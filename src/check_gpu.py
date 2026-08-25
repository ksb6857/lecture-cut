# -*- coding: utf-8 -*-
"""
이 PC 에서 GPU 전사가 가능한지 점검하고, 안 되면 무엇이 빠졌는지 알려준다.

faster-whisper 는 CTranslate2 를 쓰고, CTranslate2 4.5 이상은
CUDA 12 + cuDNN 9 가 있어야 GPU 를 쓴다. 없으면 조용히 CPU 로 떨어지는 게
아니라 오류가 나므로, 돌리기 전에 여기서 확인한다.

사용: python src/check_gpu.py
"""
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cuda_dlls  # noqa: E402  (faster_whisper 보다 먼저 와야 한다)

CACHE = Path(__file__).resolve().parent.parent / "models" / "hf"
os.environ.setdefault("HF_HOME", str(CACHE))
os.environ.setdefault("HUGGINGFACE_HUB_CACHE", str(CACHE))
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS", "1")
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

OK, NO = "  [OK] ", "  [--] "


def main():
    print("=" * 60)
    print(" GPU 전사 환경 점검")
    print("=" * 60)
    ok = True

    # 1) 그래픽카드
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total,driver_version",
             "--format=csv,noheader"],
            capture_output=True, text=True, timeout=20)
        if out.returncode == 0 and out.stdout.strip():
            for line in out.stdout.strip().splitlines():
                print(OK + f"그래픽카드: {line.strip()}")
        else:
            raise RuntimeError
    except Exception:
        print(NO + "nvidia-smi 를 찾지 못했습니다 → NVIDIA 드라이버 설치 필요")
        ok = False

    # 2) CUDA 라이브러리 (pip 로 넣는 것이 가장 간단하다)
    for pkg in ("nvidia.cublas", "nvidia.cudnn"):
        try:
            __import__(pkg)
            print(OK + f"{pkg} 설치됨")
        except Exception:
            print(NO + f"{pkg} 없음 → "
                       "pip install nvidia-cublas-cu12 nvidia-cudnn-cu12")
            ok = False

    # 윈도우는 DLL 폴더를 검색 경로에 넣어줘야 CTranslate2 가 찾는다.
    if sys.platform.startswith("win"):
        if cuda_dlls.DLL_DIRS:
            print(OK + f"CUDA DLL 경로 {len(cuda_dlls.DLL_DIRS)}곳 등록 "
                       "(cuda_dlls.py)")
        else:
            print(NO + "CUDA DLL 폴더를 못 찾음 → "
                       "pip install nvidia-cublas-cu12 nvidia-cudnn-cu12")
            ok = False

    # 3) torch (VAD 용). CPU 판이어도 VAD 는 잘 돌아간다.
    try:
        import torch
        cu = torch.cuda.is_available()
        print((OK if cu else NO) +
              f"torch {torch.__version__} / CUDA 사용 {cu}")
        if not cu:
            print("        (VAD 는 CPU 로도 충분해서 이건 없어도 됩니다)")
    except Exception as e:
        print(NO + f"torch 없음: {e}")

    # 4) 실제로 GPU 로 전사가 되는지.
    #    적재만 해 보면 안 된다 — cuBLAS 가 없어도 모델은 올라가고
    #    첫 디코딩에서야 죽는다(2026-08-13 에 이걸로 전사가 통째로 날아갔다).
    try:
        import numpy as np
        from faster_whisper import WhisperModel
        print("  ... tiny 모델로 GPU 전사 시험 중")
        m = WhisperModel("tiny", device="cuda", compute_type="float16",
                         download_root=str(CACHE))
        list(m.transcribe(np.zeros(16000, dtype=np.float32),
                          language="ko", beam_size=1)[0])
        print(OK + "faster-whisper GPU 전사 성공")
    except Exception as e:
        msg = str(e).splitlines()[0][:120]
        print(NO + f"faster-whisper GPU 전사 실패: {msg}")
        if "cublas" in msg.lower() or "cudnn" in msg.lower():
            print("        DLL 을 못 찾는 경우다 → "
                  "python src/cuda_dlls.py 로 등록 상태를 본다")
        ok = False

    print("=" * 60)
    if ok:
        print(" 준비 완료. 전사할 때 device 인자에 cuda 를 주세요:")
        print("   python src/transcribe_per_segment.py <wav> <speech.json>"
              " <out.json> large-v3 cuda")
        print(" 90분 강의 기준 CPU 1~2시간 → GPU 5~10분입니다.")
    else:
        print(" 위의 [--] 항목을 해결한 뒤 다시 실행하세요.")
        print(" 대부분 다음 한 줄로 해결됩니다:")
        print("   pip install nvidia-cublas-cu12 nvidia-cudnn-cu12")
    print("=" * 60)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
