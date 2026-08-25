# -*- coding: utf-8 -*-
"""
pycapcut 이 만든 드래프트를 캡컷 프로젝트 목록에 제대로 뜨게 고친다.

pycapcut 은 draft_meta_info.json 에 draft_name / draft_fold_path /
draft_root_path / draft_cover / tm_draft_create 를 비워둔 채로 저장한다.
캡컷은 이 값으로 목록을 그리기 때문에 이름도 경로도 없는 항목은 표시되지 않는다.
정상 프로젝트와 같은 형태로 채워 넣고, 표지 이미지도 만들어 준다.

**캡컷을 완전히 종료한 뒤 실행할 것.**
캡컷은 종료할 때 메모리에 있던 목록으로 root_meta_info.json 을 덮어쓴다.

사용: python src/fix_draft_meta.py <드래프트이름> [<원본영상> <표지시각(초)>]
"""
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from draft_root import DRAFTS  # noqa: E402
ROOT = DRAFTS.parent.parent


def now_us():
    return int(time.time() * 1_000_000)


def make_cover(video, out_jpg, at=3.0):
    try:
        subprocess.run(
            ["ffmpeg", "-v", "error", "-ss", str(at), "-i", str(video),
             "-frames:v", "1", "-vf", "scale=400:-2", "-y", str(out_jpg)],
            check=True)
        return out_jpg.exists()
    except Exception as e:
        print(f"  표지 생성 실패(무시 가능): {e}")
        return False


def fix(name, video=None, cover_at=3.0):
    folder = DRAFTS / name
    if not folder.is_dir():
        raise SystemExit(f"드래프트 폴더가 없습니다: {folder}")

    meta_path = folder / "draft_meta_info.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    content = json.loads((folder / "draft_content.json").read_text(
        encoding="utf-8"))

    fold = str(folder).replace("\\", "/")
    cover_file = folder / "draft_cover.jpg"
    if video and not cover_file.exists():
        make_cover(Path(video), cover_file, cover_at)

    created = meta.get("tm_draft_create") or now_us()
    meta.update({
        "draft_id": meta.get("draft_id") or str(uuid.uuid4()).upper(),
        "draft_name": name,
        "draft_fold_path": fold,
        "draft_root_path": str(ROOT),
        "draft_cover": "draft_cover.jpg" if cover_file.exists() else "",
        "tm_draft_create": created,
        "tm_draft_modified": now_us(),
        "draft_need_rename_folder": False,
        "draft_is_pippit_draft": False,
        "draft_is_web_article_video": False,
        "draft_web_article_video_enter_from": "",
        "pippit_avatar_url": "", "pippit_extra_info": "",
        "pippit_id": "", "pippit_user_name": "",
        "tm_draft_cloud_parent_entry_id": -1,
        "tm_draft_cloud_space_id": -1,
        "tm_draft_cloud_user_id": -1,
    })
    meta_path.write_text(json.dumps(meta, ensure_ascii=False),
                         encoding="utf-8")

    # 프로젝트 목록 인덱스도 같은 값으로 맞춘다
    root_path = DRAFTS / "root_meta_info.json"
    root = json.loads(root_path.read_text(encoding="utf-8"))
    store = root.setdefault("all_draft_store", [])
    entry = next((d for d in store if d.get("draft_name") == name), None)
    if entry is None:
        entry = {}
        store.insert(0, entry)
    entry.update({
        "draft_id": meta["draft_id"],
        "draft_name": name,
        "draft_fold_path": fold,
        "draft_root_path": fold,
        "draft_json_file": f"{fold}/draft_content.json",
        "draft_cover": f"{fold}/draft_cover.jpg",
        "draft_timeline_materials_size": meta.get(
            "draft_timeline_materials_size_", 0),
        "tm_draft_create": created,
        "tm_draft_modified": now_us(),
        "tm_duration": content.get("duration", 0),
        "draft_is_invisible": False,
        "draft_removable": False,
        "streaming_edit_draft_ready": True,
    })
    root_path.write_text(json.dumps(root, ensure_ascii=False),
                         encoding="utf-8")

    print(f"OK: '{name}' 등록 완료 "
          f"({content.get('duration', 0)/1e6/60:.1f}분, "
          f"표지 {'있음' if cover_file.exists() else '없음'})")


if __name__ == "__main__":
    fix(sys.argv[1],
        sys.argv[2] if len(sys.argv) > 2 else None,
        float(sys.argv[3]) if len(sys.argv) > 3 else 3.0)
