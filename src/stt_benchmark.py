# -*- coding: utf-8 -*-
"""전사 여러 벌을 같은 녹음의 파형과 이미 아는 판정으로 비교한다. 정답 대본 없이도 잰다.

컷 편집에서 전사가 틀리면 생기는 일 기준으로 본다. 단어 오류율(WER)은 정답 대본이 있어야 해서 재지 않는다.

  말 빠짐      실제로 소리가 난 발화 구간(-45dB 넘는 곳이 0.3초 이상)에 낱말이 하나도 없는 것
  지어낸 말    낱말 구간 전체가 진짜 무음(-50dB 아래)인 것. 없는 말이거나 1초 넘게 밀린 말
  시각         쉼 뒤 첫 낱말의 시작, 쉼 앞 끝 낱말의 끝이 실제 소리 시작·끝(-45dB 넘나드는 곳)과 몇 초 어긋나나
  되풀이 보존  판정에서 '재발화'로 지운 구간 안에 전사가 낱말을 남겼나. 남아야 판정이 그 구간을 본다
  덮지 않은 소리 발화 구간 안에서 -45dB 넘는 소리가 어느 낱말(앞뒤 0.08초)에도 안 걸리는 곳(fill_uncovered 와 같은 기준)
  추임새       음·어·아 같은 낱말 수(말 그대로 적는지)
  용어         --terms 로 준 표기 묶음마다 어떤 표기가 몇 번 나왔나
  문장부호     낱말 끝에 . ? ! 가 붙은 비율(cut_planner 의 문장 끝 판정에 쓰인다)

사용: python stt_benchmark.py <words.json> <words.json> [...] --speech <speech.json> --wav <wav>
        [--levels 세기캐시.npy] [--deletions 판정.json] [--terms 용어.json] [--report 보고서.md]
  words.json 을 여러 벌 주면 열이 그만큼 생긴다. 이름은 파일의 source_stt
  용어.json: {"제미나이": ["제미나이", "Gemini", "재미나이"], ...}  첫 표기를 바른 표기로 본다
"""
import json
import re
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import audio_levels as L  # noqa: E402

FILLERS = {"음", "어", "아", "으음", "엄", "흠", "음음", "어어", "에"}


def load_words(p):
    d = json.loads(Path(p).read_text(encoding="utf-8"))
    ws = [w for w in d["words"] if w.get("type", "word") == "word" and w["text"].strip()]
    return d.get("source_stt", Path(p).stem), ws


def span_db(db, a, b):
    i0, i1 = max(0, int(a / L.HOP)), min(len(db), int(b / L.HOP) + 1)
    return db[i0:i1] if i1 > i0 else np.array([-120.0])


def onset_near(db, t, reach=1.0, rising=True):
    """t 근처에서 -45dB 를 넘나드는 곳(올라가는 곳/내려가는 곳) 중 가장 가까운 시각."""
    i0, i1 = max(1, int((t - reach) / L.HOP)), min(len(db) - 1, int((t + reach) / L.HOP))
    seg = db[i0 - 1:i1 + 1] > L.ON_SOUND
    idx = np.where(seg[1:] & ~seg[:-1])[0] if rising else np.where(~seg[1:] & seg[:-1])[0]
    if not len(idx):
        return None
    ts = (idx + i0) * L.HOP
    return float(ts[np.argmin(np.abs(ts - t))])


def measure(name, words, speech, db, deletions, terms):
    r = {"name": name, "words": len(words)}
    # 말 빠짐
    miss, miss_sec, loud = 0, 0.0, 0
    k = 0
    ws = sorted(words, key=lambda w: w["start"])
    for a, b in speech:
        s = span_db(db, a, b)
        if (s > L.ON_SOUND).sum() * L.HOP < 0.3:
            continue
        loud += 1
        while k < len(ws) and ws[k]["end"] < a:
            k += 1
        j, hit = k, False
        while j < len(ws) and ws[j]["start"] <= b:
            if ws[j]["end"] > a:
                hit = True
                break
            j += 1
        if not hit:
            miss += 1
            miss_sec += b - a
    r["발화구간"] = loud
    r["말빠짐_구간"] = miss
    r["말빠짐_초"] = round(miss_sec, 1)
    # 지어낸 말
    fake = [w for w in words if w["end"] - w["start"] >= 0.1 and span_db(db, w["start"], w["end"]).max() < L.SILENT]
    r["무음속_낱말"] = len(fake)
    r["무음속_예"] = [f"{w['start']:.1f} {w['text']}" for w in fake[:8]]
    # 시각
    on_err, off_err = [], []
    for k, w in enumerate(ws):
        prev_end = ws[k - 1]["end"] if k else -9
        next_start = ws[k + 1]["start"] if k + 1 < len(ws) else 1e9
        if w["start"] - prev_end >= 0.25:
            o = onset_near(db, w["start"], rising=True)
            if o is not None:
                on_err.append(abs(w["start"] - o))
        if next_start - w["end"] >= 0.25:
            o = onset_near(db, w["end"], rising=False)
            if o is not None:
                off_err.append(abs(w["end"] - o))

    def q(v, p):
        return round(float(np.percentile(v, p)), 3) if v else None
    r["시작오차_중앙"], r["시작오차_90%"] = q(on_err, 50), q(on_err, 90)
    r["끝오차_중앙"], r["끝오차_90%"] = q(off_err, 50), q(off_err, 90)
    r["시작_0.1초안"] = round(sum(e <= 0.1 for e in on_err) / max(1, len(on_err)), 3)
    # 되풀이 보존
    rets = [d for d in deletions if d.get("kind") == "retake"]
    kept = 0
    for d in rets:
        a, b = float(d["from_t"]), float(d["to_t"])
        if any(a <= (w["start"] + w["end"]) / 2 <= b for w in words):
            kept += 1
    r["재발화구간"] = len(rets)
    r["재발화_낱말남음"] = kept
    from fill_uncovered import uncovered
    unc = uncovered(words, speech, db)
    r["덮지않은소리_곳"] = len(unc)
    r["덮지않은소리_초"] = round(sum(c for *_, c in unc), 1)
    # 추임새·문장부호
    bare = [re.sub(r"[.,?!…~]+$", "", w["text"]) for w in words]
    r["추임새"] = sum(1 for t in bare if t in FILLERS)
    r["문장부호_비율"] = round(sum(1 for w in words if re.search(r"[.?!]$", w["text"])) / max(1, len(words)), 3)
    # 용어
    txt = " ".join(w["text"] for w in words)
    r["용어"] = {k: {v: len(re.findall(re.escape(v), txt)) for v in vs} for k, vs in terms.items()}
    return r


def report(rs):
    rows = [("낱말 수", "words"), ("소리 난 발화 구간", "발화구간"), ("낱말 없는 발화 구간", "말빠짐_구간"),
            ("그 길이(초)", "말빠짐_초"), ("무음 속 낱말(지어냄·크게 밀림)", "무음속_낱말"),
            ("쉼 뒤 첫 낱말 시작 오차 중앙(초)", "시작오차_중앙"), ("같은 값 90%", "시작오차_90%"),
            ("0.1초 안에 맞은 비율", "시작_0.1초안"), ("쉼 앞 끝 낱말 끝 오차 중앙(초)", "끝오차_중앙"),
            ("같은 값 90%", "끝오차_90%"), ("재발화로 지운 구간", "재발화구간"),
            ("그 안에 낱말을 남긴 구간", "재발화_낱말남음"), ("낱말이 덮지 않은 소리(곳)", "덮지않은소리_곳"),
            ("그 소리(초)", "덮지않은소리_초"), ("추임새 낱말", "추임새"), ("문장부호 비율", "문장부호_비율")]
    out = ["| 항목 | " + " | ".join(r["name"] for r in rs) + " |", "|---" * (len(rs) + 1) + "|"]
    for lab, k in rows:
        out.append(f"| {lab} | " + " | ".join(str(r.get(k)) for r in rs) + " |")
    out += ["", "용어 표기 (첫 표기가 바른 것)", ""]
    for term in rs[0]["용어"]:
        out.append(f"- {term}: " + " · ".join(f"{r['name']} {r['용어'][term]}" for r in rs))
    out.append("")
    for r in rs:
        out.append(f"무음 속 낱말 예 ({r['name']}): {', '.join(r['무음속_예'])}")
    return "\n".join(out)


def main(argv):
    pos, opt, k = [], {}, 0
    while k < len(argv):
        if argv[k].startswith("--"):
            opt[argv[k]] = argv[k + 1]
            k += 2
        else:
            pos.append(argv[k])
            k += 1
    speech = json.loads(Path(opt["--speech"]).read_text(encoding="utf-8"))["speech"]
    db = L.compute(opt["--wav"], opt.get("--levels"))
    dels = json.loads(Path(opt["--deletions"]).read_text(encoding="utf-8"))["deletions"] if "--deletions" in opt else []
    terms = json.loads(Path(opt["--terms"]).read_text(encoding="utf-8")) if "--terms" in opt else {}
    rs = []
    for p in pos:
        name, ws = load_words(p)
        rs.append(measure(name, ws, speech, db, dels, terms))
    text = report(rs)
    print(text)
    if "--report" in opt:
        Path(opt["--report"]).write_text(text + "\n", encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv[1:])
