# -*- coding: utf-8 -*-
"""
생성한 드래프트를 캡컷이 저장해도 오디오가 안 날아가게 고친다.

증상: 캡컷에서 저장할 때마다 원본 영상의 소리가 사라지고,
      '오디오 복구'를 눌러야 되돌아온다.

원인: pycapcut 이 만든 draft_content.json 에는
  - 비디오 material 의 has_audio 플래그가 없고
  - 각 세그먼트에 sound_channel_mapping(오디오 채널 매핑) 참조가 없다.
캡컷은 이 정보가 없으면 그 클립에 소리가 없는 것으로 보고 저장할 때 떨어뜨린다.
'오디오 복구'는 파일을 다시 분석해 이 정보를 채워 넣는 동작이다.

이 스크립트는 캡컷이 실제로 쓰는 형태 그대로 채워 넣는다.
비디오 세그먼트마다 sound_channel_mapping / vocal_separation /
placeholder_info / canvas / material_color 를 만들어 참조를 걸어준다.

사용: python src/fix_draft_audio.py <드래프트이름>
"""
import json
import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from draft_root import DRAFTS  # noqa: E402


def uid():
    return str(uuid.uuid4()).upper()


def make(kind):
    i = uid()
    if kind == "sound_channel_mappings":
        return {"id": i, "type": "none", "audio_channel_mapping": 0,
                "is_config_open": False}
    if kind == "vocal_separations":
        return {"id": i, "type": "vocal_separation", "choice": 0,
                "removed_sounds": [], "time_range": None,
                "production_path": "", "final_algorithm": "",
                "enter_from": ""}
    if kind == "placeholder_infos":
        return {"id": i, "type": "placeholder_info", "meta_type": "none",
                "res_path": "", "res_text": "", "error_path": "",
                "error_text": ""}
    if kind == "canvases":
        return {"id": i, "type": "canvas_color", "color": "", "blur": 0.0,
                "image": "", "album_image": "", "image_id": "",
                "image_name": "", "source_platform": 0, "team_id": ""}
    if kind == "material_colors":
        return {"id": i, "is_color_clip": False, "is_gradient": False,
                "solid_color": "", "gradient_colors": [],
                "gradient_percents": [], "gradient_angle": 90.0,
                "width": 0.0, "height": 0.0}
    raise ValueError(kind)


# 세그먼트마다 붙어야 하는 부속 material 들
PER_SEGMENT = ["sound_channel_mappings", "vocal_separations",
               "placeholder_infos", "canvases", "material_colors"]


def fix(path: Path) -> dict:
    d = json.loads(path.read_text(encoding="utf-8"))
    mats = d.setdefault("materials", {})

    # 1) 비디오 material 에 오디오 플래그를 세운다
    n_mat = 0
    for v in mats.get("videos", []):
        if v.get("type") != "video":
            continue
        if not v.get("has_audio"):
            v["has_audio"] = True
            n_mat += 1
        # 아래 둘은 '이 클립의 소리를 별도 오디오 트랙으로 떼어냈다'는 표시다.
        # 켜 두면 캡컷이 클립을 음소거하고 '오디오가 분리됨 / 오디오 복구'
        # 상태로 보여준다 — 떼어낸 오디오 트랙이 없으니 강의 전체가 무음이
        # 된다. 캡컷이 실제로 읽는 쪽은 extra_type_option 이다.
        # (캡컷이 직접 만든 정상 드래프트도 0 / False 로 들어 있다)
        v["extra_type_option"] = 0
        v["has_sound_separated"] = False
        v.setdefault("intensifies_audio_path", "")
        v.setdefault("source", 0)

    # 2) 세그먼트마다 부속 material 을 만들어 참조를 건다
    existing = {k: {m["id"] for m in mats.get(k, [])} for k in PER_SEGMENT}
    n_seg = 0
    for tr in d.get("tracks", []):
        if tr.get("type") != "video":
            continue
        for seg in tr.get("segments", []):
            refs = seg.setdefault("extra_material_refs", [])
            have = set(refs)
            for kind in PER_SEGMENT:
                if have & existing[kind]:      # 이미 붙어 있으면 건너뛴다
                    continue
                m = make(kind)
                mats.setdefault(kind, []).append(m)
                existing[kind].add(m["id"])
                refs.append(m["id"])
            seg.setdefault("volume", 1.0)
            seg.setdefault("last_nonzero_volume", 1.0)
            n_seg += 1

    path.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    return {"materials_flagged": n_mat, "segments_fixed": n_seg}


def main(name):
    folder = DRAFTS / name
    if not folder.is_dir():
        raise SystemExit(f"드래프트가 없습니다: {folder}")
    p = folder / "draft_content.json"
    r = fix(p)
    print(f"OK: '{name}' 오디오 정보 보강 "
          f"(material {r['materials_flagged']}개, "
          f"세그먼트 {r['segments_fixed']}개)")


if __name__ == "__main__":
    main(sys.argv[1])
