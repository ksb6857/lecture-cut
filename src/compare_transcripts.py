# -*- coding: utf-8 -*-
"""세 전사를 나란히 놓고 어긋난 자리를 찾는다.

  A 통짜 위스퍼    words.json        — 파이프라인이 쓰는 본 전사
  B 덩어리 위스퍼  persegment.json   — 발화 덩어리마다 따로 돌린 것
  C CTC           ctc.json          — 언어모델 없는 두 번째 모델

세 가지를 내놓는다.

  환각   A·B 는 길게 말했는데 C 가 소리를 거의 못 찾은 자리.
         `<이름>_hallucination.json` 으로 나가고, 자막에서만 뺀다.
  누락   파형은 발화로 봤고 B·C 는 받아 적었는데 A 에는 한 글자도 없는 자리.
         `<이름>_missing.json` 으로 나가고 `fill_missing_words.py` 가 메운다.
  불일치 세 전사가 크게 어긋난 자리. 보고서에만 싣는다.

실측(110분 강의): 통짜 전사가 발화 덩어리 69개 61.3초를 통째로 흘렸고 그중
하나가 학습 목표를 마무리하는 문장이었다. 환각 18곳은 **전부 0.6초 미만
덩어리**에서 났다(0.6초 이상 699개에서는 0곳).

사용: python src/compare_transcripts.py <words.json> <speech.json>
                                        <persegment.json> <ctc.json>
                                        <보고서.md> [--접두 work/<이름>]
"""
import bisect
import json
import re
import sys
from difflib import SequenceMatcher
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cliargs import split_args  # noqa: E402

JAMO = re.compile(r"[^가-힣0-9a-zA-Z]")
SHORT = 0.6          # 이보다 짧은 덩어리는 환각이 잘 난다


def norm(s):
    return JAMO.sub("", s or "")


def sim(a, b):
    a, b = norm(a), norm(b)
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b, autojunk=False).ratio()


def hms(t):
    return f"{int(t//60):3d}:{t%60:04.1f}"


def run(words_p, speech_p, seg_p, ctc_p, out_p, prefix=None):
    ws = [w for w in json.loads(Path(words_p).read_text(encoding="utf-8"))["words"]
          if w["type"] == "word"]
    speech = json.loads(Path(speech_p).read_text(encoding="utf-8"))["speech"]
    B = {t["i"]: t for t in json.loads(
        Path(seg_p).read_text(encoding="utf-8"))["takes"]}
    C = {r["i"]: r for r in json.loads(
        Path(ctc_p).read_text(encoding="utf-8"))["segments"]}

    starts = [w["start"] for w in ws]
    rows = []
    for i, (a, b) in enumerate(speech):
        lo = bisect.bisect_left(starts, a - 0.3)
        hi = bisect.bisect_right(starts, b + 0.3)
        rows.append({"i": i, "start": a, "end": b, "dur": round(b - a, 2),
                     "A": " ".join(w["text"] for w in ws[lo:hi]),
                     "B": (B.get(i) or {}).get("text", ""),
                     "C": (C.get(i) or {}).get("text", "")})

    환각, 누락, 불일치 = [], [], []
    for r in rows:
        nA, nB, nC = norm(r["A"]), norm(r["B"]), norm(r["C"])
        longer = max(len(nA), len(nB))
        if longer >= 8 and len(nC) * 3 < longer:
            환각.append(r)
            continue
        if not nA and len(nB) >= 3 and len(nC) >= 2:
            누락.append(r)
            continue
        if nB and (sim(r["A"], r["B"]) < 0.6 or sim(r["B"], r["C"]) < 0.45):
            불일치.append(r)

    short = [r for r in 환각 if r["dur"] < SHORT]
    if prefix:
        Path(f"{prefix}_hallucination.json").write_text(json.dumps(
            {"deletions": [{"from_t": r["start"], "to_t": r["end"],
                            "text": (r["A"] or r["B"])[:80],
                            "reason": "CTC 가 소리를 못 찾았다. 위스퍼가 지어낸 말",
                            "confidence": "high", "kind": "hallucination"}
                           for r in 환각]}, ensure_ascii=False, indent=1),
            encoding="utf-8")
        Path(f"{prefix}_missing.json").write_text(json.dumps(
            {"segments": [{"i": r["i"], "start": r["start"], "end": r["end"],
                           "text": r["B"], "ctc": r["C"]} for r in 누락]},
            ensure_ascii=False, indent=1), encoding="utf-8")

    def table(items):
        out = ["| 시각 | 길이 | 통짜 위스퍼 | 덩어리 위스퍼 | CTC |",
               "|---|---|---|---|---|"]
        for r in items:
            out.append(f"| {hms(r['start'])} | {r['dur']}초 "
                       f"| {r['A'][:60] or '—'} | {r['B'][:60] or '—'} "
                       f"| {r['C'][:60] or '—'} |")
        return "\n".join(out)

    md = [
        "# 전사 교차검증 — 위스퍼 × CTC",
        "",
        f"발화 덩어리 {len(rows)}개를 세 전사로 비교했다.",
        "CTC 는 언어모델이 없어 무음에서 글자를 지어내지 못한다. 그래서 환각 판정에 쓴다.",
        "",
        f"- 환각으로 보이는 곳 **{len(환각)}곳** "
        f"(그중 {len(short)}곳이 {SHORT}초 미만 덩어리)",
        f"- 통짜 전사가 흘린 말 **{len(누락)}곳**",
        f"- 세 전사가 크게 어긋난 곳 **{len(불일치)}곳**",
        "",
        "## 1. 환각 — 위스퍼가 지어낸 말",
        "",
        "자막에서 뺀다. 영상은 파형이 판단한다.",
        "**짧은 덩어리에 몰려 있으면 `transcribe_per_segment.py --최소길이` 를 올려라.**",
        "",
        table(환각),
        "",
        "## 2. 통짜 전사가 흘린 말",
        "",
        "파형은 발화로 봤고 덩어리 전사와 CTC 둘 다 받아 적었는데 통짜 전사에는 없다.",
        "**컷은 파형 기준이라 영상에는 남아 있다.** 자막과 재발화 판정에서만 빠졌다.",
        "`fill_missing_words.py` 로 메우고 나서 4단계로 넘어가라.",
        "",
        table(누락),
        "",
        "## 3. 세 전사가 어긋난 곳",
        "",
        table(불일치),
        "",
    ]
    Path(out_p).write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"환각 {len(환각)}곳({SHORT}초 미만 {len(short)}곳) · "
          f"누락 {len(누락)}곳 · 불일치 {len(불일치)}곳 -> {out_p}")
    if prefix:
        print(f"  {prefix}_hallucination.json / {prefix}_missing.json")
    return 환각, 누락, 불일치


if __name__ == "__main__":
    pos, opt = split_args(sys.argv[1:], {"--접두", "--prefix"})
    run(*pos[:5], prefix=opt.get("--접두") or opt.get("--prefix"))
