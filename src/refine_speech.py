# -*- coding: utf-8 -*-
"""삭제 지시가 발화 덩어리 한가운데에 걸리면, 덩어리를 **진짜 무음**에서 나눈다.

`cut_planner` 는 발화 덩어리(VAD) 한가운데를 자르지 않는다. 그래서 한 덩어리
안에서 되풀이한 말(같은 낱말을 두 번 붙여 말한 것)이나 끝에 붙은 실패 테이크는 그대로
남는다. 이걸 낱말 시각으로 잘라 내면 말이 씹힌다. 위스퍼 시각은 ±0.3초 어긋난다.

2026-09-23 에 그렇게 해서 컷 지점 904곳 중 84곳이 말 위에 떨어졌다.
문장 끝 서술어 세 곳이 잘렸고 강사가 손으로 되살렸다.

그래서 역할을 나눈다.

- **어느 낱말이 삭제 쪽인가**는 낱말 중간점으로 정한다
- **어디서 끊는가**는 파형으로 정한다. 두 낱말 사이에서 -50dB 아래로
  40ms 이상 조용한 구간을 찾아 그 무음을 덩어리 사이의 틈으로 만든다
- 그런 무음이 없으면 **끊지 않는다.** 말이 이어져 있다는 뜻이다. 보고서에 남긴다

나눈 결과를 `cut_planner` 에 speech.json 대신 넘기면, 계획기는 평소대로
"절반 넘게 삭제에 걸린 덩어리는 빼고, 남은 틈은 쉼 규칙대로 깎는다".
덩어리 경계가 모두 무음이므로 컷 지점도 전부 무음이다.

사용:
    python refine_speech.py <speech.json> <words.json> <wav> <out_speech.json> <삭제지시.json>...
        [--levels <캐시.npy>] [--report <미해결.json>] [--snapped <옮긴지시.json>]
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import audio_levels as L  # noqa: E402

EDGE = 0.05       # 덩어리 끝에서 이보다 가까운 경계는 나눌 필요가 없다
REACH = 0.6       # 낱말 중간점 너머로 무음을 찾아볼 여유.
# 위스퍼 낱말 시각은 1초 가까이 밀리기도 한다(11차시 5020초: 실제 무음은 덩어리
# 바깥 5019.5초에 있었는데 낱말은 5020.7초로 찍혔다). 그래서 덩어리 밖까지 찾는다.
# 찾은 무음이 덩어리 경계와 겹치면 나눌 필요가 없다 — 삭제 지시만 그리로 옮긴다.
DIP_DB = -45.0    # 2단계: 완전한 무음이 없을 때 받아 주는 깊은 골
DIP_LEN = 0.02


def load_deletions(paths):
    out = []
    for p in paths:
        r = json.loads(Path(p).read_text(encoding="utf-8"))
        for d in r.get("deletions", []):
            if d.get("caption_only"):
                continue                     # 자막만 고치는 지시는 소리와 무관
            if "from_t" in d:
                out.append((float(d["from_t"]), float(d["to_t"]), d))
    return out


def mid(w):
    return (w["start"] + w["end"]) / 2


def pick_gap(db, left, right, x):
    """left 낱말과 right 낱말 사이의 무음 (시작, 끝, 등급). 없으면 None.

    1등급: -50dB 아래로 40ms 이상 (완전한 무음)
    2등급: -45dB 아래로 20ms 이상 (말 사이 깊은 골). 1등급이 없을 때만
    """
    lo = mid(left) - REACH if left else x - REACH
    hi = mid(right) + REACH if right else x + REACH
    # 경계 양쪽 두 낱말을 넘어가지 않는다. 넘어가면 남길 낱말을 삭제 쪽으로 삼키거나,
    # 삭제 범위의 두 끝이 같은 무음으로 모인다(11차시 '먼저 먼저').
    if left:
        lo = max(lo, left["start"] + 0.05)
    if right:
        hi = min(hi, right["end"] - 0.05)
    ref = (left["end"] + right["start"]) / 2 if (left and right) else x
    c1 = L.silences(db, lo, hi, L.SILENT, 0.04)
    if c1:
        g = min(c1, key=lambda g: abs((g[0] + g[1]) / 2 - ref))
        return g[0], g[1], 1
    # 2등급은 낱말 안의 파열음 막힘일 수 있다. 1등급이 하나도 없을 때만,
    # 추정 경계 가까이에서만 받는다. 사람이 손본 편집본의 컷은 전부 1등급이었다.
    c2 = L.silences(db, max(lo, ref - 0.25), min(hi, ref + 0.25), DIP_DB, DIP_LEN)
    if c2:
        g = min(c2, key=lambda g: abs((g[0] + g[1]) / 2 - ref))
        return g[0], g[1], 2
    return None


def refine(speech, words, db, deletions):
    """덩어리를 나누고, 삭제 지시의 경계를 실제 무음 쪽으로 옮긴다.

    돌려주는 것: (나눈 speech, 못 나눈 경계 목록, 옮긴 삭제 지시 목록)
    """
    segs = [list(s) for s in speech["speech"]]
    ws = sorted((w for w in words if w.get("type", "word") == "word"),
                key=lambda w: w["start"])

    def seg_of(t):
        for s, e in segs:
            if s + EDGE < t < e - EDGE:
                return (s, e)
        return None

    unresolved, snapped, gaps = [], [], {}
    for a, b, d in deletions:
        new = [a, b]
        if d.get("exact"):
            # 사람이 덩어리 경계·파형으로 직접 잡은 지시. 옮기지 않는다.
            # (통짜 전사가 그 말을 흘렸으면 낱말 기준 맞추기가 엉뚱한 무음을 잡는다)
            for x in (a, b):
                sg = seg_of(x)
                if sg:
                    g = [s for s in L.silences(db, x - 0.3, x + 0.3) if s[0] - 0.02 <= x <= s[1] + 0.02]
                    if g:
                        gaps.setdefault(tuple(sg), set()).add((g[0][0], g[0][1], 1))
                    else:
                        unresolved.append({"t": round(x, 2), "left": "", "right": "",
                                           "reason": "직접 잡은 경계가 소리 위: " + str(d.get("reason", ""))[:40]})
            snapped.append((a, b, d))
            continue
        for k, x in enumerate((a, b)):
            left = [w for w in ws if mid(w) < x]
            right = [w for w in ws if mid(w) >= x]
            lw, rw = (left[-1] if left else None), (right[0] if right else None)
            g = pick_gap(db, lw, rw, x)
            if g is None:
                if seg_of(x):
                    unresolved.append({
                        "t": round(x, 2), "left": lw["text"] if lw else "",
                        "right": rw["text"] if rw else "",
                        "reason": str(d.get("reason", ""))[:60]})
                continue
            g0, g1, grade = g
            new[k] = round((g0 + g1) / 2, 3)          # 삭제 경계를 무음 한가운데로
            sg = seg_of(new[k])
            if sg:                                     # 덩어리 안이면 거기서 나눈다
                gaps.setdefault(tuple(sg), set()).add((g0, g1, grade))
        if new[1] - new[0] < 0.05:
            # 두 경계가 같은 무음으로 모였다 — 지울 말소리가 없다는 뜻이다.
            # 위스퍼가 한 낱말을 둘로 쪼갠 경우가 많다(11차시 '됩니다 됩니다').
            unresolved.append({"t": round(a, 2), "left": "", "right": "",
                               "reason": "경계가 한 무음으로 모임: " + str(d.get("reason", ""))[:40]})
            new = [a, b]
        snapped.append((new[0], new[1], d))

    out, n_split, n_dip = [], 0, 0
    for seg in segs:
        gs = sorted(gaps.get(tuple(seg), ()))
        if not gs:
            out.append(seg)
            continue
        s, e = seg
        cur = s
        for g0, g1, grade in gs:
            if g0 - cur > 0.02:
                out.append([round(cur, 3), round(g0, 3)])
            cur = max(cur, g1)
            n_split += 1
            n_dip += grade == 2
        if e - cur > 0.02:
            out.append([round(cur, 3), round(e, 3)])
    res = dict(speech)
    res["speech"] = out
    res["n_segments"] = len(out)
    res["refined"] = {"n_split": n_split, "n_dip": n_dip,
                      "n_unresolved": len(unresolved)}
    return res, unresolved, snapped


def snap_edges(keep_ranges, speech, db, offset=0.0):
    """블록 가장자리가 소리 위면 **발화 바깥 여백 안에서만** 무음 쪽으로 옮긴다.

    계획기는 발화 앞에 0.15~0.4초 여백을 둔다. 그 여백에 입술 소리·숨소리가 걸리면
    컷 지점이 소리 위에 떨어진다(11차시 11238초). 여백 안에 무음이 있으면 거기로 옮긴다.
    발화 구간 안으로는 절대 들어가지 않는다. `_컷점다듬기` 가 이걸 어겨서 말을 씹었다.
    keep_ranges 시각이 wav 시각과 다르면 offset(keep - wav)을 준다.
    """
    sp = [tuple(s) for s in speech["speech"]]
    out, moved = [], 0
    for a, b in keep_ranges:
        wa, wb = a - offset, b - offset
        inner = [(max(wa, x), min(wb, y)) for x, y in sp if y > wa and x < wb]
        if inner and L.level_at(db, wa) > L.SILENT:
            onset = inner[0][0]
            g = [s for s in L.silences(db, wa, onset - 0.03) if s[1] - s[0] >= 0.04]
            if g:
                s0, s1 = g[-1]                       # 발화에 가장 가까운 무음
                wa = max(s0 + 0.01, s1 - min(0.15, (s1 - s0) / 2))
                moved += 1
        if inner and L.level_at(db, wb) > L.SILENT:
            offs = inner[-1][1]
            g = [s for s in L.silences(db, offs + 0.02, wb) if s[1] - s[0] >= 0.04]
            if g:
                s0, s1 = g[0]
                wb = min(s1 - 0.01, s0 + min(0.15, (s1 - s0) / 2))
                moved += 1
        out.append([round(wa + offset, 6), round(wb + offset, 6)])
    return out, moved


def main(argv):
    opts = {}
    pos = []
    k = 0
    while k < len(argv):
        if argv[k].startswith("--"):
            opts[argv[k]] = argv[k + 1]
            k += 2
        else:
            pos.append(argv[k])
            k += 1
    speech_p, words_p, wav_p, out_p = pos[:4]
    dels = load_deletions(pos[4:])
    speech = json.loads(Path(speech_p).read_text(encoding="utf-8"))
    words = json.loads(Path(words_p).read_text(encoding="utf-8"))["words"]
    db = L.compute(wav_p, opts.get("--levels"))
    res, unresolved, snapped = refine(speech, words, db, dels)
    Path(out_p).write_text(json.dumps(res, ensure_ascii=False, indent=1),
                           encoding="utf-8")
    if opts.get("--snapped"):
        Path(opts["--snapped"]).write_text(json.dumps(
            {"deletions": [{**d, "from_t": a, "to_t": b} for a, b, d in snapped]},
            ensure_ascii=False, indent=1), encoding="utf-8")
    if opts.get("--report"):
        Path(opts["--report"]).write_text(
            json.dumps(unresolved, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"덩어리 {len(speech['speech'])} → {len(res['speech'])} "
          f"(무음에서 나눈 곳 {res['refined']['n_split']}, "
          f"그중 깊은 골 {res['refined']['n_dip']})")
    if unresolved:
        print(f"  무음이 없어 못 나눈 경계 {len(unresolved)}곳 — 말이 이어져 있다. "
              f"그대로 두고 보고서에 남긴다")


if __name__ == "__main__":
    main(sys.argv[1:])
