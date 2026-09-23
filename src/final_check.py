# -*- coding: utf-8 -*-
"""러프컷을 내놓기 전 검산. 기준을 넘으면 0 이 아닌 값으로 끝난다.

사람 눈으로 대본만 읽으면 못 잡는 것들이다. 2026-09-20·23 에 두 번 지적받았다.
대본(자막)은 깨끗한데 소리는 씹혀 있었고, 쉼 규칙은 통째로 빠져 있었다.

    1. 컷 지점 세기        소리 위(-45dB 초과) 0곳
    2. 쉼                 문장 중간이 0곳이면 판정이 안 먹은 것. 중간 쉼 중앙값 0.30초 이하
    3. 삭제 잔여           지운다고 한 말이 편집본에 남은 시간 0.5초 이하
    4. 연달아 같은 낱말    0건

사용:
    python final_check.py <keep.json> <words.json> <speech.json> <wav>
        [--offset 초] [--skip 시작 끝]... [--deletions 판정.json]...
        [--takes persegment.json] [--levels 캐시.npy] [--report 보고서.md]

--takes 에 덩어리 전사를 주면 '연달아 같은 문장'(같은 문장 두 테이크가 모두 남음)도 본다.

keep.json 의 시각이 wav 시각과 다르면(앞에 인트로를 붙였을 때) --offset 으로
그 차이를 준다. --skip 은 검사에서 뺄 구간(keep 시각). 사람이 손본 구간처럼
정답으로 두는 곳에 쓴다.
"""
import json
import re
import statistics as st
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import audio_levels as L  # noqa: E402
from cut_planner import ends_sentence  # noqa: E402

LIMITS = {"on_sound": 0, "mid_median": 0.30, "residue": 0.5, "dups": 0}


def parse(argv):
    pos, opts = [], {"--skip": [], "--deletions": []}
    k = 0
    while k < len(argv):
        a = argv[k]
        if a == "--skip":
            opts["--skip"].append((float(argv[k + 1]), float(argv[k + 2])))
            k += 3
        elif a == "--deletions":
            opts["--deletions"].append(argv[k + 1])
            k += 2
        elif a.startswith("--"):
            opts[a] = argv[k + 1]
            k += 2
        else:
            pos.append(a)
            k += 1
    return pos, opts


def norm(t):
    return re.sub(r"[\s.,?!~…·'\"]", "", t or "")


def check(keep, words, speech, db, offset=0.0, skip=(), deletions=(), takes=None, reviewed=None):
    """reviewed: {편집 대상 시각: 까닭} — 사람이 파형·덩어리 전사로 확인한 오탐.
    위스퍼가 낱말 시작을 앞 침묵 속으로 늘려 잡으면, 잘려 나간 낱말이 남은 것처럼
    보여 '연달아 같은 낱말' 로 걸린다. 확인한 것은 까닭을 적어 넘긴다."""
    blocks = [list(b) for b in keep["keep_ranges"]]
    ws = sorted((w for w in words if w.get("type", "word") == "word"),
                key=lambda w: w["start"])
    sp = [tuple(s) for s in speech["speech"]]
    dur = len(db) * L.HOP

    def skipped(t):
        return any(a <= t <= b for a, b in skip)

    # 1. 컷 지점 세기
    points = []
    for i, (a, b) in enumerate(blocks):
        joined_prev = i > 0 and abs(blocks[i - 1][1] - a) < 0.005
        joined_next = i + 1 < len(blocks) and abs(blocks[i + 1][0] - b) < 0.005
        for kind, t, joined in (("시작", a, joined_prev), ("끝", b, joined_next)):
            w = t - offset
            if joined or skipped(t) or not (0.05 < w < dur - 0.05):
                continue
            points.append((kind, t, L.level_at(db, w)))
    on = [p for p in points if p[2] > L.ON_SOUND]
    edge = [p for p in points if L.SILENT < p[2] <= L.ON_SOUND]

    # 2. 쉼 (이음매마다 앞 블록 꼬리 + 뒤 블록 머리)
    def speech_in(a, b):
        return [(max(a, x), min(b, y)) for x, y in sp if y > a and x < b]
    mids, ends, tight = [], [], []
    for (a0, b0), (a1, b1) in zip(blocks, blocks[1:]):
        if skipped(b0) or skipped(a1) or abs(a1 - b0) < 0.005:
            continue
        s0 = speech_in(a0 - offset, b0 - offset)
        s1 = speech_in(a1 - offset, b1 - offset)
        if not s0 or not s1:
            continue
        gap = (b0 - offset - s0[-1][1]) + (s1[0][0] - (a1 - offset))
        prev = [w for w in ws if w["end"] <= b0 - offset + 0.05]
        is_end = ends_sentence(prev[-1]["text"]) if prev else True
        (ends if is_end else mids).append(gap)
        if gap < 0.08:
            tight.append((round(b0, 2), round(gap, 3)))

    # 3. 삭제 잔여 (지운다고 한 말소리가 남은 시간)
    wb = [(a - offset, b - offset) for a, b in blocks]
    residue, left = 0.0, []
    for d in deletions:
        if d.get("caption_only"):
            continue
        a, b = float(d["from_t"]), float(d["to_t"])
        if skipped(a + offset) and skipped(b + offset):
            continue
        ov = 0.0
        for x, y in speech_in(a, b):
            for p, q in wb:
                ov += max(0.0, min(y, q) - max(x, p))
        if ov > 0.05:
            left.append((round(a + offset, 2), round(ov, 2), str(d.get("reason", ""))[:40]))
        residue += ov

    # 4. 편집본 대본에서 연달아 같은 낱말 (낱말이 블록과 겹치면 남은 것으로 본다)
    #    자막에서만 빼는 지시(위스퍼가 지어내거나 쪼갠 낱말)에 든 낱말은 없는 것으로 본다
    cap = [(float(d["from_t"]), float(d["to_t"])) for d in deletions if d.get("caption_only")]
    kept = []
    for w in ws:
        s, e = w["start"] + offset, w["end"] + offset
        if skipped(s):
            continue
        m = (w["start"] + w["end"]) / 2
        if any(a - 0.01 <= m <= b + 0.01 for a, b in cap):
            continue
        # 낱말의 **소리 나는 부분**만 본다. 위스퍼는 앞이 조용하면 낱말 시작을
        # 침묵 속으로 늘려 잡아서, 시각만 보면 잘려 나간 낱말이 남은 것처럼 보인다.
        voiced = speech_in(w["start"], w["end"])
        vt = sum(y - x for x, y in voiced)
        if vt < 0.02:
            continue                      # 들리지 않는 낱말 (지어낸 말)
        ov = sum(max(0.0, min(y + offset, q) - max(x + offset, p))
                 for x, y in voiced for p, q in blocks)
        if ov > 0.5 * vt:
            kept.append(w)
    dups = [(round(x["start"] + offset, 2), x["text"])
            for x, y in zip(kept, kept[1:])
            if len(norm(x["text"])) >= 2 and norm(x["text"]) == norm(y["text"])]
    ok = []
    if reviewed:
        ok = [(t, x, reviewed[k]) for t, x in dups for k in reviewed if abs(k - t) < 0.3]
        dups = [(t, x) for t, x in dups if not any(abs(k - t) < 0.3 for k in reviewed)]

    # 5. 연달아 같은 문장 — 같은 문장의 두 테이크가 모두 남은 것.
    #    낱말 검사로는 못 잡는다. 덩어리 전사(persegment)로 이웃 덩어리를 비교한다.
    #    2026-09-23 11차시 10077·10086초 '우선 데이터가 기록될 구글 시트를…' 이 둘 다 남아 있었다
    reps = []
    if takes:
        from difflib import SequenceMatcher

        def canon(s):
            # 위스퍼는 같은 말을 'AI' 로도 '에이아이' 로도 적는다. 맞춰 놓고 비교한다
            s = (s or "").lower()
            for a, b in (("에이피아이", "api"), ("에이아이", "ai"), ("제미나이", "gemini"),
                         ("재미나이", "gemini"), ("잼스", "gems"), ("젬스", "gems")):
                s = s.replace(a, b)
            return norm(s)

        live = []
        for t in takes:
            a, b = t["start"], t["end"]
            txt = canon(t.get("text", ""))
            if len(txt) < 2 or skipped(a + offset):
                continue
            ov = sum(max(0.0, min(b, q) - max(a, p)) for p, q in wb)
            # 덩어리를 통째로 남긴 것끼리만 글자로 비교한다. 일부만 남긴 덩어리는
            # 어느 낱말이 남았는지 글자로는 모른다(앞 '화면을 살,' 을 잘라 낸 덩어리를
            # 통째로 읽으면 되풀이로 보인다)
            if ov > 0.9 * (b - a):
                live.append((a, b, txt, t["text"]))
        for (a0, b0, x, raw0), (a1, b1, y, raw1) in zip(live, live[1:]):
            n = min(len(x), len(y), 14)
            pre = 0
            while pre < min(len(x), len(y)) and x[pre] == y[pre]:
                pre += 1
            same = n >= 5 and SequenceMatcher(None, x[:n], y[:n]).ratio() >= 0.7
            # 헛시작: 짧은 덩어리가 다음 덩어리 첫머리와 같다 ('요금 있다' → '요금이 청구될…')
            false_start = (b0 - a0) <= 1.6 and pre >= 2 and len(x) <= 12
            if same or false_start or (pre >= 6):
                reps.append((round(a0 + offset, 2), raw0[:24], raw1[:24]))
        # 덩어리 안 되풀이: 'X X' 가 바로 이어진다 ('웹 앱 사본을 만들어서 웹 앱 사본을 만들어서')
        for a0, b0, x, raw0 in live:
            for L_ in range(len(x) // 2, 3, -1):
                if any(x[i:i + L_] == x[i + L_:i + 2 * L_] for i in range(0, len(x) - 2 * L_ + 1)):
                    reps.append((round(a0 + offset, 2), raw0[:24], "(덩어리 안 되풀이)"))
                    break

    return {
        "points": len(points), "on_sound": on, "edge": edge,
        "mid": mids, "end": ends, "tight": tight,
        "residue": residue, "left": left, "dups": dups, "reps": reps, "reviewed": ok,
    }


def verdict(r):
    bad = []
    if len(r["on_sound"]) > LIMITS["on_sound"]:
        bad.append(f"컷 지점 {len(r['on_sound'])}곳이 소리 위")
    if len(r["mid"]) + len(r["end"]) >= 20 and not r["mid"]:
        bad.append("문장 중간 쉼 0곳 — 문장 끝 판정이 안 먹었다")
    if r["mid"] and st.median(r["mid"]) > LIMITS["mid_median"]:
        bad.append(f"문장 중간 쉼 중앙값 {st.median(r['mid']):.2f}초")
    if r["residue"] > LIMITS["residue"]:
        bad.append(f"삭제 잔여 {r['residue']:.1f}초")
    if len(r["dups"]) > LIMITS["dups"]:
        bad.append(f"연달아 같은 낱말 {len(r['dups'])}건")
    if r.get("reps"):
        bad.append(f"연달아 같은 문장 {len(r['reps'])}건")
    return bad


def report(r):
    f = lambda xs: (f"{len(xs)}곳 · 중앙 {st.median(xs):.2f} · 최소 {min(xs):.2f} · "
                    f"최대 {max(xs):.2f}초") if xs else "0곳"
    lines = [
        "| 검산 | 결과 | 기준 |", "|---|---|---|",
        f"| 컷 지점 소리 위 (>-45dB) | {len(r['on_sound'])} / {r['points']} | 0 |",
        f"| 애매 (-50~-45dB) | {len(r['edge'])} | 참고 |",
        f"| 문장 중간 쉼 | {f(r['mid'])} | 중앙 0.30 이하 |",
        f"| 문장 끝 쉼 | {f(r['end'])} | 참고 |",
        f"| 0.08초보다 붙은 이음매 | {len(r['tight'])} | 참고 |",
        f"| 삭제 잔여 | {r['residue']:.1f}초 ({len(r['left'])}건) | 0.5초 이하 |",
        f"| 연달아 같은 낱말 | {len(r['dups'])} (확인한 오탐 {len(r.get('reviewed', []))}) | 0 |",
        f"| 연달아 같은 문장 (두 테이크가 다 남음) | {len(r.get('reps', []))} | 0 |",
    ]
    if r.get("reps"):
        lines += ["", "같은 문장: " + ", ".join(f"{t}s 「{a}」≒「{b}」" for t, a, b in r["reps"][:20])]
    if r["on_sound"]:
        lines += ["", "소리 위 컷: " + ", ".join(
            f"{k} {t:.2f}s({v:.0f}dB)" for k, t, v in r["on_sound"][:30])]
    if r["left"]:
        lines += ["", "삭제 잔여: " + ", ".join(f"{t}s {o}초 {why}" for t, o, why in r["left"][:30])]
    if r["dups"]:
        lines += ["", "같은 낱말: " + ", ".join(f"{t}s {x}" for t, x in r["dups"][:30])]
    if r.get("reviewed"):
        lines += ["", "확인한 오탐:"] + [f"- {t}s {x} — {why}" for t, x, why in r["reviewed"]]
    return "\n".join(lines)


def main(argv):
    pos, o = parse(argv)
    keep = json.loads(Path(pos[0]).read_text(encoding="utf-8"))
    words = json.loads(Path(pos[1]).read_text(encoding="utf-8"))["words"]
    speech = json.loads(Path(pos[2]).read_text(encoding="utf-8"))
    db = L.compute(pos[3], o.get("--levels"))
    dels = []
    for p in o["--deletions"]:
        dels += json.loads(Path(p).read_text(encoding="utf-8")).get("deletions", [])
    takes = None
    if o.get("--takes"):
        takes = json.loads(Path(o["--takes"]).read_text(encoding="utf-8"))["takes"]
    r = check(keep, words, speech, db, float(o.get("--offset", 0)),
              o["--skip"], dels, takes)
    text = report(r)
    bad = verdict(r)
    text += "\n\n" + ("**통과**" if not bad else "**멈춤** — " + " / ".join(bad))
    print(text)
    if o.get("--report"):
        Path(o["--report"]).write_text(text + "\n", encoding="utf-8")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
