# -*- coding: utf-8 -*-
"""
사용자가 손수 얹은 트랙(추출 오디오, 추가 자막)을 새 편집본으로 옮긴다.

자동편집을 다시 돌리면 컷이 달라져 타임라인이 통째로 밀린다.
그대로 붙여넣으면 엉뚱한 자리에 놓이므로, 반드시
  옛 편집본 위치 -> 원본(소스) 시각 -> 새 편집본 위치
로 환산해서 옮겨야 한다.

- 오디오 세그먼트: source_timerange 에 원본 시각이 들어 있어 바로 환산
- 텍스트 세그먼트: 소스 정보가 없으므로 옛 편집본의 비디오 세그먼트를 거쳐
  target -> source 를 역산한 뒤 환산

사용: python src/port_tracks.py <옛드래프트> <새드래프트> <새keep_ranges.json>
"""
import bisect
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from draft_root import DRAFTS  # noqa: E402
US = 1_000_000


class Mapper:
    """원본 시각 -> 새 편집본 시각"""

    def __init__(self, keep_ranges):
        self.r = keep_ranges
        self.off, t = [], 0.0
        for s, e in keep_ranges:
            self.off.append(t)
            t += e - s
        self.total = t

    def map(self, src):
        prev = 0.0
        for (s, e), o in zip(self.r, self.off):
            if src < s:
                return prev, False          # 잘려나간 구간 → 직전 끝에 붙임
            if src <= e:
                return o + (src - s), True
            prev = o + (e - s)
        return self.total, False

    def map_span(self, src, dur):
        """구간 전체로 판단한다. 클립 시작이 무음에 걸쳐 있어도
        본체가 살아남은 구간에 있으면 그쪽에 정확히 놓는다."""
        lo, hi = src, src + dur
        best, best_ov = None, 0.0
        for (s, e), o in zip(self.r, self.off):
            ov = min(hi, e) - max(lo, s)
            if ov > best_ov:
                best_ov, best = ov, o + (max(lo, s) - s)
        if best is not None:
            return best, True
        return self.map(src)


def old_target_to_source(old_vids, t):
    """옛 편집본 시각 -> 원본 시각"""
    starts = [v["t0"] for v in old_vids]
    i = bisect.bisect_right(starts, t) - 1
    if i < 0:
        return None
    v = old_vids[i]
    if t > v["t1"] + 0.05:
        return None
    return v["s0"] + (t - v["t0"])


def run(old_name, new_name, ranges_path):
    old = json.loads((DRAFTS / old_name / "draft_content.json").read_text(
        encoding="utf-8"))
    new_path = DRAFTS / new_name / "draft_content.json"
    new = json.loads(new_path.read_text(encoding="utf-8"))
    keep = json.loads(Path(ranges_path).read_text(encoding="utf-8"))["keep_ranges"]
    mp = Mapper(keep)

    old_vids = []
    for tr in old["tracks"]:
        if tr["type"] != "video":
            continue
        for s in tr["segments"]:
            t = s["target_timerange"]
            src = s.get("source_timerange") or {"start": 0, "duration": 0}
            old_vids.append({
                "t0": t["start"] / US,
                "t1": (t["start"] + t["duration"]) / US,
                "s0": src["start"] / US,
            })
    old_vids.sort(key=lambda v: v["t0"])

    # 옮길 트랙 고르기: 오디오 전부 + 자막이 아닌 소규모 텍스트 트랙
    moved, warns = [], []
    for tr in old["tracks"]:
        if tr["type"] == "audio":
            pick = tr
        elif tr["type"] == "text" and len(tr["segments"]) <= 40:
            pick = tr
        else:
            continue

        newsegs = []
        for s in pick["segments"]:
            t = s["target_timerange"]
            if pick["type"] == "audio" and s.get("source_timerange"):
                src = s["source_timerange"]["start"] / US
            else:
                src = old_target_to_source(old_vids, t["start"] / US)
            if src is None:
                warns.append((pick["type"], t["start"] / US, "원본 위치 불명"))
                continue
            nt, exact = mp.map_span(src, t["duration"] / US)
            if not exact:
                warns.append((pick["type"], t["start"] / US,
                              f"원본 {src:.1f}초가 새 편집에서 잘림 → "
                              f"{nt:.1f}초에 배치"))
            s2 = json.loads(json.dumps(s))       # 깊은 복사
            s2["target_timerange"] = {"start": int(round(nt * US)),
                                      "duration": t["duration"]}
            newsegs.append(s2)
        newsegs.sort(key=lambda x: x["target_timerange"]["start"])

        # 겹침 방지 (캡컷이 거부한다)
        for a, b in zip(newsegs, newsegs[1:]):
            ae = a["target_timerange"]["start"] + a["target_timerange"]["duration"]
            if b["target_timerange"]["start"] < ae:
                b["target_timerange"]["start"] = ae + 1000

        tr2 = json.loads(json.dumps(pick))
        tr2["segments"] = newsegs
        new["tracks"].append(tr2)
        moved.append((pick["type"], len(newsegs)))

    # 참조하는 material 을 통째로 가져온다 (없으면 캡컷이 못 연다)
    used = set()
    for tr in new["tracks"][-len(moved):]:
        for s in tr["segments"]:
            used.add(s.get("material_id"))
            used.update(s.get("extra_material_refs", []))
    n_mat = 0
    for key, arr in old.get("materials", {}).items():
        if not isinstance(arr, list):
            continue
        have = {m.get("id") for m in new["materials"].get(key, [])
                if isinstance(m, dict)}
        for m in arr:
            if isinstance(m, dict) and m.get("id") in used and m["id"] not in have:
                new["materials"].setdefault(key, []).append(m)
                n_mat += 1

    new_path.write_text(json.dumps(new, ensure_ascii=False), encoding="utf-8")
    for kind, n in moved:
        print(f"OK: {kind} 트랙 {n}개 이식")
    print(f"    참조 material {n_mat}개 복사")
    if warns:
        print(f"    주의 {len(warns)}건:")
        for kind, t, msg in warns[:10]:
            print(f"      [{kind}] 옛 {int(t//60):02d}:{t%60:05.2f} — {msg}")
    return moved


if __name__ == "__main__":
    run(*sys.argv[1:4])
