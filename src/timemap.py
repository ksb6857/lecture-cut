# -*- coding: utf-8 -*-
"""편집본 시각 <-> 원본 시각 변환.

**효과를 편집본 시각에 박으면 안 된다.** 사용자가 앞에 오프닝을 끼우거나 컷을
하나만 더 손봐도 타임라인이 밀려 강조·스티커·확대가 전부 어긋난다.
그래서 계획 파일은 **원본 mp4 시각**으로 적고, 붙일 때 지금 드래프트의
컷 구성을 보고 편집본 시각을 다시 계산한다. 컷이 바뀌면 다시 붙이기만 하면 된다.

마스크는 원래부터 안전하다 — 비디오 세그먼트에 직접 붙으므로 클립과 같이 움직인다.
위험한 건 별도 트랙에 얹히는 것들(강조 도형·스티커·배경음악)이다.

**오프닝처럼 다른 소재가 앞에 붙어도 괜찮다.** 강의 원본이 아닌 세그먼트는
빼고 대응표를 만들기 때문이다.
"""
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from draft_doctor import contents, resolve  # noqa: E402

US = 1_000_000


def _load(draft):
    if isinstance(draft, dict):
        return draft
    return json.loads(contents(resolve(str(draft)))[0].read_text(encoding="utf-8"))


def timeline(draft, material=None):
    """[(편집시작, 편집끝, 원본시작)] — 강의 원본 소재 세그먼트만.

    `material` 을 안 주면 가장 많이 쓰인 소재를 강의 원본으로 본다(오프닝처럼
    몇 개 안 되는 다른 소재는 자동으로 빠진다).
    """
    d = _load(draft)
    vids = {m["id"]: m for m in d["materials"].get("videos") or []}
    vt = [t for t in d["tracks"] if t["type"] == "video"][0]
    segs = sorted(vt["segments"], key=lambda s: s["target_timerange"]["start"])

    def name(s):
        m = vids.get(s["material_id"]) or {}
        return m.get("material_name") or m.get("path") or ""

    if material is None:
        c = Counter(name(s) for s in segs)
        material = c.most_common(1)[0][0] if c else ""
    out = []
    for s in segs:
        if name(s) != material:
            continue
        t, src = s["target_timerange"], s.get("source_timerange") or {}
        out.append((t["start"] / US, (t["start"] + t["duration"]) / US,
                    src.get("start", 0) / US))
    return out


def to_source(tl, t):
    """편집본 시각 -> 원본 시각. 그 시각에 강의 원본이 없으면 None."""
    for t0, t1, s0 in tl:
        if t0 <= t < t1:
            return s0 + (t - t0)
    return None


def to_edit(tl, src):
    """원본 시각 -> 편집본 시각. 그 부분이 잘려나갔으면 None."""
    for t0, t1, s0 in tl:
        if s0 <= src < s0 + (t1 - t0):
            return t0 + (src - s0)
    return None


def span_to_edit(tl, a, b):
    """원본 구간 [a,b) -> 편집본 (시작, 길이).

    구간 안쪽이 잘려 나갔으면 남은 부분만큼 짧아진다. 남은 게 없으면 None.
    강조가 조각조각 나뉘면 깜빡이므로 **처음 나타나는 곳부터 마지막까지**를
    한 덩어리로 잡는다.
    """
    hits = []
    for t0, t1, s0 in tl:
        s1 = s0 + (t1 - t0)
        lo, hi = max(a, s0), min(b, s1)
        if hi > lo:
            hits.append((t0 + (lo - s0), t0 + (hi - s0)))
    if not hits:
        return None
    return hits[0][0], hits[-1][1] - hits[0][0]


def resolve_item(tl, it, default_dur=6.0):
    """계획 항목 하나를 (편집시작, 길이) 로 푼다.

    `src: [a, b]` 가 있으면 원본 기준으로 계산하고(권장),
    `t`/`dur` 만 있으면 그대로 쓴다(오프닝처럼 원본에 없는 구조적 위치용).
    """
    if "src" in it and isinstance(it["src"], (list, tuple)):
        if "dur" in it:
            # 길이를 못 박아야 하는 것(배경음악 등)은 시작만 원본에 앵커한다.
            # 구간으로 잡으면 나중에 컷을 되살릴 때 음악이 같이 길어진다.
            t = to_edit(tl, it["src"][0])
            return None if t is None else (t, it["dur"])
        return span_to_edit(tl, it["src"][0], it["src"][1])
    if "t" in it:
        return it["t"], it.get("dur", default_dur)
    return None


def migrate(plan_path, draft, key="items"):
    """계획 파일의 `t`/`dur` 를 `src` 로 바꿔 적는다(한 번만 하면 된다)."""
    p = Path(plan_path)
    plan = json.loads(p.read_text(encoding="utf-8"))
    tl = timeline(draft)
    n = 0
    for it in plan.get(key) or []:
        if "src" in it or "t" not in it:
            continue
        a = to_source(tl, it["t"])
        b = to_source(tl, it["t"] + it.get("dur", 6.0) - 0.001)
        if a is None:
            print(f"  [건너뜀] {it['t']}초는 강의 원본 구간이 아니다")
            continue
        if b is None or b <= a:
            b = a + it.get("dur", 6.0)
        it["src"] = [round(a, 2), round(b, 2)]
        it.pop("t", None)
        it.pop("dur", None)
        n += 1
    p.write_text(json.dumps(plan, ensure_ascii=False, indent=1),
                 encoding="utf-8")
    print(f"{p.name}: {n}개 항목을 원본 시각으로 바꿨다")


if __name__ == "__main__":
    migrate(sys.argv[1], sys.argv[2], *(sys.argv[3:4] or []))
