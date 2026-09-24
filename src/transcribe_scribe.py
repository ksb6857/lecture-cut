# -*- coding: utf-8 -*-
"""ElevenLabs Scribe 로 전사 → words.json (transcribe.py 와 같은 형식).

위스퍼 대신 쓸 수 있게 만든 것이다. 비교 시험은 stt_benchmark.py.

- **말 그대로 적는다(verbatim).** 추임새와 되풀이를 지우지 않는다. 재발화·헛시작이 전사에 남아야
  판정이 그 구간을 본다. `no_verbatim` 은 켜지 않는다
- 녹음을 30분 안팎 조각으로 나눠 올린다. 조각 경계는 발화 구간(speech.json) 사이 가장 긴 무음 한가운데라
  말이 잘리지 않는다. 조각마다 결과를 캐시에 두고, 있으면 다시 올리지 않는다(돈이 든다)
- 용어집(한 줄에 하나)을 keyterms 로 넘긴다. 항목당 50자·5낱말 이하, 최대 1000개
- 컷 경계는 여전히 파형(speech.json·refine_speech)으로 정한다. 전사 시각은 판정과 자막에만 쓴다

API 키는 `ELEVENLABS_API_KEY` 환경변수, `--key <키파일>`, `ELEVENLABS_KEY_FILE` 환경변수가 가리키는 파일,
`~/.elevenlabs.key` 순서로 찾는다. 키 파일은 동기화·커밋되지 않는 곳에 둔다.
키에 speech_to_text 권한이 있어야 한다. 요금은 시간당 0.22달러(용어 힌트 +0.05, 2026-09 기준).

사용: python transcribe_scribe.py <wav> <speech.json> <out words.json>
        [--glossary 용어집.txt] [--cache 폴더] [--chunk 1800] [--workers 3] [--key 키파일]
"""
import json
import os
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

URL = "https://api.elevenlabs.io/v1/speech-to-text"
MODEL = "scribe_v2"
KEY_FILE = os.environ.get("ELEVENLABS_KEY_FILE", str(Path.home() / ".elevenlabs.key"))


def api_key(path=None):
    k = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    if k:
        return k
    p = Path(path or KEY_FILE)
    if p.exists():
        return p.read_text(encoding="utf-8").strip()
    raise SystemExit("ElevenLabs API 키가 없습니다. ELEVENLABS_API_KEY 나 --key 로 주세요.\n"
                     "키가 없으면 무료인 위스퍼 길(transcribe.py)로 전사하면 됩니다(SKILL.md 2단계).")


def split_points(speech, total, chunk=1800.0, reach=180.0):
    """chunk 초마다, 그 근처(±reach) 발화 사이 가장 긴 무음 한가운데에서 나눈다."""
    gaps = [(speech[k][1], speech[k + 1][0]) for k in range(len(speech) - 1)]
    cuts, t = [0.0], chunk
    while t < total - chunk / 3:
        near = [g for g in gaps if abs((g[0] + g[1]) / 2 - t) <= reach and g[1] - g[0] >= 0.5]
        if near:
            g = max(near, key=lambda g: g[1] - g[0])
            cut = (g[0] + g[1]) / 2
        else:
            cut = t
        cuts.append(round(cut, 3))
        t = cut + chunk
    cuts.append(total)
    return list(zip(cuts[:-1], cuts[1:]))


def keyterms_from(path):
    if not path or not Path(path).exists():
        return []
    terms = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        t = line.strip()
        if not t or t.startswith("#"):
            continue
        if len(t) <= 50 and len(t.split()) <= 5:
            terms.append(t)
    return terms[:1000]


def call(wav, key, keyterms, tries=3):
    data = [("model_id", MODEL), ("language_code", "ko"), ("timestamps_granularity", "word"),
            ("tag_audio_events", "true"), ("diarize", "false")]
    data += [("keyterms", t) for t in keyterms]
    for k in range(tries):
        with open(wav, "rb") as f:
            r = requests.post(URL, headers={"xi-api-key": key},
                              files={"file": (Path(wav).name, f, "audio/wav")}, data=data, timeout=3600)
        if r.status_code == 200:
            return r.json()
        if r.status_code in (401, 403):
            raise SystemExit(f"Scribe 권한 오류 {r.status_code}: {r.text[:300]}")
        time.sleep(10 * (k + 1))
    raise SystemExit(f"Scribe 실패 {r.status_code}: {r.text[:300]}")


def transcribe_piece(src, a, b, cache, key, keyterms, n):
    out = Path(cache) / f"{Path(src).stem}_{n:02d}_{a:.0f}-{b:.0f}.json"
    if out.exists():
        return n, a, json.loads(out.read_text(encoding="utf-8")), True
    with tempfile.TemporaryDirectory() as td:
        wav = Path(td) / "piece.wav"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{a:.3f}", "-t", f"{b - a:.3f}", "-i", str(src),
                        "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(wav)], check=True)
        d = call(wav, key, keyterms)
    out.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    return n, a, d, False


def to_words(pieces):
    """조각 응답들 → words.json 의 words (원본 시각). spacing 은 버리고 낱말·소리 표시만 남긴다."""
    words = []
    for n, a, d in sorted(pieces, key=lambda p: p[0]):
        for w in d.get("words", []):
            if w.get("type") == "spacing":
                continue
            words.append({"i": len(words), "type": "word" if w["type"] == "word" else w["type"],
                          "text": w["text"].strip(), "start": round(a + w["start"], 3),
                          "end": round(a + w["end"], 3), "clip": n,
                          "logprob": round(w.get("logprob", 0.0), 3)})
    return words


def main(argv):
    pos, opt, k = [], {}, 0
    while k < len(argv):
        if argv[k].startswith("--"):
            opt[argv[k]] = argv[k + 1]
            k += 2
        else:
            pos.append(argv[k])
            k += 1
    src, speech_p, out_p = pos[:3]
    speech = json.loads(Path(speech_p).read_text(encoding="utf-8"))["speech"]
    total = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of",
                                  "csv=p=0", src], capture_output=True, text=True).stdout.strip())
    cache = Path(opt.get("--cache", Path(out_p).parent / "scribe"))
    cache.mkdir(parents=True, exist_ok=True)
    key = api_key(opt.get("--key"))
    terms = keyterms_from(opt.get("--glossary"))
    parts = split_points(speech, total, float(opt.get("--chunk", 1800)))
    hours = total / 3600
    print(f"{Path(src).name}: {total / 60:.1f}분 → 조각 {len(parts)}개 · 용어 {len(terms)}개 · "
          f"예상 요금 {hours * (0.22 + (0.05 if terms else 0)):.2f}달러(캐시에 있는 조각은 빼고)", flush=True)
    with ThreadPoolExecutor(max_workers=int(opt.get("--workers", 3))) as ex:
        futs = [ex.submit(transcribe_piece, src, a, b, cache, key, terms, n) for n, (a, b) in enumerate(parts)]
        pieces = []
        for f in futs:
            n, a, d, cached = f.result()
            pieces.append((n, a, d))
            print(f"  조각 {n}: {a / 60:6.1f}분부터 · 낱말 {sum(1 for w in d.get('words', []) if w.get('type') == 'word')}"
                  f"{' (캐시)' if cached else ''}", flush=True)
    words = to_words(pieces)
    doc = {"source_stt": f"elevenlabs {MODEL}", "media_files": [Path(src).name],
           "total_end": max((w["end"] for w in words), default=0), "words": words,
           "keyterms": len(terms), "pieces": [[a, b] for a, b in parts]}
    Path(out_p).write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    n_word = sum(1 for w in words if w["type"] == "word")
    n_event = sum(1 for w in words if w["type"] == "audio_event")
    print(f"낱말 {n_word} · 소리 표시 {n_event} → {out_p}")


if __name__ == "__main__":
    main(sys.argv[1:])
