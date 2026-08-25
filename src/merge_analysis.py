# -*- coding: utf-8 -*-
"""
청크별 LLM 분석 JSON들 -> 병합된 analysis.json + retakes.json

- 겹침 구간 중복 검출 제거 (범위가 겹치면 하나로 합침)
- high confidence 삭제만 retakes.json 에 반영 (자동 적용)
- medium 은 review 목록으로 분리 (보고서에서 사람이 확인)
- corrections 는 인덱스 기준 중복 제거
"""
import json
import sys
from pathlib import Path


def merge(in_dir, analysis_out, retakes_out):
    dels, fixes = [], {}
    for p in sorted(Path(in_dir).glob("result_*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        dels.extend(d.get("deletions", []))
        for c in d.get("corrections", []):
            fixes[c["i"]] = c

    # 범위 겹침 병합 (신뢰도는 높은 쪽 유지)
    dels.sort(key=lambda d: (d["from_i"], d["to_i"]))
    merged = []
    for d in dels:
        if merged and d["from_i"] <= merged[-1]["to_i"] + 1:
            m = merged[-1]
            m["to_i"] = max(m["to_i"], d["to_i"])
            if d["confidence"] == "high":
                m["confidence"] = "high"
            if d["reason"] not in m["reason"]:
                m["reason"] += " / " + d["reason"]
        else:
            merged.append(dict(d))

    high = [d for d in merged if d["confidence"] == "high"]
    review = [d for d in merged if d["confidence"] != "high"]

    Path(analysis_out).write_text(json.dumps({
        "deletions_applied": high,
        "deletions_review": review,
        "corrections": sorted(fixes.values(), key=lambda c: c["i"]),
    }, ensure_ascii=False, indent=1), encoding="utf-8")

    Path(retakes_out).write_text(json.dumps(
        {"deletions": high}, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"OK: 삭제 확정 {len(high)}건, 검토 필요 {len(review)}건, "
          f"자막 교정 {len(fixes)}건")


if __name__ == "__main__":
    merge(sys.argv[1], sys.argv[2], sys.argv[3])
