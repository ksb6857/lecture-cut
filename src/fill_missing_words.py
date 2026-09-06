# -*- coding: utf-8 -*-
"""통짜 전사가 흘린 발화 덩어리를 words.json 에 메운다.

위스퍼는 긴 오디오를 30초 창으로 훑다가 발화 덩어리를 통째로 건너뛸 때가
있다(long-form content omission). 실측: 110분 강의에서 69개 덩어리 61.3초가
통짜 전사에 한 글자도 없었고, 그중 하나가 학습 목표를 마무리하는 문장이었다.

컷은 파형 기준이라 그 말은 영상에 남는다. 그런데 전사에 없으면
**재발화 판정과 자막이 그 구간을 못 본다.** 같은 문장을 세 번 말했는데
전사에 두 번만 있어 러프컷에 중복이 남는 사고가 실제로 났다.

덩어리별 전사(persegment.json)의 문장을 덩어리 길이에 맞춰 고르게 나눠
넣는다. 시각은 어림값이므로 `"filled": true` 로 표시한다.
**컷 경계는 여기서 가져오지 않는다.** 그건 파형(VAD) 몫이다.

사용: python src/fill_missing_words.py <words.json> <missing.json> <out.json>
"""
import json
import sys
from pathlib import Path


def run(words_p, missing_p, out_p):
    doc = json.loads(Path(words_p).read_text(encoding="utf-8"))
    words = doc["words"]
    miss = json.loads(Path(missing_p).read_text(encoding="utf-8"))["segments"]

    # words.json 의 i 는 전역 단어 번호이고, 자막 교정(corrections)과
    # 삭제 지시(from_i/to_i)가 이 번호를 가리킨다. 메운 낱말에 같은 번호를
    # 주면 남의 교정이 딸려 온다. **기존 최대값 뒤에 새 번호를 붙인다.**
    # 시간순으로는 사이에 끼어들지만 번호는 뒤라서 기존 지시가 안 흔들린다.
    nxt = max((w.get("i", -1) for w in words if w.get("type") == "word"),
              default=-1) + 1
    added = []
    for m in miss:
        toks = [t for t in (m.get("text") or "").split() if t]
        if not toks:
            continue
        a, b = float(m["start"]), float(m["end"])
        step = (b - a) / len(toks)
        for k, t in enumerate(toks):
            added.append({"i": nxt + len(added), "type": "word", "text": t,
                          "start": round(a + k * step, 3),
                          "end": round(a + (k + 1) * step, 3),
                          "filled": True})
    if not added:
        print("메울 것이 없다.")
        Path(out_p).write_text(json.dumps(doc, ensure_ascii=False, indent=1),
                               encoding="utf-8")
        return doc

    merged = sorted(words + added,
                    key=lambda w: (w.get("start", 0.0), w.get("end", 0.0)))
    doc["words"] = merged
    doc["filled_words"] = len(added)
    Path(out_p).write_text(json.dumps(doc, ensure_ascii=False, indent=1),
                           encoding="utf-8")
    secs = sum(float(m["end"]) - float(m["start"]) for m in miss)
    print(f"OK: 덩어리 {len(miss)}개({secs:.1f}초)에서 낱말 {len(added)}개를 메웠다 "
          f"-> {out_p}")
    print("   이후 단계는 이 파일을 words.json 자리에 넣어라.")
    return doc


if __name__ == "__main__":
    run(*sys.argv[1:4])
