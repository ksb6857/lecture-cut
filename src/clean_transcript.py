# -*- coding: utf-8 -*-
"""
전사본에서 Whisper 환각(유튜브 자막 상투구)을 제거한다.

Whisper 는 학습 데이터에 유튜브 자막이 많이 섞인 탓에, 말이 잠시 끊긴 자리에
"시청해주셔서 감사합니다", "다음 영상에서 만나요" 같은 문구를 만들어 넣는다.
실제로 2차시 12:49 에는 이런 삽입이 있었다:
  "한글이 들어간 [다음 영상에서 만나요.] 포스터나 안내자료까지 만들 수 있는"

주의: 영상 끝의 "그럼 다음 차시에서 뵙겠습니다. 감사합니다" 는 진짜 인사다.
그래서 마지막 tail_keep 초 안에 있는 것은 건드리지 않는다.

사용: python src/clean_transcript.py <words.json> <out.json>
"""
import json
import sys
from pathlib import Path

# 연속 단어열로 매칭할 상투구 (띄어쓰기 무시하고 붙여서 비교)
ARTIFACTS = [
    "시청해주셔서감사합니다",
    "시청해주셔서감사드립니다",
    "다음영상에서만나요",
    "다음시간에만나요",
    "다음영상에서뵙겠습니다",
    "구독과좋아요",
    "구독좋아요알림설정",
    "자막제공",
    "8시뉴스마칩니다",
    "뉴스마칩니다",
    "한글자막by",
    "이만마치겠습니다시청해주셔서",
]
MAX_SPAN = 8          # 상투구 하나가 차지할 수 있는 최대 단어 수
TAIL_KEEP = 40.0      # 영상 마지막 이 시간 안쪽은 진짜 인사로 보고 보존


def clean(in_path, out_path):
    data = json.loads(Path(in_path).read_text(encoding="utf-8"))
    words = data["words"]
    total = max((w["end"] for w in words), default=0)

    drop = set()
    n = len(words)
    for i in range(n):
        if i in drop:
            continue
        acc = ""
        for j in range(i, min(n, i + MAX_SPAN)):
            acc += words[j]["text"].replace(" ", "")
            norm = acc.replace(".", "").replace(",", "").replace("!", "") \
                      .replace("?", "").replace("~", "")
            if norm in ARTIFACTS:
                if words[j]["end"] >= total - TAIL_KEEP:
                    break            # 끝인사는 살린다
                drop.update(range(i, j + 1))
                break
            if len(norm) > 20:
                break

    kept = [w for k, w in enumerate(words) if k not in drop]
    removed = [words[k] for k in sorted(drop)]

    # 인덱스 재부여 (이후 단계가 i 를 키로 쓴다)
    for new_i, w in enumerate(kept):
        w["i"] = new_i

    data["words"] = kept
    data["hallucinations_removed"] = len(removed)
    Path(out_path).write_text(
        json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"OK: 환각 {len(removed)}단어 제거, {len(kept)}단어 남김 -> {out_path}")
    if removed:
        runs, cur = [], [removed[0]]
        for w in removed[1:]:
            if w["start"] - cur[-1]["end"] < 1.0:
                cur.append(w)
            else:
                runs.append(cur)
                cur = [w]
        runs.append(cur)
        for r in runs:
            t = " ".join(x["text"] for x in r)
            print(f"   [{int(r[0]['start']//60):02d}:"
                  f"{int(r[0]['start']%60):02d}] {t}")
    return data


if __name__ == "__main__":
    clean(sys.argv[1], sys.argv[2])
