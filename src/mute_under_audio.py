# -*- coding: utf-8 -*-
"""
재녹음(오디오 트랙)이 덮은 자리의 원본 소리를 죽인다.

사용자가 발음이 꼬인 구간을 다시 녹음해 오디오 트랙에 얹으면, 그 아래 영상
클립의 원본 소리도 같이 나서 **두 목소리가 겹쳐 들린다.** 덮인 클립만 골라
음소거한다.

캡컷이 '이 클립은 소리를 떼어냈다'로 읽는 값은 `extra_type_option` 이다
(`has_sound_separated` 만 바꾸면 안 먹는다). 둘 다 맞춰 준다.

이 조작이 안전하려면 **클립마다 material 이 따로** 있어야 한다. 공유 상태면
한 클립을 음소거할 때 그 material 을 쓰는 클립이 전부 같이 죽는다.
`split_materials.py` 가 빌드에서 처리하지만, 여기서도 확인하고 필요하면 나눈다.

사용: python src/mute_under_audio.py <드래프트이름> [덮임비율(기본 0.5)]
      python src/mute_under_audio.py <드래프트이름> --undo   (전부 되살림)
"""
import json
import os
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from draft_root import DRAFTS  # noqa: E402
US = 1_000_000


def overlap(a, b):
    return max(0.0, min(a[1], b[1]) - max(a[0], b[0]))


def patch(path: Path, ratio: float, undo: bool) -> dict:
    d = json.loads(path.read_text(encoding="utf-8"))
    mats = {m["id"]: m for m in d.get("materials", {}).get("videos", [])
            if isinstance(m, dict)}

    aud = []
    for tr in d.get("tracks", []):
        if tr.get("type") != "audio":
            continue
        for s in tr.get("segments", []):
            t = s["target_timerange"]
            aud.append((t["start"] / US, (t["start"] + t["duration"]) / US))

    n_mute = n_live = 0
    partial = []
    for tr in d.get("tracks", []):
        if tr.get("type") != "video":
            continue
        for s in tr.get("segments", []):
            m = mats.get(s.get("material_id"))
            if m is None:
                continue
            t = s["target_timerange"]
            a, b = t["start"] / US, (t["start"] + t["duration"]) / US
            cov = sum(overlap((a, b), x) for x in aud)
            frac = cov / max(b - a, 1e-9)
            hit = (not undo) and frac >= ratio
            m["extra_type_option"] = 1 if hit else 0
            m["has_sound_separated"] = bool(hit)
            if hit:
                n_mute += 1
                if frac < 0.95:
                    partial.append((a, b - a, cov, frac))
            else:
                n_live += 1
    path.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    return {"muted": n_mute, "live": n_live, "partial": partial,
            "audio": len(aud)}


def main(argv):
    name = argv[0]
    undo = "--undo" in argv
    ratio = 0.5
    for a in argv[1:]:
        if a != "--undo":
            ratio = float(a)

    folder = DRAFTS / name
    if not folder.is_dir():
        raise SystemExit(f"드래프트가 없습니다: {folder}")
    from build_capcut_draft import capcut_running
    if capcut_running():
        raise SystemExit("캡컷이 실행 중입니다. 완전히 종료한 뒤 다시 실행하세요.")

    stamp = time.strftime("%Y%m%d_%H%M%S")
    bk = folder.parent.parent / "_lecture_autocut_backup" / f"{name}_{stamp}_mute"
    bk.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(folder, bk)
    print(f"백업: {bk}")

    # 클립마다 material 이 따로 있어야 한 클립만 음소거된다
    from split_materials import split as split_mats

    files = sorted(folder.rglob("draft_content.json"))
    for f in files:
        split_mats(f, preserve_flags=True)
        r = patch(f, ratio, undo)
        rel = f.relative_to(folder)
        print(f"  {rel}")
        print(f"    재녹음 {r['audio']}구간 → 음소거 {r['muted']}클립 / "
              f"소리 유지 {r['live']}클립")
        for a, dur, cov, frac in r["partial"]:
            print(f"      부분만 덮임: {int(a//60):02d}:{a%60:05.2f} "
                  f"{dur:.1f}초 중 {cov:.1f}초({frac*100:.0f}%) — 통째로 음소거함")
    print("완료")


if __name__ == "__main__":
    main(sys.argv[1:])
