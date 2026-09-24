# -*- coding: utf-8 -*-
"""길이 예산: 러프컷이 규격보다 길 때 뺄 후보를 '역할'로 고르고 합계를 맞춘다.

video-use 는 편집 에이전트에게 목표 길이와 구조(도입, 준비, 단계, 주의, 정리)를 주고 넘치면 구간을 덜어
합계를 다시 보고하게 한다. 강의 러프컷은 늘 사람이 고르므로, 여기서는 **후보표를 만든다.**

  구간  남는 블록을 장(교안 번호)·화면 단위로 묶어 편집 시각·길이·첫 말을 적는다. 후보를 고를 때 본다
  예산  후보 파일(역할·왜·빼면)을 받아 위에서부터 뺄 때의 누적 길이를 계산하고 표를 쓴다.
        목표보다 짧아지는 가장 앞 묶음을 추천으로 표시한다. 고른 번호는 원본 시각 삭제 지시로 내보낸다

후보의 역할(뺄 때 앞에 둘수록 잃는 것이 적다)
  되풀이      앞에서 이미 보여 주거나 말한 것 (검수서: 같은 설명은 한 번만)
  곁가지      절차 밖에 덧붙인 팁
  꼬인 문장   다시 시작하거나 같은 뜻을 되풀이한 문장
  예시 세부   예를 길게 읽어 주는 부분
  말 없는 장  말 없이 띄운 교안 장의 길이
  설명        까닭·개념 설명 (웬만하면 빼지 않는다)

**후보마다 '왜'를 반드시 적는다**(2026-09-24 "왜 빼는지는 안 알려주는 건가" 지적).

후보 파일:
  {"target": 1500, "margin": 10,
   "items": [{"no": 1, "edit": [741.7, 783.2], "role": "되풀이", "what": "…", "why": "…", "lose": "…"},
             {"no": 9, "seconds": 24, "role": "말 없는 장", "what": "…", "why": "…", "lose": "…"}]}
  edit 는 편집본 시각(초). 구간이 아닌 후보(말 없는 장 줄이기)는 seconds 로 줄어드는 길이만 적는다.

사용: python length_budget.py 구간 <keep.json> <words.json> [--spans 장구간.json] --out 구간표.md
     python length_budget.py 예산 <keep.json> <후보.json> --out 후보표.md [--pick 1,2,3 --deletions 지시.json]
"""
import json
import sys
from pathlib import Path

def mmss(t):
    return f"{int(t // 60):02d}:{t % 60:04.1f}"


def edges(keep):
    out, e = [], 0.0
    for a, b in keep:
        out.append((a, b, e))
        e += b - a
    return out, e


def edit_to_src(blocks, a, b):
    """편집 구간 → 원본 구간들 (블록 경계에서 나뉜다)."""
    res = []
    for p, q, e0 in blocks:
        e1 = e0 + (q - p)
        lo, hi = max(a, e0), min(b, e1)
        if hi > lo:
            res.append([round(p + (lo - e0), 3), round(p + (hi - e0), 3)])
    return res


def sections(keep, words, spans=None):
    blocks, total = edges(keep)

    def label(a, b):
        m = (a + b) / 2
        for s in spans or []:
            if s["a"] <= m <= s["b"]:
                return f"S{s['slide']:02d}"
        return "화면"
    groups = []
    for a, b, e0 in blocks:
        lab = label(a, b)
        if groups and groups[-1]["lab"] == lab:
            groups[-1]["b"] = b
            groups[-1]["dur"] += b - a
        else:
            groups.append({"lab": lab, "a": a, "b": b, "dur": b - a, "edit": e0})
    for g in groups:
        ws = [w["text"] for w in words if w.get("type", "word") == "word" and g["a"] <= w["start"] < g["b"]]
        g["first"] = " ".join(ws[:14])
    return groups, total


def budget(keep, cand, pick=None):
    blocks, total = edges(keep)
    items = cand["items"]
    target, margin = cand.get("target", 1500), cand.get("margin", 10)
    rows, cum, rec = [], 0.0, None
    for it in items:
        sec = it.get("seconds")
        if sec is None:
            sec = it["edit"][1] - it["edit"][0]
        cum += sec
        rows.append((it, sec, cum, total - cum))
        if rec is None and total - cum <= target - margin:
            rec = it["no"]
    lines = [f"지금 길이 **{mmss(total)}** · 목표 {mmss(target)} 이하(여유 {margin}초)", ""]
    for it, sec, _, _ in rows:
        where = f"{mmss(it['edit'][0])} ~ {mmss(it['edit'][1])}" if "edit" in it else "여러 곳"
        lines += [f"**{it['no']}. {where} · {sec:.1f}초 · {it['what']}** ({it.get('role', '')})",
                  f"- 왜: {it['why']}", f"- 빼면: {it['lose']}", ""]
    lines += ["| 뺀 번호 | 줄어드는 길이 | 남는 길이 |", "|---|---|---|"]
    for it, sec, c, left in rows:
        mark = "**" if rec is not None and it["no"] == rec else ""
        first = rows[0][0]["no"]
        lab = f"{first}" if it["no"] == first else f"{first}~{it['no']}"
        lines.append(f"| {mark}{lab}{mark} | {c:.1f}초 | {mark}{mmss(left)}{mark} |")
    if rec is not None:
        lines += ["", f"목표 안으로 들어오는 가장 앞 묶음: {rows[0][0]['no']}~{rec}번"]
    dels = []
    if pick:
        for it in items:
            if it["no"] in pick and "edit" in it:
                for a, b in edit_to_src(blocks, *it["edit"]):
                    dels.append({"from_t": a, "to_t": b, "kind": "retake", "exact": True,
                                 "reason": f"길이 후보 {it['no']}번: {it['what']}", "text": ""})
    return "\n".join(lines), dels


def main(argv):
    cmd, pos, opt, k = argv[0], [], {}, 1
    while k < len(argv):
        if argv[k].startswith("--"):
            opt[argv[k]] = argv[k + 1]
            k += 2
        else:
            pos.append(argv[k])
            k += 1
    keep = json.loads(Path(pos[0]).read_text(encoding="utf-8"))["keep_ranges"]
    if cmd == "구간":
        words = json.loads(Path(pos[1]).read_text(encoding="utf-8"))["words"]
        spans = json.loads(Path(opt["--spans"]).read_text(encoding="utf-8")) if "--spans" in opt else None
        groups, total = sections(keep, words, spans)
        lines = [f"전체 {mmss(total)}", "", "| 편집 시각 | 장 | 길이 | 첫 말 |", "|---|---|---|---|"]
        lines += [f"| {mmss(g['edit'])} | {g['lab']} | {g['dur']:.1f}초 | {g['first']} |" for g in groups]
        text = "\n".join(lines)
    else:
        cand = json.loads(Path(pos[1]).read_text(encoding="utf-8"))
        pick = {int(x) for x in opt["--pick"].split(",")} if "--pick" in opt else None
        text, dels = budget(keep, cand, pick)
        if pick and "--deletions" in opt:
            Path(opt["--deletions"]).write_text(json.dumps({"deletions": dels}, ensure_ascii=False, indent=1),
                                                encoding="utf-8")
            text += f"\n\n고른 번호 {sorted(pick)} → 삭제 지시 {len(dels)}건 ({opt['--deletions']})"
    print(text)
    if "--out" in opt:
        Path(opt["--out"]).write_text(text + "\n", encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv[1:])
