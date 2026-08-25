# -*- coding: utf-8 -*-
"""
발화 덩어리를 **하나씩 따로** 전사해 반복 발화를 빠짐없이 드러낸다.

왜 필요한가:
  Whisper 든 브루든, 여러 발화를 한 번에 디코딩하면 같은 문장이 연달아 나올 때
  반복 억제 필터가 하나를 지운다. 그래서 "말하다 막혀서 다시 말한" 구간이
  전사본에는 한 번만 남고, 편집기는 재발화가 있었다는 사실조차 알 수 없다.
  덩어리를 하나씩 독립 디코딩하면 서로를 볼 수 없으므로 억제가 원리적으로
  일어나지 않는다.

출력: 덩어리별 전사 + 이웃끼리 유사도를 재서 재발화 후보를 표시한 JSON.
느리다(덩어리 수만큼 모델 호출). GPU 가 있으면 크게 빨라진다.

사용: python src/transcribe_per_segment.py <wav> <speech.json> <out.json>
                                           [모델] [디바이스]
"""
import difflib
import json
import os
import re
import sys
import time
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cuda_dlls  # noqa: E402,F401  (faster_whisper 보다 먼저 와야 한다)

CACHE = Path(__file__).resolve().parent.parent / "models" / "hf"
os.environ.setdefault("HF_HOME", str(CACHE))
os.environ.setdefault("HUGGINGFACE_HUB_CACHE", str(CACHE))
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS", "1")
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

SR = 16000
PAD = 0.15
GLOSSARY = (
    "AI 동화책 출판 프로젝트 연수입니다. "
    "삽화, 그림체, 기준 이미지, 캐릭터 기준 이미지, 스타일 기준 이미지, "
    "프롬프트, 고정부, 변동부, 장면 목록표, 시놉시스, 펼침면, 크라운판, "
    "ChatGPT, 제미나이, 미드저니, 나노바나나, LM 아레나, 프로젝트 기능, "
    "저작권, 워터마크, 일관성, 해상도를 다룹니다."
)


def norm(t):
    return re.sub(r"[^\w가-힣]+", "", t or "")


def similarity(a, b):
    a, b = norm(a), norm(b)
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def prefix_similarity(a, b):
    """앞 테이크가 뒤 테이크의 '앞부분'인가 (말하다 만 실패 테이크 패턴)"""
    a, b = norm(a), norm(b)
    if not a or not b or len(a) > len(b):
        return 0.0
    return difflib.SequenceMatcher(None, a, b[:len(a)]).ratio()


def be_polite():
    """이 PC 로 편집도 해야 하므로 우선순위를 낮춘다.
    안 그러면 CPU 를 다 먹어 캡컷 미리보기가 멈춘다(실제로 겪음)."""
    try:
        import ctypes
        BELOW_NORMAL = 0x00004000
        ctypes.windll.kernel32.SetPriorityClass(
            ctypes.windll.kernel32.GetCurrentProcess(), BELOW_NORMAL)
    except Exception:
        pass


def run(wav_path, speech_path, out_path, model_size="large-v3",
        device="cpu", threads=None):
    speech = json.loads(Path(speech_path).read_text(
        encoding="utf-8"))["speech"]
    with wave.open(str(wav_path), "rb") as f:
        x = np.frombuffer(f.readframes(f.getnframes()),
                          dtype=np.int16).astype(np.float32) / 32768.0

    # 중간 저장 파일. 중간에 죽어도 여기까지는 남고, 다시 돌리면 이어서 한다.
    part = Path(str(out_path) + ".partial.jsonl")
    done = {}
    if part.exists():
        for line in part.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(line)
                done[r["i"]] = r
            except Exception:
                pass
        print(f"이전 진행분 {len(done)}개를 이어받습니다")

    if device != "cuda":
        be_polite()
        if threads is None:                      # 편집용으로 코어를 남긴다
            threads = max(2, (os.cpu_count() or 4) - 4)
    threads = int(threads) if threads else 0

    from faster_whisper import WhisperModel
    ct = "float16" if device == "cuda" else "int8"
    print(f"모델 {model_size} / {device} / {ct} / 스레드 {threads or '기본'}, "
          f"덩어리 {len(speech)}개", flush=True)
    model = WhisperModel(model_size, device=device, compute_type=ct,
                         cpu_threads=threads, download_root=str(CACHE))

    takes, t0, n_new = [], time.time(), 0
    with open(part, "a", encoding="utf-8") as pf:
        for n, (a, b) in enumerate(speech):
            if n in done:
                takes.append(done[n])
                continue
            clip = x[int(max(0, a - PAD) * SR):int((b + PAD) * SR)]
            segs, _ = model.transcribe(clip, language="ko", beam_size=5,
                                       condition_on_previous_text=False,
                                       initial_prompt=GLOSSARY,
                                       vad_filter=False)
            txt = " ".join(s.text.strip() for s in segs).strip()
            rec = {"i": n, "start": a, "end": b, "text": txt}
            takes.append(rec)
            pf.write(json.dumps(rec, ensure_ascii=False) + "\n")
            pf.flush()                            # 죽어도 여기까지는 남는다
            n_new += 1
            if n_new % 10 == 0 or n == len(speech) - 1:
                el = time.time() - t0
                eta = el / n_new * (len(speech) - len(done) - n_new)
                print(f"  {n+1}/{len(speech)}  경과 {el/60:.0f}분  "
                      f"남은 예상 {eta/60:.0f}분", flush=True)

    # 이웃 덩어리끼리 비교해 재발화 후보를 표시
    cands = []
    for i in range(len(takes) - 1):
        for j in (i + 1, i + 2):            # 한 칸 건너뛴 경우도 본다
            if j >= len(takes):
                break
            if takes[j]["start"] - takes[i]["end"] > 12:
                break
            sim = similarity(takes[i]["text"], takes[j]["text"])
            pre = prefix_similarity(takes[i]["text"], takes[j]["text"])
            if sim >= 0.6 or pre >= 0.75:
                cands.append({
                    "from_i": i, "to_i": j,
                    "similarity": round(max(sim, pre), 2),
                    "kind": "동일 반복" if sim >= 0.6 else "앞부분만 말하다 중단",
                    "earlier": takes[i], "later": takes[j],
                })

    Path(out_path).write_text(json.dumps(
        {"takes": takes, "retake_candidates": cands},
        ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nOK: 덩어리 {len(takes)}개 전사, 재발화 후보 {len(cands)}건 "
          f"-> {out_path}")
    for c in cands[:20]:
        s = c["earlier"]["start"]
        print(f"  {int(s//60):02d}:{s%60:05.2f} [{c['kind']} {c['similarity']}]")
        print(f"     앞: 「{c['earlier']['text'][:60]}」")
        print(f"     뒤: 「{c['later']['text'][:60]}」")
    return cands


if __name__ == "__main__":
    run(*sys.argv[1:7])
