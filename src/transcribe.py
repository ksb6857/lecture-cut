# -*- coding: utf-8 -*-
"""
음성 인식 (faster-whisper) -> words.json

브루/캡컷의 자동 자막을 대체한다. 출력 형식은 extract_vrew.py 와 동일해서
이후 파이프라인(청크 분석 → 컷 → 드래프트)을 그대로 쓸 수 있다.

설계 요점:
- **VAD 발화 구간을 묶어서 전사한다.** 통짜로 넣으면 Whisper 가 긴 무음에서
  환각을 만들고("시청해주셔서 감사합니다"), 침묵 사이 짧은 발화를 통째로
  버린다(브루가 4.2분을 날린 이유). 발화만 이어붙여 넣으면 둘 다 막힌다.
- 청크는 25초 안팎으로 묶되 반드시 무음에서만 자른다 → 말이 잘리지 않는다.
- condition_on_previous_text=False : 한 번 틀린 전사가 뒤로 전염되는 것을 막는다.
- initial_prompt 로 강의 전문용어를 미리 알려준다 (삽화/프롬프트/ChatGPT 등).

사용: python src/transcribe.py <wav|mp4> <speech.json> <out words.json>
                              [모델] [디바이스] [용어파일]
      디바이스는 cuda 또는 cpu (기본 cpu)
"""
import json
import os
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cuda_dlls  # noqa: E402,F401  (faster_whisper 보다 먼저 와야 한다)

CACHE = Path(__file__).resolve().parent.parent / "models" / "hf"
CACHE.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("HF_HOME", str(CACHE))
os.environ.setdefault("HUGGINGFACE_HUB_CACHE", str(CACHE))
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS", "1")
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

SR = 16000
CHUNK_TARGET = 25.0      # 청크 목표 길이(초) — 문맥은 주되 너무 길지 않게
CHUNK_MAX = 30.0         # Whisper 입력 상한
JOIN_GAP = 0.6           # 이보다 짧은 공백은 청크 안에서 유지

# 이 강의 도메인 용어. 모르는 단어를 엉뚱하게 받아쓰는 것을 크게 줄여준다.
GLOSSARY = (
    "AI 동화책 출판 프로젝트 연수입니다. "
    "삽화, 그림체, 기준 이미지, 캐릭터 기준 이미지, 스타일 기준 이미지, "
    "프롬프트, 고정부, 변동부, 장면 목록표, 시놉시스, 펼침면, 크라운판, "
    "ChatGPT, 제미나이, 미드저니, 나노바나나, LM 아레나, 프로젝트 기능, "
    "저작권, 워터마크, 일관성, 해상도를 다룹니다."
)


def to_wav(src, dst):
    subprocess.run(["ffmpeg", "-v", "error", "-i", str(src), "-vn", "-ac", "1",
                    "-ar", str(SR), "-c:a", "pcm_s16le", "-y", str(dst)],
                   check=True)


def read_wav(path):
    with wave.open(str(path), "rb") as w:
        if not (w.getframerate() == SR and w.getnchannels() == 1
                and w.getsampwidth() == 2):
            raise SystemExit(
                f"16kHz 모노 wav 가 아닙니다 ({w.getframerate()}Hz "
                f"{w.getnchannels()}채널). 먼저 변환하세요.")
        raw = w.readframes(w.getnframes())
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0


def needs_convert(path):
    """이미 16kHz 모노 wav 인가.

    **확장자만 보고 넘기면 조용히 망가진다.** 편집본에서 뽑은 wav 는 44.1kHz
    스테레오라, 그대로 읽으면 바이트를 16kHz 모노로 잘못 해석해 소리가 3배
    느려지고 좌우 채널이 뒤섞인다. 전사가 되긴 되는데 시각이 전부 틀린다.
    """
    if Path(path).suffix.lower() != ".wav":
        return True
    try:
        with wave.open(str(path), "rb") as w:
            return not (w.getframerate() == SR and w.getnchannels() == 1
                        and w.getsampwidth() == 2)
    except Exception:
        return True


def make_chunks(speech):
    """VAD 발화 구간들을 25초 안팎 청크로 묶는다. 경계는 항상 무음."""
    chunks, cur = [], None
    for s, e in speech:
        if cur is None:
            cur = [s, e]
            continue
        gap = s - cur[1]
        would = e - cur[0]
        if would <= CHUNK_TARGET or (gap <= JOIN_GAP and would <= CHUNK_MAX):
            cur[1] = e
        else:
            chunks.append(cur)
            cur = [s, e]
    if cur:
        chunks.append(cur)
    return chunks


def run(src_path, speech_path, out_path, model_size="large-v3",
        device="cpu", glossary_path=None, limit=None):
    src = Path(src_path)
    tmp = None
    if needs_convert(src):
        tmp = Path(tempfile.gettempdir()) / "lecture_autocut_stt.wav"
        print(f"16kHz 모노로 변환 중... ({src.name})")
        to_wav(src, tmp)
        wav = tmp
    else:
        wav = src

    x = read_wav(wav)
    speech = json.loads(Path(speech_path).read_text(encoding="utf-8"))["speech"]
    if limit:
        speech = [s for s in speech if s[1] <= float(limit)]

    prompt = GLOSSARY
    if glossary_path and Path(glossary_path).exists():
        prompt = Path(glossary_path).read_text(encoding="utf-8").strip()

    chunks = make_chunks(speech)
    talk = sum(e - s for s, e in chunks)
    print(f"발화 {talk/60:.1f}분을 {len(chunks)}개 청크로 전사합니다 "
          f"(모델 {model_size})")

    from faster_whisper import WhisperModel
    ct = "float16" if device == "cuda" else "int8"
    model = WhisperModel(model_size, device=device, compute_type=ct,
                         cpu_threads=os.cpu_count(), download_root=str(CACHE))
    print("모델 로딩 완료, 시작\n")

    words, i, done = [], 0, 0.0
    import time
    t0 = time.time()
    for n, (cs, ce) in enumerate(chunks):
        clip = x[int(cs * SR):int(ce * SR)]
        segs, _ = model.transcribe(
            clip, language="ko", beam_size=5, word_timestamps=True,
            condition_on_previous_text=False, initial_prompt=prompt,
            vad_filter=False,
        )
        for seg in segs:
            for wd in (seg.words or []):
                t = wd.word.strip()
                if not t:
                    continue
                words.append({
                    "i": i, "type": "word", "text": t,
                    "start": round(cs + wd.start, 3),
                    "end": round(cs + wd.end, 3),
                    "clip": n,
                })
                i += 1
        done += ce - cs
        if (n + 1) % 20 == 0 or n == len(chunks) - 1:
            el = time.time() - t0
            eta = el / max(done, 1e-6) * (talk - done)
            print(f"  {n+1}/{len(chunks)} 청크  ({done/60:.1f}/{talk/60:.1f}분)  "
                  f"경과 {el/60:.0f}분  남은 예상 {eta/60:.0f}분")

    result = {
        "source_stt": f"faster-whisper {model_size}",
        "media_files": [src.name],
        "total_end": max((w["end"] for w in words), default=0),
        "words": words,
    }
    Path(out_path).write_text(
        json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nOK: 단어 {len(words)}개, "
          f"소요 {(time.time()-t0)/60:.0f}분 -> {out_path}")

    if tmp and tmp.exists():
        tmp.unlink()
    return result


if __name__ == "__main__":
    run(*sys.argv[1:7])
