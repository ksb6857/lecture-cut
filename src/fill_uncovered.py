# -*- coding: utf-8 -*-
"""Scribe 전사가 덮지 않은 소리를 조각마다 다시 전사해 메운다.

Scribe 는 말 그대로 적는 설정이어도 실패 테이크·되풀이·헛시작을 지운다. 「제목을 제목을」을 「제목을」로 적고,
말하다 멈춘 문장은 통째로 뺀다. 그대로 쓰면 재발화 검출이 그 구간을 못 보고 실패 테이크가 컷에 남는다.
대신 Scribe 는 낱말 시각이 정확해서(한 강의에서 쉼 뒤 첫 낱말 90%가 0.09초 안) 지운 곳이
'소리는 나는데 어느 낱말에도 안 걸리는 곳'으로 드러난다. 그 강의에서 50곳 31초였고, 열어 본 곳은 거의 다
실패 테이크·되풀이였다. 위스퍼는 시각이 1초까지 흔들려 같은 방법이 안 된다.

- 덮지 않은 소리: 발화 구간 안에서 -45dB 넘는 10ms 틀이 어느 낱말(앞뒤 0.08초 여유)에도 안 걸리는 곳.
  0.12초 안 틈은 잇고, 소리가 0.2초 이상인 것만 본다
- 조각마다 따로(앞뒤 0.1초 여유) Scribe 로 다시 전사한다. 앞뒤 문맥이 없으면 지우지 않는다
- 나온 낱말은 원본 시각으로 옮겨 끼우고 `fill: "uncovered"` 를 붙인다. 이미 있는 낱말과 겹치는 것은 뺀다.
  재발화 검출(find_repeat_retakes)을 이 파일로 돌리면 되풀이가 보인다
- 다시 전사해도 낱말이 안 나온 곳(숨·잡음·다른 소리)은 목록에만 남긴다
- Scribe 가 소리 표시([입 푸는 소리] 같은 audio_event)로 적은 곳은 덮인 것으로 본다. 입술 떠는 소리를 다시 전사하면
  「부르르르…」를 수천 자 적는다. 같은 글자가 여섯 번 넘게 이어지거나 1초에 20자가 넘는 낱말은 버린다
- 조각 결과는 캐시에 둔다. 다시 돌려도 다시 올리지 않는다(돈이 든다)

사용: python fill_uncovered.py <wav> <speech.json> <words.json> <out words.json>
        [--levels 세기캐시.npy] [--glossary 용어집.txt] [--cache 폴더] [--key 키파일] [--report 목록.json]
"""
import json
import re
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import audio_levels as L  # noqa: E402
# transcribe_scribe(requests)는 실제로 다시 전사할 때만 부른다. uncovered() 만 쓰는 stt_benchmark 는 키·requests 없이 돈다

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

PAD, MIN_SOUND, JOIN, MARGIN = 0.08, 0.2, 0.12, 0.1


def uncovered(words, speech, db, pad=PAD, min_sound=MIN_SOUND, join=JOIN):
    """[(시작, 끝, 소리 초)] 낱말이 덮지 않은 소리."""
    h, n = L.HOP, len(db)
    cover = np.zeros(n, bool)
    for w in words:
        cover[max(0, int((w["start"] - pad) / h)):min(n, int((w["end"] + pad) / h) + 1)] = True
    inside = np.zeros(n, bool)
    for a, b in speech:
        inside[int(a / h):min(n, int(b / h) + 1)] = True
    idx = np.where((db > L.ON_SOUND) & inside & ~cover)[0]
    runs = []
    if len(idx):
        s = p = idx[0]
        c = 1
        for i in idx[1:]:
            if (i - p) * h <= join:
                p, c = i, c + 1
            else:
                runs.append((s, p, c))
                s, p, c = i, i, 1
        runs.append((s, p, c))
    return [(round(s * h, 3), round((e + 1) * h, 3), round(c * h, 3)) for s, e, c in runs if c * h >= min_sound]


def looks_like_noise(text, dur):
    """입술 떨기·잡음을 글자로 적은 것: 같은 글자 여섯 번 넘게, 또는 1초에 20자 넘게."""
    return bool(re.search(r"(.)\1{5,}", text)) or len(text) / max(dur, 0.05) > 20


def transcribe_stretch(wav, a, b, cache, key, terms):
    from transcribe_scribe import call
    out = Path(cache) / f"{Path(wav).stem}_unc_{a:.2f}-{b:.2f}.json"
    if out.exists():
        return json.loads(out.read_text(encoding="utf-8")), True
    with tempfile.TemporaryDirectory() as td:
        clip = Path(td) / "c.wav"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{a:.3f}", "-t", f"{b - a:.3f}", "-i", str(wav),
                        "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(clip)], check=True)
        d = call(clip, key, terms)
    out.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    return d, False


def main(argv):
    pos, opt, k = [], {}, 0
    while k < len(argv):
        if argv[k].startswith("--"):
            opt[argv[k]] = argv[k + 1]
            k += 2
        else:
            pos.append(argv[k])
            k += 1
    wav, speech_p, words_p, out_p = pos[:4]
    speech = json.loads(Path(speech_p).read_text(encoding="utf-8"))["speech"]
    doc = json.loads(Path(words_p).read_text(encoding="utf-8"))
    words = [w for w in doc["words"] if w.get("type", "word") == "word" and w["text"].strip()]
    events = [w for w in doc["words"] if w.get("type") == "audio_event"]
    db = L.compute(wav, opt.get("--levels"))
    total = len(db) * L.HOP
    spots = uncovered(words + events, speech, db)
    print(f"덮지 않은 소리 {len(spots)}곳 · 소리 {sum(c for *_, c in spots):.1f}초", flush=True)
    from transcribe_scribe import api_key, keyterms_from
    cache = Path(opt.get("--cache", Path(out_p).parent / "scribe_uncovered"))
    cache.mkdir(parents=True, exist_ok=True)
    key = api_key(opt.get("--key"))
    terms = keyterms_from(opt.get("--glossary"))
    clips = [(max(0.0, a - MARGIN), min(total, b + MARGIN)) for a, b, _ in spots]
    with ThreadPoolExecutor(max_workers=4) as ex:
        res = list(ex.map(lambda c: transcribe_stretch(wav, c[0], c[1], cache, key, terms), clips))
    spans = [(w["start"], w["end"]) for w in words]
    added, report = [], []
    for (a, b, sound), (ca, cb), (d, cached) in zip(spots, clips, res):
        got, noise = [], []
        for w in d.get("words", []):
            if w.get("type") != "word" or not w["text"].strip():
                continue
            s, e = round(ca + w["start"], 3), round(ca + w["end"], 3)
            mid = (s + e) / 2
            if any(p <= mid <= q for p, q in spans):
                continue                      # 이미 있는 낱말을 다시 적은 것
            if looks_like_noise(w["text"].strip(), e - s):
                noise.append(w["text"].strip()[:12] + "…")
                continue
            got.append({"type": "word", "text": w["text"].strip(), "start": s, "end": e, "clip": -1,
                        "logprob": round(w.get("logprob", 0.0), 3), "fill": "uncovered"})
        added += got
        report.append({"from": a, "to": b, "sound": sound, "text": " ".join(g["text"] for g in got),
                       "noise": noise})
    rest = [w for w in doc["words"] if not (w.get("type", "word") == "word" and w["text"].strip())]
    merged = sorted(words + added + rest, key=lambda w: (w["start"], w["end"]))
    for i, w in enumerate(merged):
        w["i"] = i
    doc["words"] = merged
    doc["source_stt"] = doc.get("source_stt", "stt") + " + 덮지 않은 소리 메움"
    doc["filled_uncovered"] = {"spots": len(spots), "words_added": len(added),
                               "empty": sum(1 for r in report if not r["text"])}
    Path(out_p).write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    if "--report" in opt:
        Path(opt["--report"]).write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    empty = [r for r in report if not r["text"]]
    print(f"다시 전사: 낱말 {len(added)}개를 {len(spots) - len(empty)}곳에 끼움 · 낱말이 안 나온 곳 {len(empty)}")
    for r in report[:80]:
        extra = f"  [잡음으로 버림: {', '.join(r['noise'])}]" if r["noise"] else ""
        print(f"  {r['from']:9.2f}~{r['to']:9.2f} 소리 {r['sound']:.2f}초  {r['text'] or '(없음)'}{extra}")
    print(f"→ {out_p}")


if __name__ == "__main__":
    main(sys.argv[1:])
