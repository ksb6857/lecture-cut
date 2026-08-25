# -*- coding: utf-8 -*-
"""analysis.json + keep_ranges.json + words.json -> 검수 보고서(.md)

- 자동 적용된 삭제(재발화) 목록
- 검토 필요(medium) 목록: 영상에 남아있으므로 편집 타임라인 기준 위치 표기
- 자막 교정 목록
"""
import json
import sys
from pathlib import Path


def fmt(sec):
    m, s = divmod(int(sec), 60)
    return f"{m:02d}:{s:02d}"


def make(words_path, ranges_path, analysis_path, out_path, title,
         repeat_review=None):
    words = {w["i"]: w for w in json.loads(
        Path(words_path).read_text(encoding="utf-8"))["words"]}
    plan = json.loads(Path(ranges_path).read_text(encoding="utf-8"))
    ana = json.loads(Path(analysis_path).read_text(encoding="utf-8"))

    ranges = plan["keep_ranges"]
    offsets, t = [], 0.0
    for s, e in ranges:
        offsets.append(t)
        t += e - s

    def src_time(d):
        """삭제 지시의 원본 시각. 단어 인덱스 형식과 시간 형식을 모두 받는다.
        (덩어리별 전사·반복 검출은 시간 형식으로 내놓는다)"""
        if "from_t" in d:
            return float(d["from_t"])
        w = words.get(d.get("from_i"))
        return w["start"] if w else 0.0

    def to_edit_time(src_t):
        prev = 0.0
        for (s, e), off in zip(ranges, offsets):
            if src_t < s:
                return prev
            if src_t <= e:
                return off + (src_t - s)
            prev = off + (e - s)
        return t

    L = [f"# {title} 자동 편집 검수 보고서", ""]
    L.append(f"- 원본 {plan['src_duration']/60:.1f}분 → 편집 후 "
             f"{plan['kept_duration']/60:.1f}분")
    L.append(f"- 무음 컷 {plan['n_silence_cuts']}곳, "
             f"재발화 삭제 {len(plan.get('retakes_applied', []))}건 적용, "
             f"자막 교정 {len(ana['corrections'])}건")
    if plan.get("boundary_source") == "vad":
        L.append("- 컷 경계는 자막이 아니라 **파형(VAD) 기준** — "
                 "발화 구간을 중간에서 자르지 않음")
    L.append("")

    review = list(ana["deletions_review"]) + list(plan.get("retakes_unapplied", []))
    L.append("## 1. 검토 필요 구간 (영상에 남겨둠 — 직접 판단해서 삭제하세요)")
    L.append("")
    L.append("| 편집본 위치 | 내용 | 판단 근거 |")
    L.append("|---|---|---|")
    for d in sorted(review, key=src_time):
        L.append(f"| {fmt(to_edit_time(src_time(d)))} | {d.get('text','')[:40]} "
                 f"| {d.get('reason','')[:60]} |")
    L.append("")

    L.append("## 2. 자동 삭제된 재발화 구간 (이미 잘려나감)")
    L.append("")
    L.append("| 원본 위치 | 삭제된 내용 | 근거 |")
    L.append("|---|---|---|")
    for d in sorted(plan.get("retakes_applied", ana["deletions_applied"]),
                    key=src_time):
        L.append(f"| {fmt(src_time(d))} | {d.get('text','')[:40]} "
                 f"| {d.get('reason', d.get('kind',''))[:60]} |")
    L.append("")

    if repeat_review and Path(repeat_review).exists():
        cands = json.loads(Path(repeat_review).read_text(
            encoding="utf-8"))["candidates"]
        L.append("## 2-1. 반복으로 보이지만 확신이 없어 남겨둔 곳")
        L.append("")
        L.append("기계가 같은 말이 두 번 나온 걸 찾았지만, 재봤더니 이 등급은")
        L.append("절반쯤이 멀쩡한 말이었다(강의 용어가 다시 나온 것). 그래서")
        L.append("지우지 않고 여기 적어둔다. 보고 아니다 싶으면 그냥 두면 된다.")
        L.append("")
        L.append("| 편집본 위치 | 앞 테이크 | 뒤에 다시 나온 말 |")
        L.append("|---|---|---|")
        for c in sorted(cands, key=lambda x: x["from_t"]):
            L.append(f"| {fmt(to_edit_time(c['from_t']))} "
                     f"| {c['dropped'][:46]} | {c['kept'][:34]} |")
        L.append("")

    L.append("## 3. 자막 교정 내역")
    L.append("")
    L.append("| 원문 | 교정 |")
    L.append("|---|---|")
    for c in ana["corrections"]:
        L.append(f"| {c['orig']} | {c['fixed']} |")
    L.append("")

    Path(out_path).write_text("\n".join(L), encoding="utf-8")
    print(f"OK: {out_path}")


if __name__ == "__main__":
    make(*sys.argv[1:7])
