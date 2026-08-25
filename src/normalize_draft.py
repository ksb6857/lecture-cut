# -*- coding: utf-8 -*-
"""캡컷이 읽을 수 있는 모양으로 트랙을 정리한다.

**캡컷은 비디오 트랙을 `target_timerange` 가 아니라 배열 순서대로 늘어놓는다.**
2026-08-23 에 이걸 몰라서 2차시가 통째로 어긋났다. `insert_blocks` 가 오프닝·
무음화면·클로징을 배열 **끝에** 덧붙였는데(시각은 맨 앞 0초), 캡컷이 열면서
배열 순서대로 다시 깔아 강의 영상이 0초로 당겨지고 오프닝은 뒤로 밀렸다.
자막·배경음악·강조는 절대시각 그대로라 화면과 소리가 28초씩 어긋났다.
사용자 화면에는 강의 슬라이드 위에 오프닝 제목과 음악만 얹혀 있었다.

그래서 **쓰기 직전에 모든 트랙을 시각순으로 정렬한다.**

**같은 트랙에서 겹치는 세그먼트는 새 트랙으로 뺀다.** 캡컷은 겹침을 발견하면
자기가 트랙을 쪼개는데, 그때 이름이 빈 트랙이 생겨 다음 작업에서 어느 트랙이
자막인지 분간이 안 된다(`fix_captions` 가 두 줄 겹쳐 찍힌 걸 잡느라 헤맸다).
오프닝 제목 두 줄이 같은 시각에 있는 게 그 경우다.

비디오 트랙의 겹침은 자동으로 손대지 않는다 — 그건 편집 자체가 틀린 것이라
조용히 옮기면 더 나빠진다. 짚어만 준다.

사용: python src/normalize_draft.py <드래프트> [--dry]
"""
import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from draft_doctor import contents, resolve  # noqa: E402
from port_effects import capcut_running  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

US = 1_000_000
TOL = 1000          # 1ms 미만 겹침은 반올림 오차로 본다


def _start(s):
    return s["target_timerange"]["start"]


def _end(s):
    return s["target_timerange"]["start"] + s["target_timerange"]["duration"]


def sort_all(d):
    """모든 트랙을 시각순으로. 몇 개 트랙이 어긋나 있었는지 돌려준다."""
    n = 0
    for tr in d["tracks"]:
        segs = tr.get("segments") or []
        if any(_start(segs[i]) > _start(segs[i + 1]) for i in range(len(segs) - 1)):
            n += 1
        segs.sort(key=_start)
    return n


def split_overlaps(d):
    """한 트랙 안에서 시간이 겹치는 세그먼트를 새 트랙으로 옮긴다."""
    moved = 0
    for tr in list(d["tracks"]):
        if tr["type"] == "video":
            continue
        segs = sorted(tr.get("segments") or [], key=_start)
        keep, spill = [], []
        last = None
        for s in segs:
            if last is not None and _start(s) < last - TOL:
                spill.append(s)
            else:
                keep.append(s)
                last = _end(s)
        if not spill:
            continue
        tr["segments"] = keep
        used = {t.get("track_render_index") or 0 for t in d["tracks"]}
        d["tracks"].append({
            "attribute": 0, "flag": 0, "id": str(uuid.uuid4()).upper(),
            "is_default_name": False,
            "name": (tr.get("name") or tr["type"]) + "_2",
            "segments": spill, "type": tr["type"],
            "track_render_index": max(used, default=0) + 1})
        moved += len(spill)
    return moved


def video_overlaps(d):
    """비디오 트랙의 겹침을 짚기만 한다 (고치지 않는다)."""
    out = []
    for tr in d["tracks"]:
        if tr["type"] != "video":
            continue
        segs = sorted(tr.get("segments") or [], key=_start)
        for x, y in zip(segs, segs[1:]):
            if _end(x) > _start(y) + TOL:
                out.append((tr.get("name"), _start(x) / US, _end(x) / US,
                            _start(y) / US))
    return out


def apply(d):
    """드래프트 하나를 정리한다. (어긋난 트랙 수, 옮긴 세그먼트 수, 비디오 겹침)"""
    bad = sort_all(d)
    moved = split_overlaps(d)
    sort_all(d)
    return bad, moved, video_overlaps(d)


def run(draft, dry=False):
    if not dry and capcut_running():
        raise SystemExit("캡컷이 실행 중입니다. 완전히 종료한 뒤 다시 실행하세요.")
    root = resolve(draft)
    print(f"정리: {draft}  ({root.name})")
    for f in contents(root):
        d = json.loads(f.read_text(encoding="utf-8"))
        bad, moved, ov = apply(d)
        if not dry:
            f.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        print(f"  {f.relative_to(root)}: 순서 바로잡은 트랙 {bad}개 · "
              f"새 트랙으로 뺀 세그먼트 {moved}개")
        for nm, a, b, c in ov:
            print(f"    [비디오 겹침] {nm} {a:.2f}~{b:.2f} 인데 다음이 {c:.2f} 시작")


def main(argv):
    run(argv[0], dry="--dry" in argv)


if __name__ == "__main__":
    main(sys.argv[1:])
