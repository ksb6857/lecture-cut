# -*- coding: utf-8 -*-
"""드래프트를 새 이름으로 복제한다. 사람이 손본 편집본을 살린 채 효과를
얹으려면 원본을 덮어쓰면 안 되기 때문이다 (CLAUDE.md 2번).

**작업 사본을 평평하게 만든다.** 캡컷은 드래프트를 처음 열 때 같은 이름의
하위 폴더와 `Timelines/<GUID>/` 에 사본을 만들고 그 뒤로는 하위 사본에만
저장한다. 그대로 복사하면 새 드래프트 안에 옛 이름의 폴더가 남고 어느
쪽이 진짜인지 알 수 없게 된다. 그래서 **가장 깊은(진짜) draft_content.json
을 최상위로 올리고 하위 사본은 지운다.** 캡컷이 열면서 자기 사본을 새로
만든다.

사용: python src/duplicate_draft.py <원본 드래프트> <새 이름> [원본.mp4]
"""
import json
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from learn_from_edit import draft_content_path  # noqa: E402
from port_effects import capcut_running  # noqa: E402

from draft_root import DRAFTS  # noqa: E402


def duplicate(src_name, new_name, video=None):
    if capcut_running():
        raise SystemExit("캡컷이 실행 중입니다. 완전히 종료한 뒤 다시 실행하세요.")
    src = DRAFTS / src_name
    dest = DRAFTS / new_name
    if not src.is_dir():
        raise SystemExit(f"원본 드래프트가 없습니다: {src}")
    if dest.exists():
        raise SystemExit(f"이미 있습니다 — 덮어쓰지 않습니다: {dest}")

    real = draft_content_path(src_name)          # 사람 편집이 든 진짜 사본
    shutil.copytree(src, dest)

    # 하위 작업 사본을 걷어내고 진짜를 최상위에 놓는다
    # 하위 사본은 **이름으로 찾지 않는다.** 캡컷은 폴더가 아니라
    # `draft_name` 으로 하위 폴더를 만들어서(`2차시_효과_v2(1)` 안에
    # `2차시_효과_v2`) 이름을 맞춰 보면 놓친다. draft_content.json 을
    # 품은 하위 폴더는 전부 작업 사본이므로 지운다.
    for p in list(dest.iterdir()):
        if p.is_dir() and (p.name == "Timelines"
                           or (p / "draft_content.json").exists()):
            shutil.rmtree(p)
    shutil.copy2(real, dest / "draft_content.json")
    for junk in ("template.json", "template.json.bak", "draft.extra"):
        f = dest / junk
        if f.exists():
            f.unlink()

    # 메타의 이름·경로를 새것으로
    meta_path = dest / "draft_meta_info.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["draft_id"] = ""                        # fix_draft_meta 가 새로 발급
    meta_path.write_text(json.dumps(meta, ensure_ascii=False),
                         encoding="utf-8")
    cover = dest / "draft_cover.jpg"
    if cover.exists():
        cover.unlink()

    from fix_draft_meta import fix as fix_meta
    fix_meta(new_name, video, 25)
    size = json.loads((dest / "draft_content.json").read_text(
        encoding="utf-8"))
    print(f"복제 완료: {src_name} -> {new_name} "
          f"({size.get('duration', 0)/1e6/60:.1f}분, "
          f"진짜 사본 {real.relative_to(DRAFTS)})")
    return dest


if __name__ == "__main__":
    duplicate(*sys.argv[1:4])
