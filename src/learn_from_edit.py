# -*- coding: utf-8 -*-
"""
사람이 손본 캡컷 드래프트와 자동 편집본을 비교해 편집 규칙을 수치로 뽑는다.

- 두 편집본의 '남긴 구간'을 소스 시간축 위에 놓고 겹쳐본다
- 컷 지점마다 실제로 남은 무음(tail+lead)을 VAD 기준으로 계산
- 그 지점이 문장 끝인지 문장 중간인지 전사본 문장부호로 분류
  → 사람이 문장 안/문장 사이에 각각 몇 초를 남기는지가 나온다
- 사람만 잘라낸 구간의 대사를 뽑아 재발화 판단 사례를 확보
- 자막 길이/시간 분포 비교

사용: python src/learn_from_edit.py <사람draft> <자동draft> <speech.json> <words.json>
"""
import bisect
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from draft_root import DRAFTS  # noqa: E402
US = 1_000_000


def draft_content_path(name) -> Path:
    """사용자 편집이 실제로 들어 있는 draft_content.json 을 찾는다.

    캡컷은 드래프트를 처음 열 때 내부 형식으로 변환하면서 같은 이름의
    하위 폴더에 사본을 만들고, 그 뒤로는 **하위 사본에만** 저장한다.
    바깥 파일은 우리가 만든 그대로 멈춰 있다. 그걸 읽으면 사용자가 손본
    내용이 하나도 안 보이는 채로 '학습' 이 돌아간다 — 조용히 틀린다.
    그래서 가장 최근에 저장된 것을 고른다.
    """
    root = Path(name) if Path(name).is_dir() else DRAFTS / name
    cands = list(root.rglob("draft_content.json"))
    if not cands:
        raise SystemExit(f"draft_content.json 이 없습니다: {root}")
    # 수정 시각으로 고르면 안 된다. 수리 도구들이 사본을 전부 건드리면
    # 바깥 파일이 최신이 되어버려 사용자 편집이 안 보인다(실제로 겪었다).
    # 캡컷이 만든 하위 사본이 깊이 있으므로 '가장 깊은 것' 을 고르고,
    # 같은 깊이면 최근 것을 고른다.
    return max(cands, key=lambda p: (len(p.relative_to(root).parts),
                                     p.stat().st_mtime))


def load_draft(name):
    d = json.loads(draft_content_path(name).read_text(encoding="utf-8"))
    vids, texts = [], []
    for tr in d.get("tracks", []):
        for s in tr.get("segments", []):
            t = s["target_timerange"]
            if tr["type"] == "video":
                src = s.get("source_timerange") or {"start": 0, "duration": 0}
                vids.append({
                    "t0": t["start"] / US, "t1": (t["start"] + t["duration"]) / US,
                    "s0": src["start"] / US,
                    "s1": (src["start"] + src["duration"]) / US,
                })
            elif tr["type"] == "text":
                mid = s.get("material_id")
                vids and None
                texts.append({
                    "t0": t["start"] / US,
                    "t1": (t["start"] + t["duration"]) / US,
                    "mid": mid,
                })
    # 자막 본문
    bank = {}
    for m in d.get("materials", {}).get("texts", []):
        try:
            bank[m["id"]] = json.loads(m["content"])["text"]
        except Exception:
            bank[m["id"]] = m.get("content", "")
    for t in texts:
        t["text"] = bank.get(t["mid"], "")
    vids.sort(key=lambda x: x["t0"])
    texts.sort(key=lambda x: x["t0"])
    return vids, texts


def analyze(human_name, auto_name, speech_path, words_path):
    hv, ht = load_draft(human_name)
    av, at = load_draft(auto_name)
    speech = json.loads(Path(speech_path).read_text(encoding="utf-8"))["speech"]
    words = [w for w in json.loads(Path(words_path).read_text(
        encoding="utf-8"))["words"] if w["type"] == "word"]

    sp_starts = [s for s, _ in speech]
    sp_ends = [e for _, e in speech]
    w_starts = [w["start"] for w in words]

    def prev_speech_end(t):
        i = bisect.bisect_left(sp_ends, t) - 1
        return sp_ends[i] if i >= 0 else None

    def next_speech_start(t):
        i = bisect.bisect_right(sp_starts, t)
        return sp_starts[i] if i < len(sp_starts) else None

    def word_before(t):
        i = bisect.bisect_left(w_starts, t) - 1
        return words[i] if i >= 0 else None

    def residuals(vids, upto_src=None):
        """컷 지점마다 (남은 무음, 문장끝여부, 소스시각, 직전 대사)"""
        out = []
        for a, b in zip(vids, vids[1:]):
            if abs(b["s0"] - a["s1"]) < 0.02:      # 소스가 이어지면 컷 아님
                continue
            if upto_src and a["s1"] > upto_src:
                break
            pe = prev_speech_end(a["s1"])
            ns = next_speech_start(b["s0"])
            if pe is None or ns is None:
                continue
            tail = a["s1"] - pe
            lead = ns - b["s0"]
            if tail < -0.05 or lead < -0.05:
                continue
            w = word_before(a["s1"])
            txt = w["text"] if w else ""
            ends = txt.rstrip()[-1:] in ".?!"
            out.append({
                "src": a["s1"], "tail": tail, "lead": lead,
                "residual": tail + lead, "sentence_end": ends, "word": txt,
            })
        return out

    # 사람이 손댄 구간 찾기: 소스 커버리지가 갈라지는 지점까지
    def covered(vids):
        return [(v["s0"], v["s1"]) for v in vids]

    hc, ac = covered(hv), covered(av)
    edit_end = 0.0
    for i in range(min(len(hc), len(ac))):
        if abs(hc[i][0] - ac[i][0]) > 0.05 or abs(hc[i][1] - ac[i][1]) > 0.05:
            edit_end = max(edit_end, hc[i][1], ac[i][1])
    # 뒤에서부터 동일해지는 지점 확인
    print(f"사람 편집본 {len(hv)}세그먼트 / 자동 {len(av)}세그먼트")
    print(f"손댄 구간(소스 기준): 0 ~ {edit_end:.1f}초\n")

    hr = residuals(hv, edit_end + 5)
    ar = residuals(av, edit_end + 5)

    def summarize(rs, label):
        import statistics as st
        if not rs:
            print(f"  {label}: 컷 없음")
            return
        mid = [r["residual"] for r in rs if not r["sentence_end"]]
        end = [r["residual"] for r in rs if r["sentence_end"]]
        print(f"  {label}  컷 {len(rs)}곳")
        if mid:
            print(f"    문장 중간 : n={len(mid):2d}  중앙값 {st.median(mid):.2f}초  "
                  f"범위 {min(mid):.2f}~{max(mid):.2f}")
        if end:
            print(f"    문장 끝   : n={len(end):2d}  중앙값 {st.median(end):.2f}초  "
                  f"범위 {min(end):.2f}~{max(end):.2f}")

    print("[컷 지점에 남긴 무음] (손댄 구간 안에서)")
    summarize(hr, "사람")
    summarize(ar, "자동")
    print()

    print("[사람이 남긴 무음 상세]")
    for r in hr:
        kind = "문장끝" if r["sentence_end"] else "문장중간"
        print(f"  {int(r['src']//60):02d}:{r['src']%60:05.2f}  {kind}  "
              f"남김 {r['residual']:.2f}초 (뒤 {r['tail']:.2f} + 앞 {r['lead']:.2f})"
              f"  …{r['word']}")
    print()

    # 사람만 잘라낸 소스 구간 = 재발화 삭제 후보
    def gaps_removed(vids, lo, hi):
        out = []
        for a, b in zip(vids, vids[1:]):
            if a["s1"] > hi:
                break
            if b["s0"] - a["s1"] > 0.02:
                out.append((a["s1"], b["s0"]))
        return out

    hrm = gaps_removed(hv, 0, edit_end + 5)
    arm = gaps_removed(av, 0, edit_end + 5)

    def overlap(x, y):
        return max(0.0, min(x[1], y[1]) - max(x[0], y[0]))

    print("[사람이 추가로 잘라낸 구간] (자동편집은 남겨뒀던 곳)")
    for g in hrm:
        extra = (g[1] - g[0]) - sum(overlap(g, a) for a in arm)
        if extra < 0.4:
            continue
        txt = " ".join(w["text"] for w in words
                       if w["start"] >= g[0] - 0.2 and w["end"] <= g[1] + 0.2)
        sp_in = sum(overlap(g, s) for s in speech)
        print(f"  {int(g[0]//60):02d}:{g[0]%60:05.2f}~{int(g[1]//60):02d}:"
              f"{g[1]%60:05.2f}  ({g[1]-g[0]:.1f}초, 발화 {sp_in:.1f}초)")
        if txt.strip():
            print(f"      「{txt.strip()[:70]}」")
    print()

    # 자막 비교
    def sub_stats(ts, upto):
        sel = [t for t in ts if t["t1"] <= upto]
        if not sel:
            return None
        import statistics as st
        lens = [len(t["text"]) for t in sel]
        durs = [t["t1"] - t["t0"] for t in sel]
        return len(sel), st.median(lens), max(lens), st.median(durs), max(durs)

    hu = max((v["t1"] for v in hv if v["s1"] <= edit_end + 5), default=0)
    au = max((v["t1"] for v in av if v["s1"] <= edit_end + 5), default=0)
    print("[자막] (손댄 구간)")
    for label, ts, upto in (("사람", ht, hu), ("자동", at, au)):
        s = sub_stats(ts, upto)
        if s:
            print(f"  {label}: {s[0]}줄, 글자수 중앙 {s[1]:.0f} 최대 {s[2]}, "
                  f"길이 중앙 {s[3]:.2f}초 최대 {s[4]:.2f}초")
    print("\n  사람 자막 앞부분:")
    for t in ht[:14]:
        print(f"    {t['t0']:6.2f}~{t['t1']:6.2f} ({t['t1']-t['t0']:.2f}s) "
              f"{t['text'][:40]}")


if __name__ == "__main__":
    analyze(*sys.argv[1:5])
