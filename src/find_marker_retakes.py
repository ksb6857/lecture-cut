# -*- coding: utf-8 -*-
"""
녹화 중 말한 '다시' 를 편집 신호로 읽어 실패 테이크를 잘라낸다.

녹화하다 말이 꼬이면 "다시" 라고 말한 뒤 처음부터 다시 말하면,
편집기가 그 지점을 100% 정확히 찾을 수 있다. STT 의 반복 억제나
문맥 추론에 기대지 않는 유일하게 확실한 방법이다.

삭제 범위: 직전 문장이 끝난 자리 ~ '다시' 를 말한 발화 덩어리의 끝
  (문장부호가 없으면 '다시' 앞 12초 또는 발화 덩어리 3개까지만 거슬러 간다)

실측: 이 강의에서도 이미 2차시 12회, 3차시 9회 '다시'라고 말하고 있었다.

사용: python src/find_marker_retakes.py <words.json> <speech.json> <out.json>
"""
import bisect
import json
import sys
from pathlib import Path

MARKERS = ("다시", "다시요", "다시할게요", "다시하겠습니다")
MAX_LOOKBACK_SEC = 12.0     # 이보다 멀리는 거슬러 올라가지 않는다
MAX_LOOKBACK_SEGS = 3       # 발화 덩어리 기준 상한


def norm(t):
    return t.strip().strip(".,?!…\"'")


def run(words_path, speech_path, out_path):
    words = [w for w in json.loads(Path(words_path).read_text(
        encoding="utf-8"))["words"] if w["type"] == "word"]
    speech = json.loads(Path(speech_path).read_text(
        encoding="utf-8"))["speech"]
    seg_starts = [s for s, _ in speech]

    def seg_of(t):
        i = bisect.bisect_right(seg_starts, t) - 1
        if i < 0:
            return None
        return i if speech[i][1] >= t - 0.3 else None

    dels = []
    for k, w in enumerate(words):
        if norm(w["text"]) not in MARKERS:
            continue
        si = seg_of(w["start"])
        if si is None:
            continue
        # '다시 만드는', '다시 그려줘' 처럼 뒷말을 꾸미는 경우는 신호가 아니다.
        # 실측: 평범한 쓰임은 뒷말과 간격이 정확히 0.00초로 붙어 있고,
        # 신호로 쓴 '다시' 만 0.08~0.22초 떨어져 있다.
        nxt = words[k + 1] if k + 1 < len(words) else None
        if nxt and nxt["start"] - w["end"] < 0.06:
            continue
        # 앞 문장이 끝나고 나온 '다시' 는 확실한 신호, 아니면 검토 대상
        prev_ends = k > 0 and words[k - 1]["text"].rstrip()[-1:] in ".?!"

        # 뒤로: '다시' 가 속한 발화 덩어리 끝까지 지운다
        to_t = speech[si][1]

        # 앞으로: 직전 문장이 끝난 자리까지 거슬러 올라간다
        from_t = None
        for j in range(k - 1, -1, -1):
            if words[j]["text"].rstrip()[-1:] in ".?!":
                from_t = words[j]["end"]
                break
            if w["start"] - words[j]["start"] > MAX_LOOKBACK_SEC:
                break
        lo_seg = max(0, si - MAX_LOOKBACK_SEGS)
        floor_t = speech[lo_seg][0]
        from_t = max(from_t, floor_t) if from_t is not None else floor_t
        if to_t - from_t < 0.3:
            continue

        txt = " ".join(x["text"] for x in words
                       if from_t <= x["start"] and x["end"] <= to_t + 0.3)
        dels.append({
            "from_t": round(from_t, 2), "to_t": round(to_t, 2),
            "text": txt[:100],
            "reason": "녹화 중 '다시'라고 말한 편집 신호 — 그 앞 실패 테이크 삭제",
            "confidence": "high" if prev_ends else "medium",
        })

    Path(out_path).write_text(
        json.dumps({"deletions": dels}, ensure_ascii=False, indent=1),
        encoding="utf-8")
    print(f"OK: '다시' 신호 {len(dels)}곳 -> {out_path}")
    for d in dels:
        m = int(d["from_t"] // 60)
        print(f"  {m:02d}:{d['from_t'] % 60:05.2f}~{d['to_t']:.1f}s  "
              f"「{d['text'][:60]}」")
    return dels


if __name__ == "__main__":
    run(*sys.argv[1:4])
