# -*- coding: utf-8 -*-
"""
STT(브루) 가 놓친 발화 구간을 골라 재전사해서 무엇이 사라졌는지 보여준다.

브루 자막에 없는데 VAD 는 발화라고 본 구간 = 자막 기준으로 자르면 날아갈 말.
그 구간만 faster-whisper 로 다시 받아쓰고, 앞뒤 문맥(브루 자막)과 나란히 출력한다.

사용: python src/inspect_missed.py <wav> <speech.json> <words.json> [개수] [모델]
"""
import json
import os
import sys
import wave
from pathlib import Path

import numpy as np

# HuggingFace 캐시가 한글 경로에 있으면 모델 로드가 깨진다 → ASCII 경로 고정
CACHE = Path(__file__).resolve().parent.parent / "models" / "hf"
CACHE.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("HF_HOME", str(CACHE))
os.environ.setdefault("HUGGINGFACE_HUB_CACHE", str(CACHE))
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS", "1")
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

SR = 16000


def overlap(a, b):
    return max(0.0, min(a[1], b[1]) - max(a[0], b[0]))


def fmt(t):
    return f"{int(t//60):02d}:{int(t%60):02d}"


def find_missed(speech, words):
    """브루가 1초 이상 무음이라 본 구간 중, VAD 가 발화를 찾은 곳"""
    gaps, prev = [], None
    for w in words:
        if prev is not None and w["start"] - prev >= 1.0:
            gaps.append([prev, w["start"]])
        prev = max(prev or 0, w["end"])

    missed = []
    for g in gaps:
        for s in speech:
            o = overlap(g, s)
            if o >= 0.5:
                missed.append([max(g[0], s[0]), min(g[1], s[1])])
    return missed


def context(words, t, before=True, n=12):
    """시각 t 직전/직후의 브루 자막 n 단어"""
    if before:
        ws = [w for w in words if w["end"] <= t][-n:]
    else:
        ws = [w for w in words if w["start"] >= t][:n]
    return " ".join(w["text"] for w in ws)


def run(wav_path, speech_path, words_path, top=10, model_size="medium"):
    speech = json.loads(Path(speech_path).read_text(encoding="utf-8"))["speech"]
    words = [w for w in json.loads(
        Path(words_path).read_text(encoding="utf-8"))["words"]
        if w["type"] == "word"]

    missed = find_missed(speech, words)
    missed.sort(key=lambda r: -(r[1] - r[0]))
    picks = missed[:int(top)]
    print(f"놓친 구간 {len(missed)}곳 중 긴 순서로 {len(picks)}곳을 재전사합니다\n")

    with wave.open(str(wav_path), "rb") as w:
        x = np.frombuffer(w.readframes(w.getnframes()),
                          dtype=np.int16).astype(np.float32) / 32768.0

    from faster_whisper import WhisperModel
    print(f"모델 로딩 ({model_size}, CPU int8)... 첫 실행은 다운로드가 있습니다")
    model = WhisperModel(model_size, device="cpu", compute_type="int8",
                         download_root=str(CACHE))
    print("로딩 완료\n" + "=" * 72)

    for a, b in picks:
        pad = 0.3
        clip = x[int(max(0, a - pad) * SR):int((b + pad) * SR)]
        segs, _ = model.transcribe(clip, language="ko", beam_size=5,
                                   vad_filter=False)
        text = " ".join(s.text.strip() for s in segs).strip()
        print(f"\n[{fmt(a)}] {b-a:.1f}초 — 브루가 버린 구간")
        print(f"  직전 자막: ...{context(words, a, True)}")
        print(f"  ▶ 실제 내용: 「{text or '(전사 실패/무의미)'}」")
        print(f"  직후 자막: {context(words, b, False)}...")
    print("\n" + "=" * 72)


if __name__ == "__main__":
    run(*sys.argv[1:6])
