# -*- coding: utf-8 -*-
"""
사용자가 손본 편집본에서 규칙을 뽑는다 (2차 학습).

- 컷 지점마다 남긴 무음을 문장 끝 / 문장 중간으로 나눠 통계
- 자동편집이 남겼는데 사용자가 지운 발화 = 놓친 재발화
- 자막 줄바꿈 위치를 실제 말뭉치와 대조

사용: python src/analyze_user_edit.py <드래프트> <speech.json> <words.json> [끝시각(초)]
"""
import bisect
import json
import statistics as st
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from learn_from_edit import load_draft  # noqa: E402


def overlap(a, b):
    return max(0.0, min(a[1], b[1]) - max(a[0], b[0]))


def mmss(t):
    return f"{int(t//60):02d}:{t % 60:05.2f}"


def run(draft, speech_path, words_path, until=None):
    vids, texts = load_draft(draft)
    speech = json.loads(Path(speech_path).read_text(encoding="utf-8"))["speech"]
    words = [w for w in json.loads(Path(words_path).read_text(
        encoding="utf-8"))["words"] if w["type"] == "word"]
    until = float(until) if until else 10 ** 9

    sp_s = [s for s, _ in speech]
    sp_e = [e for _, e in speech]
    w_ends = sorted(w["end"] for w in words)
    by_end = {w["end"]: w for w in words}

    def prev_end(t):
        i = bisect.bisect_left(sp_e, t) - 1
        return sp_e[i] if i >= 0 else None

    def next_start(t):
        i = bisect.bisect_right(sp_s, t)
        return sp_s[i] if i < len(sp_s) else None

    def sentence_end(t):
        i = bisect.bisect_right(w_ends, t + 0.05) - 1
        if i < 0:
            return False
        return by_end[w_ends[i]]["text"].rstrip()[-1:] in ".?!"

    # 1) 컷 지점 쉼
    mid, end = [], []
    for a, b in zip(vids, vids[1:]):
        if a["t1"] > until:
            break
        if b["s0"] - a["s1"] <= 0.02:
            continue
        pe, ns = prev_end(a["s1"]), next_start(b["s0"])
        if pe is None or ns is None:
            continue
        tail, lead = a["s1"] - pe, ns - b["s0"]
        if tail < -0.05 or lead < -0.05:
            continue
        (end if sentence_end(a["s1"]) else mid).append(
            (tail + lead, tail, lead, a["s1"]))

    print(f"[컷 지점에 남긴 쉼]  (편집본 0~{until:.0f}초)")
    for name, X in (("문장 중간", mid), ("문장 끝", end)):
        if not X:
            continue
        r = [x[0] for x in X]
        print(f"  {name}: n={len(r):3d}  중앙 {st.median(r):.2f}초  "
              f"평균 {st.mean(r):.2f}  범위 {min(r):.2f}~{max(r):.2f}  "
              f"| tail 중앙 {st.median([x[1] for x in X]):.2f} "
              f"lead 중앙 {st.median([x[2] for x in X]):.2f}")
    print()

    # 2) 사용자가 지운 발화
    src_max = max((v["s1"] for v in vids if v["t1"] <= until), default=0)
    keep = [(v["s0"], v["s1"]) for v in vids if v["s0"] <= src_max + 1]
    print(f"[사용자가 지운 발화]  (소스 0~{src_max:.0f}초)")
    total_removed = 0.0
    for s in speech:
        if s[1] > src_max:
            break
        cov = sum(overlap(s, k) for k in keep)
        span = s[1] - s[0]
        if span - cov < 0.4:
            continue
        total_removed += span - cov
        txt = " ".join(w["text"] for w in words
                       if w["start"] >= s[0] - 0.3 and w["end"] <= s[1] + 0.3)
        print(f"  {mmss(s[0])}~{mmss(s[1])} ({span:.1f}초 중 {span-cov:.1f}초 삭제)")
        if txt.strip():
            print(f"      「{txt.strip()[:80]}」")
    print(f"  합계 {total_removed:.1f}초 삭제")
    print()

    # 3) 자막 줄
    subs = [t for t in texts if t["t1"] <= until and t["text"].strip()]
    if subs:
        L = [len(t["text"]) for t in subs]
        D = [t["t1"] - t["t0"] for t in subs]
        print(f"[자막] {len(subs)}줄  글자 중앙 {st.median(L):.0f} 최대 {max(L)} "
              f"| 길이 중앙 {st.median(D):.2f}초 최대 {max(D):.2f}초")
        print("  앞 20줄:")
        for t in subs[:20]:
            print(f"    {t['t0']:7.2f}~{t['t1']:7.2f}  {t['text'][:44]}")


if __name__ == "__main__":
    run(*sys.argv[1:5])
