# -*- coding: utf-8 -*-
"""
비디오 클립마다 material 을 따로 갖게 만든다. (오디오 유실의 진짜 원인 해결)

## 무슨 문제였나

캡컷은 클립 하나당 material 하나를 둔다(0714: 세그먼트 10개 = material 10개).
그런데 pycapcut 은 같은 파일을 쓰는 클립 472개가 **material 하나를 공유**하게
만든다.

`has_sound_separated`(오디오를 분리해 뒀음) 는 **material 단위 플래그**다.
그래서 사용자가 클립 하나에서 '오디오 분리'를 하면 그 material 이 True 가 되고,
**그 material 을 쓰는 472개 클립이 전부 음소거된다.** 저장할 때마다 원본
오디오가 통째로 사라지던 이유가 이것이다. '오디오 복구'를 누르면 되돌아오지만
다음에 오디오를 건드리면 또 같은 일이 반복된다.

볼륨(1.0)이나 has_audio(True)는 멀쩡했기 때문에 그쪽만 봐서는 원인을 못 찾는다.

## 무엇을 하나

1. 세그먼트마다 material 을 복제해 고유 id 를 준다 → 한 클립의 오디오 분리가
   다른 클립에 번지지 않는다.
2. has_sound_separated 를 다시 계산한다. 오디오 트랙에 실제로 소리를 얹어 둔
   구간의 클립만 True(음소거), 나머지는 False(원본 소리 재생).

사용: python src/split_materials.py <드래프트이름>
"""
import json
import os
import sys
import uuid
from pathlib import Path

from draft_root import DRAFTS  # noqa: E402
US = 1_000_000


def overlap(a, b):
    return max(0, min(a[1], b[1]) - max(a[0], b[0]))


def split(path: Path, respect_audio_track=True, preserve_flags=False) -> dict:
    """preserve_flags=True 면 소리 관련 플래그는 현재 값을 그대로 둔다
    (repair_sound_separated 로 이미 정리된 드래프트를 되돌리지 않기 위함)."""
    d = json.loads(path.read_text(encoding="utf-8"))
    vids = d["materials"].setdefault("videos", [])
    by_id = {m["id"]: m for m in vids if isinstance(m, dict)}

    # 오디오 트랙이 덮고 있는 구간 (여기 클립은 원본 소리를 죽여둔 상태로 본다)
    covered = []
    if respect_audio_track:
        for tr in d.get("tracks", []):
            if tr.get("type") != "audio":
                continue
            for s in tr.get("segments", []):
                t = s["target_timerange"]
                covered.append((t["start"], t["start"] + t["duration"]))

    new_mats, n_split, n_muted = [], 0, 0
    used = set()
    for tr in d.get("tracks", []):
        if tr.get("type") != "video":
            continue
        for seg in tr.get("segments", []):
            src = by_id.get(seg.get("material_id"))
            if src is None:
                continue
            m = json.loads(json.dumps(src))       # 깊은 복사
            if seg["material_id"] in used:        # 이미 쓰인 material → 새 id
                m["id"] = str(uuid.uuid4()).upper()
                seg["material_id"] = m["id"]
                n_split += 1
            used.add(m["id"])

            if preserve_flags:
                if m.get("extra_type_option") or m.get("has_sound_separated"):
                    n_muted += 1
            else:
                t = seg["target_timerange"]
                span = (t["start"], t["start"] + t["duration"])
                hit = any(overlap(span, c) > 0.2 * US for c in covered)
                m["has_audio"] = True
                # 캡컷이 '오디오 분리' 로 읽는 쪽은 extra_type_option 이다.
                m["has_sound_separated"] = bool(hit)
                m["extra_type_option"] = 1 if hit else 0
                if hit:
                    n_muted += 1
            new_mats.append(m)

    # 비디오가 아닌 material(이미지 등)은 그대로 둔다
    keep = [m for m in vids if isinstance(m, dict) and m.get("type") != "video"]
    d["materials"]["videos"] = keep + new_mats

    path.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    return {"segments": len(new_mats), "split": n_split, "muted": n_muted}


def main(name):
    folder = DRAFTS / name
    if not folder.is_dir():
        raise SystemExit(f"드래프트가 없습니다: {folder}")
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        from build_capcut_draft import capcut_running
        if capcut_running():
            raise SystemExit("캡컷이 실행 중입니다. 완전히 종료한 뒤 다시 실행하세요.")
    except ImportError:
        pass
    r = split(folder / "draft_content.json")
    print(f"OK: '{name}'")
    print(f"  클립 {r['segments']}개에 각자 material 부여 (새로 만든 것 {r['split']}개)")
    print(f"  원본 소리 재생 {r['segments']-r['muted']}개 / "
          f"오디오 트랙이 덮은 구간 음소거 {r['muted']}개")


if __name__ == "__main__":
    main(sys.argv[1])
