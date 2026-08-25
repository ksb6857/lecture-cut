# -*- coding: utf-8 -*-
"""파트 앞머리의 육성 슬레이트를 찾아 삭제 지시로 내놓는다.

파트를 나눠 찍을 때 테이크마다 앞에 슬레이트를 넣는 촬영 방식이 있다.

    녹화 시작 -> 3초 대기 -> "김상백, 6차시, 테이크 1" -> 잠깐 멈춤
              -> 대본 낭독 -> 3초 대기 -> 녹화 종료

이 슬레이트와 앞 여유는 편집에서 잘라내야 한다. 파트 경계
(`merge_parts.py --json`)를 알고 있으면 기계로 찾을 수 있다.

**찾는 방법.** 파트 시작부터 `--window` 초(기본 25초) 안에서 슬레이트 낱말이
들어간 발화를 찾고, 파트 시작부터 그 발화 끝까지를 지운다. 낱말은 '테이크'
'take' 'T1' 처럼 슬레이트에만 나오는 것을 쓴다. 차시 번호나 이름은 본문에도
나오므로 단독 근거로 쓰지 않는다.

**못 찾은 파트는 지우지 않고 알려만 준다.** 슬레이트를 빼먹고 찍은 파트가
있는데 앞부분을 통째로 지우면 강의 첫 문장이 사라진다. 그런 파트는 사람이
듣고 판정한다.

결과는 `cut_planner.py` 가 그대로 먹는 시간 기반 삭제 지시다.

사용: python src/find_slates.py <words.json> <parts.json> <out.json>
                                [--window 25] [--pad 0.3]
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cliargs import split_args  # noqa: E402

# 슬레이트에만 나오는 낱말. 본문에 섞이면 오검출이 되므로 좁게 잡는다.
MARK = re.compile(r"테이크|테익|take|^T\d$|슬레이트", re.I)


def run(words_path, parts_path, out_path, window=25.0, pad=0.3):
    words = [w for w in json.loads(Path(words_path).read_text(
        encoding="utf-8"))["words"] if w.get("type") == "word"]
    parts = json.loads(Path(parts_path).read_text(encoding="utf-8"))["parts"]

    dels, missed = [], []
    for p in parts:
        head = [w for w in words
                if p["start"] <= w["start"] < p["start"] + window]
        hits = [w for w in head if MARK.search(w["text"])]
        if not hits:
            missed.append(p)
            continue
        last = hits[-1]
        # 슬레이트 낱말 뒤에 붙은 숫자('테이크 1')까지 삼킨다
        tail = [w for w in head
                if last["end"] <= w["start"] <= last["end"] + 1.0]
        end = max([last["end"]] + [w["end"] for w in tail]) + pad
        dels.append({
            "from_t": round(p["start"], 3),
            "to_t": round(min(end, p["end"]), 3),
            "text": " ".join(w["text"] for w in head
                             if w["start"] <= end)[:80],
            "reason": f"{p['part']}번 파트 앞머리 슬레이트",
            "confidence": "high",
        })

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(json.dumps(
        {"deletions": dels}, ensure_ascii=False, indent=1), encoding="utf-8")

    total = sum(d["to_t"] - d["from_t"] for d in dels)
    print(f"파트 {len(parts)}개 중 슬레이트 {len(dels)}개 발견, "
          f"합계 {total:.1f}초")
    for d in dels:
        print(f"  {d['from_t']:8.2f}~{d['to_t']:8.2f}  {d['reason']}")
        print(f"      「{d['text']}」")
    if missed:
        print(f"\n슬레이트를 못 찾은 파트 {len(missed)}개. "
              f"직접 들어 보고 판정한다 (자동으로 지우지 않았다):")
        for p in missed:
            print(f"  {p['part']:>3}  {p['title']:<12} "
                  f"{p['start']:8.2f}초부터")
    print(f"\n{out_path}")
    return {"deletions": dels, "missed": missed}


if __name__ == "__main__":
    pos, opt = split_args(sys.argv[1:], {"--window", "--pad"})
    if len(pos) < 3:
        raise SystemExit(__doc__)
    run(pos[0], pos[1], pos[2],
        window=float(opt.get("--window", 25.0)),
        pad=float(opt.get("--pad", 0.3)))
