# -*- coding: utf-8 -*-
"""삭제 지시들이 서로 반대로 판단해 말을 통째로 없애는 것을 막는다.

이 파이프라인은 재발화를 여러 검출기가 따로 찾는다:
  retakes2.json      LLM 이 전사본 청크를 읽고 판단
  hidden2.json       덩어리별 독립 재전사로 찾아낸 것
  hidden_judged.json 위 결과를 사람/LLM 이 판정한 것
  repeats.json       find_repeat_retakes.py 가 기계적으로 찾은 것
지금까지 이걸 그냥 합쳐서 적용했다. 검출기끼리 반대로 판단하면 어떻게
되는지 아무도 확인하지 않았다.

실제 사고 (3차시 v5, 원본 55:24):
    발화 3324.70~3326.80  "이렇게 창을 여러개 만들어두고"   <- 1번 테이크
    발화 3336.60~3338.60  "이렇게 창을 여러개 만들어두고"   <- 2번 테이크
    retakes2 : 3336.12~3338.32 삭제 ("앞 테이크가 더 완결됨")
    hidden2  : 3324.70~3326.80 삭제 ("같은 문장을 그대로 다시 말함")
    -> 둘 다 적용되어 두 테이크가 다 사라졌다. 문장이 통째로 없어졌다.

불변식: **재발화 삭제는 같은 말이 어딘가 남아 있을 때만 정당하다.**
같은 말을 노리는 삭제 지시가 여럿이면 마지막 테이크 하나는 반드시 남긴다.

마지막 것을 남기는 근거: 2차시에서 사용자가 손수 지운 43곳을 보면
지운 쪽은 언제나 **앞** 테이크였다(70:46 '모든 삽화의 그림체는…',
92:19 '조금씩', 91:17 '스타일 기준' 등). 말하다 고쳐 말하면 뒤엣것이
완결된 테이크이고 다음 문장으로 이어지기 때문이다.
"""
import difflib
import re
import sys

PUNCT = re.compile(r"[^\w가-힣]+")

CONFLICT_WINDOW = 90.0   # 이 안에 있는 삭제들끼리만 같은 말인지 본다
MIN_RUN = 3              # 연달아 이만큼 같은 단어면 같은 말로 본다
MIN_SIM = 0.75           # 또는 문자열 유사도가 이 이상
WORD_SIM = 0.80


def norm(t):
    return PUNCT.sub("", t or "").strip()


def _sim(a, b):
    return difflib.SequenceMatcher(None, a, b).ratio()


def words_in(words, s, e, pad=0.10):
    return [w for w in words if w["end"] > s - pad and w["start"] < e + pad]


def common_run(a, b):
    """두 단어열에서 연달아 같은 최대 길이"""
    best = 0
    for i in range(len(a)):
        for j in range(len(b)):
            n = 0
            while (i + n < len(a) and j + n < len(b)
                   and _sim(a[i + n], b[j + n]) >= WORD_SIM):
                n += 1
            best = max(best, n)
    return best


def same_speech(wa, wb):
    """두 삭제 구간이 '같은 말' 인가"""
    ta = [norm(w["text"]) for w in wa if norm(w["text"])]
    tb = [norm(w["text"]) for w in wb if norm(w["text"])]
    if not ta or not tb:
        return False
    if common_run(ta, tb) >= MIN_RUN:
        return True
    return _sim("".join(ta), "".join(tb)) >= MIN_SIM


def _overlap(a, b):
    return max(0.0, min(a[1], b[1]) - max(a[0], b[0]))


DUP_OVERLAP = 0.8        # 이만큼 겹치면 같은 지시가 두 소스에서 온 것


def _clusters(ranges, info, words):
    """같은 말을 노리는 삭제들을 묶는다.

    묶기 전에 **중복 지시부터 걸러낸다.** 검출기 넷이 같은 구간을 각자
    찾아내는 일이 흔한데(3차시에서 23곳), 그건 충돌이 아니라 중복이다.
    같은 구간을 두 번 지우자는 것뿐이라 하나만 남기면 결과가 같다.
    이걸 충돌로 세면 진짜 충돌이 로그에 묻힌다.
    """
    items = [{"k": k, "s": r[0], "e": r[1], "d": d,
              "w": words_in(words, r[0], r[1])}
             for k, (r, d) in enumerate(zip(ranges, info))]
    items.sort(key=lambda x: x["s"])

    uniq = []
    for it in items:
        hit = None
        for u in uniq:
            ov = _overlap((it["s"], it["e"]), (u["s"], u["e"]))
            span = min(it["e"] - it["s"], u["e"] - u["s"])
            if span > 0 and ov / span >= DUP_OVERLAP:
                hit = u
                break
        if hit:
            hit["dups"] = hit.get("dups", 0) + 1
        else:
            uniq.append(it)
    items = uniq
    out, used = [], set()
    for i, a in enumerate(items):
        if a["k"] in used:
            continue
        group = [a]
        used.add(a["k"])
        for b in items[i + 1:]:
            if b["k"] in used:
                continue
            if b["s"] - group[-1]["e"] > CONFLICT_WINDOW:
                break
            if any(same_speech(g["w"], b["w"]) for g in group):
                group.append(b)
                used.add(b["k"])
        if len(group) > 1:
            out.append(group)
    return out


def resolve(segments, ranges, info, words, delete_overlap, verbose=True):
    """지운 뒤에 그 말이 하나도 안 남는 삭제만 되돌린다.

    같은 말을 노린 삭제가 여럿이라고 해서 다 충돌은 아니다. 테이크가
    셋이면 앞의 둘을 지우는 게 맞다. 실제로 위험한 건 **지우고 났더니
    그 말이 어디에도 안 남는** 경우뿐이다. 그래서 삭제를 실제로 적용해
    보고, 살아남은 발화 안에 같은 말이 있는지 확인한 뒤에 판단한다.
    """
    def kept_words(rngs):
        alive = []
        for seg in segments:
            span = seg[1] - seg[0]
            ov = sum(_overlap(seg, d) for d in rngs)
            if span > 0 and ov / span >= delete_overlap:
                continue
            alive.append(seg)
        return alive

    reverted = set()
    for g in _clusters(ranges, info, words):
        cur = [r for k, r in enumerate(ranges) if k not in reverted]
        alive = kept_words(cur)
        lo = min(x["s"] for x in g) - CONFLICT_WINDOW
        hi = max(x["e"] for x in g) + CONFLICT_WINDOW
        near = [w for w in words
                if lo <= w["start"] <= hi
                and any(_overlap((w["start"], w["end"]), s) > 0 for s in alive)]
        toks = [norm(w["text"]) for w in near if norm(w["text"])]
        # 이 무리가 노리는 말이 살아남은 발화 안에 있나?
        target = max(g, key=lambda x: len(x["w"]))
        want = [norm(w["text"]) for w in target["w"] if norm(w["text"])]
        # 몇 단어가 살아 있어야 '그 말이 남았다' 고 볼지. 테이크가 한두
        # 단어짜리면 MIN_RUN(3) 을 채울 방법이 없어서 무조건 충돌로
        # 잡혀버린다("여백을", "이렇게" 같은 것들). 테이크 길이에 맞춘다.
        need = max(1, min(MIN_RUN, len(want)))
        if want and toks and common_run(want, toks) >= need:
            continue                     # 한 테이크는 살아 있다 — 정상
        keep = max(g, key=lambda x: x["s"])   # 마지막 테이크를 살린다
        reverted.add(keep["k"])
        if verbose:
            txt = " ".join(w["text"] for w in keep["w"])[:46]
            print(f"    [충돌] {', '.join(f'{x['s']:.0f}초' for x in g)} 의 "
                  f"삭제 지시가 서로 반대로 판단했다 — 다 지우면 말이 "
                  f"사라진다. {keep['s']:.1f}초 테이크를 살린다 「{txt}」")
            print(f"           되돌린 지시: "
                  f"{str(keep['d'].get('reason', ''))[:76]}")

    out_r = [r for k, r in enumerate(ranges) if k not in reverted]
    out_i = [d for k, d in enumerate(info) if k not in reverted]
    rev = [info[k] for k in sorted(reverted)]
    if verbose and reverted:
        print(f"    삭제 지시 {len(reverted)}건을 되돌렸다")
    return out_r, out_i, rev


if __name__ == "__main__":
    print(__doc__)
    sys.exit(0)
