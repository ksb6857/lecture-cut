# -*- coding: utf-8 -*-
"""
전사본에 **그대로 보이는** 반복 발화(말 버벅임)를 찾는다.

`find_hidden_retakes.py` 는 Whisper 가 삼켜서 전사본에 흔적만 남은 반복을
찾는다. 이건 반대다 — 전사본에 두 번 다 적혀 있는데도 안 지워진 것들.
그동안 이 몫은 LLM 청크 분석에만 맡겨져 있었고, 2차시에서 사용자가 손수
지운 43곳이 그렇게 샜다.

찾는 모양 (말을 다시 시작하는 구조):
    [버린 말] ... [다시 시작한 말]
     ^^^^^^^          ^^^^^^^^^^
     같은 말로 시작한다
지울 곳은 '버린 말의 시작 ~ 다시 시작한 말의 시작' 이다. 뒤 테이크를 남긴다.

  실제 예 (2차시):
    92:19  조금씩 | 조금씩 변형을 주면서   -> 앞 '조금씩' 삭제
    72:52  인쇄했을 때 | 인쇄했을 때 접히고 -> 앞 것 삭제
    70:46  모든 삽화의 그림체는 소스 스타일의 기준 이미지를 따르고 …(32초)…
           다시, 모든 삽화의 그림체는 소스 스타일을 기준으로 …
                                          -> 앞 테이크 통째 삭제

한국어 어미가 흔들리는 것(스타일'의' vs 스타일'을')은 글자 유사도로 흡수한다.

사용:
    python src/find_repeat_retakes.py <words.json> <speech.json> <out.json>
    python src/find_repeat_retakes.py ... --eval <정답지.json>
"""
import difflib
import json
import re
import sys
from pathlib import Path

# [효과 검증 — 2차시, 사용자가 손수 지운 발화 44곳이 정답지]
# 파라미터를 훑어(near_max_extra 0/2/4 x near_min_words 1/2 x far 3/4/5 x
# long 6/8/12 x word_sim 0.67/0.8/1.0) 재현율·정밀도를 재봤다. 결과:
#
#   설정                        검출  재현      정밀   남긴말 먹는 양
#   extra<=0, n>=2               7   1/44     100%    0초     <- 자동 적용
#   extra<=1, n>=2              15   1/44      53%   12초
#   extra<=4, n>=2, far n>=3    59  15/44      44%   175초
#   far n>=3 까지 다 켠 최대치    102  14/44      37%   218초
#
# 재현율을 올리면 정밀도가 반드시 50% 아래로 떨어진다. 절반이 사람이
# 남긴 말을 먹는 제안이라는 뜻이라, 자동 적용하면 '발화를 자르지 않는다'는
# 이 프로젝트의 제1원칙을 정면으로 어긴다. 그래서 등급을 나눈다:
#   auto   — 두 테이크가 딱 붙은 되풀이. 오탐 0. 그대로 지운다.
#   review — 나머지. 지우지 않고 후보로만 내놓아 사람/LLM 이 판단한다.
#
# 정답지를 뜯어보면 재현율 천장 자체가 낮다: 44곳 중 전사본에 반복이
# 보이는 건 3분의 1쯤이고, 나머지는 '그리드는 칸이' 처럼 반복 없이 끊긴
# 조각이거나 사용자가 내용상 덜어낸 것이다. 반복 검출로 닿을 수 있는
# 한계가 거기까지다 — 나머지는 후보로 내놓고 사람이 보는 게 맞다.
PARAMS = {
    # 짧은 되풀이("조금씩 조금씩"): 뒤 테이크가 곧바로 붙어야 인정한다.
    # 아래 값은 '후보를 넉넉히 만드는' 쪽으로 잡았다. 자동 삭제 여부는
    # split_tiers 가 auto_* 로 다시 거른다.
    "near_max_extra": 4,     # 사이에 낀 군더더기 단어 허용치
    "near_min_words": 2,     # 한 단어 되풀이는 오탐이 너무 많다
    "near_max_sec": 6.0,     # 삭제 길이 상한
    # 자동 적용 등급의 조건 (위 표에서 오탐 0 인 지점)
    "auto_max_extra": 0,
    "auto_min_words": 2,
    "auto_max_sec": 6.0,
    # 긴 되돌이(한 문장을 통째로 다시 말함): 짧으면 우연이라 길이를 요구한다.
    "far_min_words": 3,      # 이만큼 연달아 같아야 한다
    "far_max_sec": 45.0,     # 삭제 길이 상한
    # 아주 길게 겹치면(문장 하나를 통째로 다시 말한 것) 버린 테이크도 그만큼
    # 길다. 2차시 70:46 은 18단어가 똑같이 반복되는데 버린 테이크가 80초라
    # far 상한 45초에 걸려 통째로 놓쳤다. 확신이 높은 만큼 상한을 늘린다.
    "long_min_words": 8,
    "long_max_sec": 150.0,
    # 한국어는 어미가 흔들린다(스타일'의' vs 스타일'을'). 0.80 이 가장
    # 나았다 — 0.67 은 '이미지가/이미지를' 같은 남남까지 붙여 오탐이 늘고,
    # 1.0(완전 일치)은 재현율이 떨어진다.
    "word_sim": 0.80,        # 두 단어를 같다고 볼 글자 유사도
    "lookahead_words": 300,  # 뒤로 이만큼까지만 짝을 찾는다
    "min_del_sec": 0.15,     # 이보다 짧으면 컷할 가치가 없다
}

PUNCT = re.compile(r"[^\w가-힣]+")


def norm(t):
    return PUNCT.sub("", t or "").strip()


def similar(a, b, thr):
    if a == b:
        return True
    if not a or not b:
        return False
    if abs(len(a) - len(b)) > 2:
        return False
    return difflib.SequenceMatcher(None, a, b).ratio() >= thr


def load_words(path):
    ws = [w for w in json.loads(Path(path).read_text(encoding="utf-8"))["words"]
          if w["type"] == "word"]
    ws.sort(key=lambda w: w["start"])
    out = []
    for w in ws:
        n = norm(w["text"])
        if n:
            out.append({"t": n, "raw": w["text"], "s": w["start"],
                        "e": w["end"], "i": w.get("i")})
    return out


def find(words, p=None):
    p = {**PARAMS, **(p or {})}
    N = len(words)
    thr = p["word_sim"]
    cands = []

    for i in range(N):
        jmax = min(N, i + p["lookahead_words"])
        best = None
        for j in range(i + 1, jmax):
            if not similar(words[i]["t"], words[j]["t"], thr):
                continue
            # 같은 말이 얼마나 이어지는지
            n = 0
            while (j + n < N and i + n < j
                   and similar(words[i + n]["t"], words[j + n]["t"], thr)):
                n += 1
            if n == 0:
                continue
            del_s, del_e = words[i]["s"], words[j]["s"]
            dur = del_e - del_s
            if dur < p["min_del_sec"]:
                continue
            extra = (j - i) - n          # 두 테이크 사이에 낀 군더더기
            near = (extra <= p["near_max_extra"]
                    and n >= p["near_min_words"] and dur <= p["near_max_sec"])
            far = (n >= p["far_min_words"] and dur <= p["far_max_sec"])
            long = (n >= p["long_min_words"] and dur <= p["long_max_sec"])
            if not (near or far or long):
                continue
            far = far or long
            # 점수는 near/far 를 따로 매긴다. far 는 두 테이크 사이가 벌어져
            # 있는 게 정상이므로(그 사이가 곧 버릴 테이크다) extra 를
            # 깎으면 안 된다. 예전에 깎았더니 32초짜리 되돌이가 점수 음수로
            # 밀려 그 안의 짧은 오탐에 자리를 뺏겼다.
            if near:
                score = 100 + n * 10 - extra * 2
            else:
                score = n * 10 - dur * 0.05
            if best is None or score > best["score"]:
                best = {"from_t": round(del_s, 3), "to_t": round(del_e, 3),
                        "n": n, "extra": extra, "kind": "near" if near else "far",
                        "score": score,
                        "dropped": " ".join(w["raw"] for w in words[i:j]),
                        "kept": " ".join(w["raw"] for w in words[j:j + n]),
                        "i0": i, "i1": j}
        if best:
            cands.append(best)

    # 겹치지 않게 좋은 것부터 고른다
    cands.sort(key=lambda c: (-c["score"], c["from_t"]))
    taken, used = [], []
    for c in cands:
        if any(not (c["to_t"] <= a or c["from_t"] >= b) for a, b in used):
            continue
        used.append((c["from_t"], c["to_t"]))
        taken.append(c)
    taken.sort(key=lambda c: c["from_t"])
    return taken


def mmss(t):
    return f"{int(t//60):02d}:{t % 60:05.2f}"


def evaluate(found, truth_path, quiet=False):
    """정답지와 대조한다.

    정답지(`diff_user_cuts.py --json`)에는 두 가지가 들어 있다:
      removed — 사용자가 지운 구간 (재현율의 분모)
      kept    — 사용자가 남긴 구간 (오탐의 기준)
    오탐을 'removed 에 안 겹치는 것' 으로 세면 안 된다. 자동편집이 이미
    지워둔 자리는 removed 에도 kept 에도 없어서, 거길 또 지우자고 해도
    아무 손해가 없는데 오탐으로 잡혀버린다.
    """
    T = json.loads(Path(truth_path).read_text(encoding="utf-8"))
    real = [t for t in T["removed"] if t.get("dur", 0) >= 0.5]
    kept = [(k[0], k[1]) for k in T.get("kept", [])]

    def ov(a, b):
        return max(0.0, min(a[1], b[1]) - max(a[0], b[0]))

    hit = 0
    missed = []
    for t in real:
        span = (t["from_t"], t["to_t"])
        cov = sum(ov(span, (f["from_t"], f["to_t"])) for f in found)
        if cov / max(span[1] - span[0], 1e-9) >= 0.5:
            hit += 1
        else:
            missed.append(t)

    bad, bad_sec = [], 0.0
    for f in found:
        span = (f["from_t"], f["to_t"])
        keep_ov = sum(ov(span, k) for k in kept)
        if keep_ov >= 0.5:          # 사람이 남긴 말을 0.5초 이상 먹으면 오탐
            bad.append(f)
            bad_sec += keep_ov

    prec = 100 * (len(found) - len(bad)) / max(len(found), 1)
    if not quiet:
        print(f"\n[효과 검증]  정답지 {len(real)}곳 = 사용자가 손수 지운 발화")
        print(f"  검출     {len(found)}곳")
        print(f"  재현율   {hit}/{len(real)} = {100*hit/max(len(real),1):.0f}%")
        print(f"  오탐     {len(bad)}곳 — 사용자가 남긴 말을 "
              f"{bad_sec:.1f}초 먹는다")
        print(f"  정밀도   {len(found)-len(bad)}/{len(found)} = {prec:.0f}%")
    return {"truth": len(real), "found": len(found), "hit": hit,
            "recall": round(100 * hit / max(len(real), 1)),
            "false": len(bad), "false_sec": round(bad_sec, 1),
            "prec": round(prec), "missed": missed, "bad": bad}


def split_tiers(found, p=None):
    """자동으로 지울 것과, 사람이 볼 후보를 가른다."""
    p = {**PARAMS, **(p or {})}
    auto, review = [], []
    for f in found:
        # near 로 한정한다. far 는 extra 가 0 이어도 두 테이크가 멀리
        # 떨어져 있을 수 있다 — 2차시 24:50 은 5단어가 13초에 걸쳐 있었고
        # (단어 사이가 그만큼 비어 있다는 뜻) 사람이 남긴 말이었다.
        ok = (f["kind"] == "near"
              and f["extra"] <= p["auto_max_extra"]
              and f["n"] >= p["auto_min_words"]
              and (f["to_t"] - f["from_t"]) <= p["auto_max_sec"])
        (auto if ok else review).append(f)
    return auto, review


def run(words_path, out_path, eval_path=None, params=None, quiet=False,
        review_path=None):
    words = load_words(words_path)
    found = find(words, params)
    auto, review = split_tiers(found, params)

    def dump(items):
        for f in items:
            print(f"  {mmss(f['from_t'])}~{mmss(f['to_t'])} "
                  f"{f['to_t']-f['from_t']:5.2f}초 [{f['kind']} n={f['n']} "
                  f"extra={f['extra']}]")
            print(f"      버림: 「{f['dropped'][:70]}」")
            print(f"      남김: 「{f['kept'][:50]}…」")

    if not quiet:
        print(f"[자동 삭제] {len(auto)}곳, "
              f"{sum(f['to_t']-f['from_t'] for f in auto):.1f}초 "
              f"— 두 테이크가 딱 붙은 되풀이")
        dump(auto)
        print(f"\n[사람이 볼 후보] {len(review)}곳, "
              f"{sum(f['to_t']-f['from_t'] for f in review):.1f}초 "
              f"— 지우지 않는다. 절반쯤은 멀쩡한 말이다")
        dump(review)

    if out_path:
        Path(out_path).write_text(json.dumps(
            {"deletions": [{"from_t": f["from_t"], "to_t": f["to_t"],
                            "kind": "repeat", "n": f["n"],
                            "text": f["dropped"][:120]} for f in auto]},
            ensure_ascii=False, indent=1), encoding="utf-8")
        if not quiet:
            print(f"\n자동 삭제 저장: {out_path}")
    if review_path:
        Path(review_path).write_text(json.dumps(
            {"candidates": [{"from_t": f["from_t"], "to_t": f["to_t"],
                             "n": f["n"], "extra": f["extra"],
                             "dropped": f["dropped"][:200],
                             "kept": f["kept"][:120]} for f in review]},
            ensure_ascii=False, indent=1), encoding="utf-8")
        if not quiet:
            print(f"검토 후보 저장: {review_path}")

    stats = evaluate(found, eval_path, quiet) if eval_path else None
    if eval_path and not quiet:
        a = evaluate(auto, eval_path, quiet=True)
        print(f"\n  이 중 자동 삭제 등급만:  검출 {a['found']}곳  "
              f"정밀도 {a['prec']}%  남긴 말 먹는 양 {a['false_sec']:.1f}초")
    return found, stats


if __name__ == "__main__":
    a = [x for x in sys.argv[1:] if not x.startswith("--")]

    def opt(name):
        if name in sys.argv:
            k = sys.argv.index(name)
            return sys.argv[k + 1] if k + 1 < len(sys.argv) else None
        return None

    run(a[0], a[1] if len(a) > 1 else None, opt("--eval"),
        review_path=opt("--review"))
