# -*- coding: utf-8 -*-
"""
이미 만들어 둔 드래프트의 '오디오가 분리됨' 상태를 되돌린다.

증상: 캡컷에서 열면 영상 클립에 파형이 없고, 클립을 고르면 오디오 탭에
      "오디오가 분리됨 / 오디오 복구" 만 뜬다. 강의 전체가 무음.

원인: fix_draft_audio.py 가 비디오 material 에 has_sound_separated=True 를
      넣었다(2026-08-13 ~ 08-14 에 만든 드래프트). 이 플래그는
      '이 클립의 소리를 별도 오디오 트랙으로 떼어냈다'는 뜻이라서,
      떼어낸 트랙이 없으면 캡컷이 그냥 음소거로 취급한다.
      스크립트는 고쳤지만(False), 이미 만든 드래프트는 이걸로 되돌린다.

캡컷은 드래프트를 열 때 내부 형식으로 변환하면서 draft_content.json 을
여러 벌 만든다(하위 폴더·Timelines). 전부 고쳐야 한다.

사용:
    python src/repair_sound_separated.py <드래프트이름> [<드래프트이름> ...]
    python src/repair_sound_separated.py <드래프트이름> --drop-ported-audio

--drop-ported-audio 는 port_tracks.py 가 옮겨온 'video_original_sound'
오디오 트랙을 함께 지운다. 영상 소리를 되살리면 그 클립들이 같은 소리를
한 번 더 내므로(2차시는 29개 중 13개가 0.8~7.9초 어긋나 메아리가 된다)
되살린 뒤에는 지우는 게 맞다.
"""
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from draft_root import DRAFTS  # noqa: E402


def capcut_running() -> bool:
    try:
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq CapCut.exe"],
                             capture_output=True, text=True, timeout=15)
        return "CapCut.exe" in out.stdout
    except Exception:
        return False


def backup(folder: Path) -> Path:
    stamp = time.strftime("%Y%m%d_%H%M%S")
    dest = folder.parent.parent / "_lecture_autocut_backup" / \
        f"{folder.name}_{stamp}_sepfix"
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(folder, dest)
    return dest


def patch_file(path: Path, drop_ported: bool) -> dict:
    d = json.loads(path.read_text(encoding="utf-8"))
    # 사용자가 일부러 오디오를 분리해 둔 클립은 건드리지 않는다. 2차시에서는
    # 재녹음할 곳 표시로 쓰고 있어서, 되돌리면 그 표시가 사라진다.
    # 주의: 캡컷은 material 을 여러 클립이 공유한다. 2차시에서는 461컷 중
    # 448컷이 같은 material 2개를 쓴다. 그래서 '이 material 을 쓰는 클립이
    # **전부** 분리 오디오로 덮여 있을 때만' 의도적 분리로 본다. 하나라도
    # 안 덮여 있으면 그 클립은 그냥 무음이므로 되돌려야 한다.
    aud = []
    for tr in d.get("tracks", []):
        if tr.get("type") == "audio":
            for s in tr.get("segments", []):
                a = s["target_timerange"]["start"] / 1e6
                aud.append((a, a + s["target_timerange"]["duration"] / 1e6))
    cov_ok, cov_all = {}, {}
    for tr in d.get("tracks", []):
        if tr.get("type") != "video":
            continue
        for s in tr.get("segments", []):
            mid = s.get("material_id")
            a = s["target_timerange"]["start"] / 1e6
            b = a + s["target_timerange"]["duration"] / 1e6
            cov = sum(max(0.0, min(b, y) - max(a, x)) for x, y in aud)
            cov_all[mid] = cov_all.get(mid, 0) + 1
            if cov / max(b - a, 1e-9) >= 0.9:
                cov_ok[mid] = cov_ok.get(mid, 0) + 1
    keep = {m for m, n in cov_all.items() if cov_ok.get(m, 0) == n}

    n_flag = 0
    for v in d.get("materials", {}).get("videos", []):
        if v.get("type") != "video" or v.get("id") in keep:
            continue
        if v.get("extra_type_option") or v.get("has_sound_separated"):
            # 캡컷이 '오디오 분리' 로 읽는 쪽은 extra_type_option 이다.
            v["extra_type_option"] = 0
            v["has_sound_separated"] = False
            n_flag += 1

    n_track, n_seg = 0, 0
    if drop_ported:
        ported = {a["id"] for a in d.get("materials", {}).get("audios", [])
                  if a.get("type") == "video_original_sound"}
        keep = []
        for tr in d.get("tracks", []):
            segs = tr.get("segments", [])
            if tr.get("type") == "audio" and segs and all(
                    s.get("material_id") in ported for s in segs):
                n_track += 1
                n_seg += len(segs)
                continue
            keep.append(tr)
        d["tracks"] = keep

    path.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    return {"flags": n_flag, "tracks": n_track, "segs": n_seg}


def repair(name: str, drop_ported: bool) -> None:
    folder = DRAFTS / name
    if not folder.is_dir():
        raise SystemExit(f"드래프트가 없습니다: {folder}")

    dest = backup(folder)
    print(f"[{name}] 백업: {dest}")

    files = sorted(folder.rglob("draft_content.json"))
    total = {"flags": 0, "tracks": 0, "segs": 0}
    for f in files:
        r = patch_file(f, drop_ported)
        for k in total:
            total[k] += r[k]
        rel = f.relative_to(folder)
        print(f"    {rel} — 클립 {r['flags']}개 소리 되살림"
              + (f", 오디오 트랙 {r['tracks']}개({r['segs']}클립) 제거"
                 if r["tracks"] else ""))

    print(f"[{name}] 완료: 파일 {len(files)}벌, "
          f"영상 클립 {total['flags']}개 소리 되살림"
          + (f", 옮겨온 오디오 클립 {total['segs']}개 제거"
             if total["segs"] else ""))


def main(argv):
    drop_ported = "--drop-ported-audio" in argv
    names = [a for a in argv if not a.startswith("--")]
    if not names:
        raise SystemExit(__doc__)
    if capcut_running():
        raise SystemExit(
            "캡컷이 실행 중입니다. 완전히 종료한 뒤 다시 실행하세요.\n"
            "  (열려 있는 상태에서 드래프트를 고치면 캡컷이 메모리에 있던\n"
            "   내용으로 되돌려 저장해 고친 게 날아갑니다)")
    for n in names:
        repair(n, drop_ported)


if __name__ == "__main__":
    main(sys.argv[1:])
