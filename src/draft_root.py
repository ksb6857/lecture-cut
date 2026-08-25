# -*- coding: utf-8 -*-
r"""캡컷 드래프트 폴더를 찾는다.

컴퓨터마다 사용자명이 다르고, 캡컷을 다른 드라이브에 설치한 사람도 있다.
그래서 경로를 코드에 박지 않고 여기서 한 번만 찾는다.

찾는 순서
  1. 환경변수 `CAPCUT_DRAFT_ROOT` (직접 지정)
  2. Windows: %LOCALAPPDATA%\CapCut\User Data\Projects\com.lveditor.draft
  3. macOS:   ~/Movies/CapCut/User Data/Projects/com.lveditor.draft

없으면 `DRAFTS` 를 읽는 순간 이유를 적어 멈춘다. 예전에는 모듈마다
`os.environ["LOCALAPPDATA"]` 를 직접 읽어서, 캡컷을 D 드라이브에 깔았거나
맥에서 돌리면 임포트 단계에서 KeyError 로 죽었다.
"""
import os
from pathlib import Path

_SUB = ("CapCut", "User Data", "Projects", "com.lveditor.draft")


def candidates():
    out = []
    local = os.environ.get("LOCALAPPDATA")
    if local:
        out.append(Path(local).joinpath(*_SUB))
    out.append(Path.home() / "Movies" / Path(*_SUB))
    return out


def find_draft_root(required: bool = True) -> Path:
    env = os.environ.get("CAPCUT_DRAFT_ROOT")
    if env:
        return Path(env)
    cand = candidates()
    for c in cand:
        if c.is_dir():
            return c
    if not required:
        return cand[0]
    raise SystemExit(
        "캡컷 드래프트 폴더를 찾지 못했습니다. 캡컷 설치를 확인하거나\n"
        "환경변수 CAPCUT_DRAFT_ROOT 에 경로를 직접 지정하세요.\n"
        "  찾아본 경로: " + "\n              ".join(str(c) for c in cand)
    )


DRAFTS = find_draft_root(required=False)
