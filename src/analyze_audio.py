# -*- coding: utf-8 -*-
"""
영상/오디오 -> 실제 발화 구간 (speech.json)

Silero VAD 로 파형에서 직접 사람 목소리를 검출한다.
자막(STT) 타임스탬프와 달리 키보드 소리·마우스 클릭·숨소리를 발화로 치지 않고,
경계도 30ms 수준으로 정확하다. 컷 편집의 기준은 이 결과를 쓴다.

사용: python src/analyze_audio.py <입력.mp4|wav> <출력 speech.json>
"""
import json
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

import numpy as np
import torch

SR = 16000
MODEL_PATH = Path(__file__).resolve().parent.parent / "models" / "silero_vad.jit"

# 강의 영상 기준값
VAD_PARAMS = {
    "threshold": 0.5,
    "min_speech_duration_ms": 80,    # 짧은 감탄사도 놓치지 않게
    "min_silence_duration_ms": 200,  # 이보다 짧은 끊김은 발화 내부로 본다
    "speech_pad_ms": 0,              # 여유분은 컷 단계에서 따로 준다
}


def ensure_model() -> Path:
    """torch 는 한글이 섞인 경로의 모델을 못 연다(errno 42).
    silero_vad 패키지 안의 모델을 ASCII 경로인 models/ 로 한 번 복사해 둔다."""
    if MODEL_PATH.exists():
        return MODEL_PATH
    import shutil
    import silero_vad
    src = Path(silero_vad.__file__).parent / "data" / "silero_vad.jit"
    if not src.exists():
        raise SystemExit(f"silero_vad 모델을 찾지 못했습니다: {src}")
    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, MODEL_PATH)
    print(f"VAD 모델 준비 완료 -> {MODEL_PATH}")
    return MODEL_PATH


def to_wav(src, dst):
    subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(src), "-vn", "-ac", "1",
         "-ar", str(SR), "-c:a", "pcm_s16le", "-y", str(dst)],
        check=True,
    )


def read_wav(path):
    with wave.open(str(path), "rb") as w:
        assert w.getframerate() == SR and w.getnchannels() == 1
        raw = w.readframes(w.getnframes())
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0


def needs_convert(path):
    """이미 16kHz 모노 wav 인가. **확장자만 보면 안 된다** — 편집본에서 뽑은
    wav 는 44.1kHz 스테레오라 그대로 읽으면 assert 에서 죽는다."""
    if Path(path).suffix.lower() != ".wav":
        return True
    try:
        with wave.open(str(path), "rb") as w:
            return not (w.getframerate() == SR and w.getnchannels() == 1
                        and w.getsampwidth() == 2)
    except Exception:
        return True


def analyze(src_path, out_path):
    src = Path(src_path)
    tmp = None
    if needs_convert(src):
        tmp = Path(tempfile.gettempdir()) / "lecture_autocut_vad.wav"
        print(f"16kHz 모노로 변환 중... ({src.name})")
        to_wav(src, tmp)
        wav_path = tmp
    else:
        wav_path = src

    x = read_wav(wav_path)
    dur = len(x) / SR
    print(f"길이 {dur/60:.1f}분, VAD 분석 시작")

    model = torch.jit.load(str(ensure_model()), map_location="cpu")
    model.eval()
    from silero_vad import get_speech_timestamps

    ts = get_speech_timestamps(
        torch.from_numpy(x), model, sampling_rate=SR,
        return_seconds=True, **VAD_PARAMS,
    )

    segs = [[round(float(t["start"]), 3), round(float(t["end"]), 3)]
            for t in ts]
    total = sum(b - a for a, b in segs)
    result = {
        "source": src.name,
        "duration": round(dur, 3),
        "vad_params": VAD_PARAMS,
        "n_segments": len(segs),
        "speech_duration": round(total, 3),
        "speech": segs,
    }
    Path(out_path).write_text(
        json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"OK: 발화 {len(segs)}구간, {total/60:.1f}분 "
          f"({100*total/dur:.1f}%) -> {out_path}")

    if tmp and tmp.exists():
        tmp.unlink()
    return result


if __name__ == "__main__":
    analyze(sys.argv[1], sys.argv[2])
