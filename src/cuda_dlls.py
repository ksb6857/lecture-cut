# -*- coding: utf-8 -*-
"""
pip 로 깐 CUDA 라이브러리를 윈도우가 찾게 해 준다.

`nvidia-cublas-cu12` / `nvidia-cudnn-cu12` 는 DLL 을
`site-packages/nvidia/*/bin` 에 넣는다. 리눅스에서는 패키지가 알아서 잡히지만
윈도우에서는 torch 가 CUDA 판일 때만 이 폴더들을 검색 경로에 넣어준다.
torch 가 CPU 판이면(우리는 VAD 에만 쓰므로 CPU 판으로 충분하다) 아무도 안
넣어주고, 모델은 올라가는데 첫 디코딩에서
`Library cublas64_12.dll is not found or cannot be loaded` 로 죽는다.

CTranslate2 는 `LoadLibrary` 로 DLL 을 직접 부르므로 PATH 를 고쳐야 잡히고,
파이썬 확장 모듈의 의존 DLL 은 `add_dll_directory` 로 잡힌다. 둘 다 해 둔다.

`faster_whisper` 를 import 하기 **전에** 이 모듈을 import 하면 된다.
"""
import os
import sys
from pathlib import Path


def enable():
    """찾아서 등록한 DLL 폴더 목록을 돌려준다 (윈도우 아니면 빈 목록)."""
    if not sys.platform.startswith("win"):
        return []
    added = []
    for site in map(Path, sys.path):
        root = site / "nvidia"
        if not root.is_dir():
            continue
        for sub in sorted(root.iterdir()):
            b = sub / "bin"
            if not b.is_dir() or str(b) in added:
                continue
            try:
                os.add_dll_directory(str(b))       # 확장 모듈 의존성용
            except OSError:
                continue
            added.append(str(b))
    if added:                                       # CTranslate2 의 LoadLibrary 용
        path = os.environ.get("PATH", "")
        head = os.pathsep.join(p for p in added if p not in path)
        if head:
            os.environ["PATH"] = head + os.pathsep + path
    return added


DLL_DIRS = enable()


if __name__ == "__main__":
    if not DLL_DIRS:
        print("등록된 CUDA DLL 폴더 없음 "
              "(pip install nvidia-cublas-cu12 nvidia-cudnn-cu12)")
    for d in DLL_DIRS:
        print("등록:", d)
