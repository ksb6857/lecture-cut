# -*- coding: utf-8 -*-
"""
자동편집본과 사용자가 손본 편집본을 소스 시간축에서 비교한다.

'사용자가 더 지운 구간' = 자동편집이 남겼는데 사용자가 없앤 원본 구간.
이게 자동편집이 놓친 것들의 정답지다. 여기서 말 버벅임 검출 규칙을 뽑고,
고친 뒤에는 같은 정답지로 검출률을 재서 효과를 확인한다.

사용:
    python src/diff_user_cuts.py <드래프트이름> <auto_keep_ranges.json> \
        <words.json> [--json 저장경로]

드래프트에서는 사용자 편집본(하위 폴더 사본)을 자동으로 찾아 읽는다.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from learn_from_edit import load_draft  # noqa: E402

MERGE_GAP = 0.20     # 이 이하로 떨어진 삭제 조각은 한 건으로 본다
MIN_SPAN = 0.15      # 이보다 짧은 건 컷 경계 미세조정이지 삭제가 아니다


def mmss(t):
    return f"{int(t//60):02d}:{t % 60:05.2f}"


def subtract(base, cut):
    """base 구간들에서 cut 구간들을 뺀 나머지."""
    cut = sorted(cut)
    out = []
    for s, e in sorted(base):
        cur = s
        for cs, ce in cut:
            if ce <= cur or cs >= e:
                continue
            if cs > cur:
                out.append((cur, min(cs, e)))
            cur = max(cur, ce)
            if cur >= e:
                break
        if cur < e:
            out.append((cur, e))
    return [(a, b) for a, b in out if b - a > 1e-6]


def merge(spans, gap=MERGE_GAP):
    out = []
    for s, e in sorted(spans):
        if out and s - out[-1][1] <= gap:
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return [(a, b) for a, b in out]


def text_in(words, s, e, pad=0.15):
    return " ".join(w["text"] for w in words
                    if w["end"] > s - pad and w["start"] < e + pad)


def run(draft, auto_ranges_path, words_path, save=None):
    user_vids, _ = load_draft(draft)
    user = [(v["s0"], v["s1"]) for v in user_vids]
    auto = [tuple(r) for r in json.loads(
        Path(auto_ranges_path).read_text(encoding="utf-8"))["keep_ranges"]]
    words = [w for w in json.loads(Path(words_path).read_text(
        encoding="utf-8"))["words"] if w["type"] == "word"]

    removed = [x for x in merge(subtract(auto, user)) if x[1] - x[0] >= MIN_SPAN]
    added = [x for x in merge(subtract(user, auto)) if x[1] - x[0] >= MIN_SPAN]

    auto_dur = sum(e - s for s, e in auto)
    user_dur = sum(e - s for s, e in user)
    rem_dur = sum(e - s for s, e in removed)

    print(f"자동편집 {auto_dur/60:.2f}분 ({len(auto)}블록) "
          f"-> 사용자편집 {user_dur/60:.2f}분 ({len(user)}블록)")
    print(f"사용자가 더 지운 구간: {len(removed)}곳, 합계 {rem_dur:.1f}초 "
          f"({100*rem_dur/max(auto_dur, 1e-9):.1f}%)")
    if added:
        print(f"  (자동편집이 지웠는데 사용자가 되살린 구간: {len(added)}곳, "
              f"{sum(e-s for s, e in added):.1f}초)")
    print()

    items = []
    for s, e in removed:
        txt = text_in(words, s, e).strip()
        items.append({"from_t": round(s, 3), "to_t": round(e, 3),
                      "dur": round(e - s, 2), "text": txt})
        print(f"  {mmss(s)}~{mmss(e)}  {e-s:5.2f}초")
        if txt:
            print(f"      「{txt[:100]}」")

    if save:
        # kept 도 같이 남긴다. 검출기 오탐은 'removed 에 안 겹치는 것' 이
        # 아니라 '사용자가 남긴 말을 먹는 것' 으로 세야 한다 — 자동편집이
        # 이미 지운 자리는 어느 쪽도 아니라서 지우자고 해도 손해가 없다.
        Path(save).write_text(json.dumps(
            {"removed": items,
             "kept": [[round(s, 3), round(e, 3)] for s, e in merge(user)],
             "added": [{"from_t": round(s, 3), "to_t": round(e, 3)}
                       for s, e in added]},
            ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\n저장: {save}")
    return items


if __name__ == "__main__":
    a = [x for x in sys.argv[1:] if not x.startswith("--")]
    save = None
    if "--json" in sys.argv:
        i = sys.argv.index("--json")
        save = sys.argv[i + 1] if i + 1 < len(sys.argv) else None
    run(a[0], a[1], a[2], save)
