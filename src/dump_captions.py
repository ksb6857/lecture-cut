# -*- coding: utf-8 -*-
"""드래프트의 자막을 편집본 시각과 함께 뽑는다.

강조 도형을 어디에 넣을지는 '그때 무슨 말을 하는가' 를 봐야 정해진다.
컨택트시트(`sample_frames.py`)의 시각과 맞춰 읽으려고 만든 것이라,
`--step` 을 주면 그 간격으로 묶어 준다.

사용: python src/dump_captions.py <드래프트> [--step 20] [--from 0] [--to 1e9]
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from learn_from_edit import draft_content_path  # noqa: E402

US = 1_000_000


def lines(draft):
    d = json.loads(draft_content_path(draft).read_text(encoding="utf-8"))
    txt = {m["id"]: m for m in d["materials"].get("texts") or []}
    out = []
    for tr in d["tracks"]:
        if tr["type"] != "text":
            continue
        for s in tr.get("segments") or []:
            m = txt.get(s.get("material_id"))
            if not m:
                continue
            try:
                t = json.loads(m["content"])["text"]
            except Exception:
                continue
            a = s["target_timerange"]["start"] / US
            out.append((a, a + s["target_timerange"]["duration"] / US,
                        t.replace("\n", " / ")))
    out.sort()
    return out


def run(draft, step=20.0, lo=0.0, hi=1e9):
    step, lo, hi = float(step), float(lo), float(hi)
    cur = None
    for a, b, t in lines(draft):
        if not (lo <= a < hi):
            continue
        bucket = int(a // step) * step
        if bucket != cur:
            cur = bucket
            print(f"\n[{int(bucket//60):02d}m{int(bucket % 60):02d}s]")
        print(f"  {a - bucket:5.1f}+ {t}")


def main(argv):
    draft = argv[0]

    def opt(name, dv):
        return argv[argv.index(name) + 1] if name in argv else dv
    run(draft, opt("--step", 20), opt("--from", 0), opt("--to", 1e9))


if __name__ == "__main__":
    main(sys.argv[1:])
