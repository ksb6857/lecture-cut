# -*- coding: utf-8 -*-
"""
전사가 삼켜버린 반복 발화를 찾아낸다.

Whisper 는 같은 문장이 연달아 나오면 반복 억제 필터가 하나를 지운다.
브루도 같은 짓을 했다. 문제는 전사본만 봐서는 반복이 있었는지 알 수 없다는 것.

하지만 흔적이 남는다: 지워진 자리를 메우려고 **직전 단어의 타임스탬프가
비정상적으로 늘어난다.** 실제 사례(2차시 02:27):
  입력된(0.4초) 문장의(0.6초) 맥락과(0.7초) 숨겨진(4.96초!) 의도까지(0.5초)
  → VAD 는 147.6~150.3 과 151.7~155.9 두 덩어리를 봤는데 전사는 한 번뿐.
  실제로는 "입력된 문장의 맥락과"를 말하다 끊고 다시 말한 것이었다.

한국어 단어는 보통 0.2~0.6초다. 1.5초를 넘으면 뭔가 삼킨 것이다.
해당 구간을 VAD 덩어리별로 따로 재전사하면 (짧은 클립은 반복 억제가
걸리지 않으므로) 감춰졌던 반복이 드러난다.

사용: python src/find_hidden_retakes.py <wav> <speech.json> <words.json>
                                        <out.json> [모델]
"""
import json
import os
import sys
import wave
from pathlib import Path

import numpy as np

CACHE = Path(__file__).resolve().parent.parent / "models" / "hf"
os.environ.setdefault("HF_HOME", str(CACHE))
os.environ.setdefault("HUGGINGFACE_HUB_CACHE", str(CACHE))
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS", "1")
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

SR = 16000
LONG_WORD = 1.5      # 이보다 긴 단어는 전사가 뭔가 삼킨 신호
MIN_SWALLOWED = 1.0  # 그 단어가 '다음 발화 덩어리'를 이만큼 덮으면 의심 확정
PAD = 0.15
# 단어 길이만 보면 오탐이 많다(문장 끝 단어는 원래 무음까지 늘어난다).
# '다음 발화 덩어리를 얼마나 덮는가' = 삼킨 말의 양으로 걸러야 정확하다.


def overlap(a, b):
    return max(0.0, min(a[1], b[1]) - max(a[0], b[0]))


def run(wav_path, speech_path, words_path, out_path, model_size="large-v3"):
    speech = json.loads(Path(speech_path).read_text(encoding="utf-8"))["speech"]
    words = [w for w in json.loads(Path(words_path).read_text(
        encoding="utf-8"))["words"] if w["type"] == "word"]

    suspects = []
    for w in words:
        dur = w["end"] - w["start"]
        if dur < LONG_WORD:
            continue
        span = (w["start"], w["end"])
        segs = [s for s in speech if overlap(span, s) > 0.1]
        if len(segs) < 2:          # 발화 덩어리 두 개 이상에 걸쳐야 의심
            continue
        swallowed = sum(overlap(span, s) for s in segs[1:])
        if swallowed < MIN_SWALLOWED:
            continue
        suspects.append({"word": w["text"], "start": w["start"],
                         "end": w["end"], "dur": round(dur, 2),
                         "swallowed": round(swallowed, 2), "segments": segs})

    print(f"의심 구간 {len(suspects)}곳 (단어가 {LONG_WORD}초 넘게 늘어난 곳)")
    if not suspects:
        Path(out_path).write_text(json.dumps({"suspects": []},
                                             ensure_ascii=False, indent=1),
                                  encoding="utf-8")
        return []

    with wave.open(str(wav_path), "rb") as f:
        x = np.frombuffer(f.readframes(f.getnframes()),
                          dtype=np.int16).astype(np.float32) / 32768.0

    from faster_whisper import WhisperModel
    print(f"모델 로딩 ({model_size})...")
    model = WhisperModel(model_size, device="cpu", compute_type="int8",
                         cpu_threads=os.cpu_count(), download_root=str(CACHE))

    out = []
    for n, s in enumerate(suspects, 1):
        texts = []
        for a, b in s["segments"]:
            clip = x[int(max(0, a - PAD) * SR):int((b + PAD) * SR)]
            segs, _ = model.transcribe(clip, language="ko", beam_size=5,
                                       condition_on_previous_text=False,
                                       vad_filter=False)
            t = " ".join(q.text.strip() for q in segs).strip()
            texts.append({"start": a, "end": b, "text": t})
        s2 = {"trigger_word": s["word"], "at": s["start"],
              "stretched": s["dur"], "takes": texts}
        out.append(s2)
        m = int(s["start"] // 60)
        print(f"  [{n}/{len(suspects)}] {m:02d}:{s['start'] % 60:05.2f} "
              f"'{s['word']}' {s['dur']}초")
        for t in texts:
            print(f"      {t['start']:.1f}~{t['end']:.1f}  「{t['text']}」")

    Path(out_path).write_text(
        json.dumps({"suspects": out}, ensure_ascii=False, indent=1),
        encoding="utf-8")
    print(f"\nOK -> {out_path}")
    return out


if __name__ == "__main__":
    run(*sys.argv[1:6])
