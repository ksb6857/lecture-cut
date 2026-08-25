# -*- coding: utf-8 -*-
"""
컷 결과 안전성 검증: 잘라낸 구간에 실제 발화가 들어있지 않은지 확인한다.

speech.json(VAD) 을 정답으로 놓고 keep_ranges.json 을 채점한다.
- 잘린 발화: 삭제 구간에 남아있던 VAD 발화 시간 (재발화 삭제분은 의도된 것)
- 경계 침범: 각 컷 경계가 발화 시작/끝에서 얼마나 떨어져 있는지
"""
import json
import sys
from pathlib import Path


def overlap(a, b):
    return max(0.0, min(a[1], b[1]) - max(a[0], b[0]))


def verify(speech_path, ranges_path):
    sp = json.loads(Path(speech_path).read_text(encoding="utf-8"))
    plan = json.loads(Path(ranges_path).read_text(encoding="utf-8"))
    speech = sp["speech"]
    keep = plan["keep_ranges"]

    total_speech = sum(e - s for s, e in speech)
    kept_speech = 0.0
    partial = []          # 발화 구간이 중간에서 잘린 사례
    for seg in speech:
        cov = sum(overlap(seg, k) for k in keep)
        kept_speech += cov
        span = seg[1] - seg[0]
        if 0.15 < cov < span - 0.15:      # 일부만 남음 = 말 중간 컷
            partial.append((seg, round(cov, 2), round(span, 2)))

    lost = total_speech - kept_speech
    print(f"전체 발화 {total_speech/60:.1f}분 중 "
          f"{kept_speech/60:.1f}분 유지, {lost/60:.1f}분 제거")
    print(f"  (제거분은 재발화 삭제 의도분 + 잘린 사고분의 합)")
    print(f"발화 구간이 중간에서 잘린 사례: {len(partial)}건")
    for seg, cov, span in partial[:10]:
        m = int(seg[0] // 60)
        print(f"  {m:02d}:{int(seg[0]%60):02d}  {span}초 발화 중 {cov}초만 남음")
    if len(partial) > 10:
        print(f"  ... 외 {len(partial)-10}건")

    # 각 컷 지점이 발화로부터 얼마나 떨어져 있나
    starts = [s for s, _ in speech]
    ends = [e for _, e in speech]
    tight = 0
    for i, (ks, ke) in enumerate(keep):
        after = min((abs(ke - e) for e in ends), default=9)
        before = min((abs(ks - s) for s in starts), default=9)
        if after < 0.1 or before < 0.1:
            tight += 1
    print(f"발화에 0.1초 이내로 바짝 붙은 컷: {tight}곳 / {len(keep)*2}곳")
    return len(partial)


if __name__ == "__main__":
    verify(sys.argv[1], sys.argv[2])
