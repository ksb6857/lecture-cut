# -*- coding: utf-8 -*-
"""납품 규격을 지켰는지 기계로 확인한다.

연수 영상은 검수에서 되돌아오면 재작업이 크다. 그런데 지적받는 항목의
상당수는 **눈으로 세는 것**이다. 해상도, 길이, 파일명, 금지 표현, 자막이
있으면 안 되는 구간의 자막. 그건 기계가 훨씬 잘 센다.

이 도구는 규격을 `프로필 JSON` 으로 받아 검사한다. 플랫폼마다 규격이
다르므로 코드에 값을 박지 않는다. 프로필 만드는 법은
[docs/규격점검.md](../docs/규격점검.md).

무엇을 보나
  영상   해상도·프레임레이트·코덱·길이·파일명·오디오 유무·라우드니스
  자막   허용 구간 밖의 자막, 한 줄 글자 수, 줄 수, 금지 표현   (캡컷 드래프트)
  말     차시 언급, 금지 표현, 슬레이트 잔존                     (전사본)

**기계가 못 보는 것은 못 본다고 적는다.** 자막이 화면 내용을 가리는지,
학습목표가 관찰 가능한 행동동사인지, 블러가 빠졌는지는 사람이 본다.
프로필의 `직접확인` 목록이 보고서 끝에 그대로 실린다.

사용:
  python src/check_guidelines.py <영상.mp4> [영상2.mp4 ...]
                                 --프로필 <프로필.json>
                                 [--드래프트 <캡컷드래프트이름>]
                                 [--전사 <words.json>]
                                 [--보고서 <점검보고서.md>]

영상은 위치 인자로 준다. 셋 다 없어도 되고, 준 것만 검사하고 나머지는
'건너뜀' 으로 적는다.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cliargs import split_args  # noqa: E402

# 한국어 윈도우 콘솔은 cp949 라 일부 문자에서 UnicodeEncodeError 로 죽는다.
# 보고서 파일은 UTF-8 로 따로 쓰므로, 콘솔에서는 못 찍는 글자만 대체한다.
try:
    sys.stdout.reconfigure(errors="replace")
except Exception:
    pass

OK, BAD, WARN, SKIP = "통과", "실패", "확인", "건너뜀"


class Report:
    def __init__(self):
        self.rows = []

    def add(self, group, item, verdict, detail=""):
        self.rows.append((group, item, verdict, detail))

    def count(self, verdict):
        return sum(1 for r in self.rows if r[2] == verdict)

    def render(self):
        out, cur = [], None
        for group, item, verdict, detail in self.rows:
            if group != cur:
                cur = group
                out.append(f"\n## {group}\n")
                out.append("| | 항목 | 결과 |")
                out.append("|---|---|---|")
            mark = {OK: "○", BAD: "✕", WARN: "△", SKIP: "·"}[verdict]
            cell = item if not detail else f"{item}<br>{detail}"
            out.append(f"| {mark} | {cell} | {verdict} |")
        return "\n".join(out)


# ---------------------------------------------------------------- 영상

def probe(path):
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format",
         "-of", "json", str(path)],
        capture_output=True, text=True, encoding="utf-8")
    if r.returncode:
        raise SystemExit(f"ffprobe 실패: {path}")
    d = json.loads(r.stdout)
    v = next((s for s in d["streams"] if s["codec_type"] == "video"), {})
    a = next((s for s in d["streams"] if s["codec_type"] == "audio"), None)
    num, _, den = (v.get("r_frame_rate") or "0/1").partition("/")
    return {
        "w": v.get("width"), "h": v.get("height"),
        "fps": round(float(num) / float(den or 1), 3) if float(den or 1) else 0,
        "codec": v.get("codec_name"), "has_audio": a is not None,
        "dur": float(d["format"].get("duration", 0)),
        "container": Path(path).suffix.lstrip(".").lower(),
    }


def loudness(path):
    """통합 라우드니스(LUFS). ebur128 은 프레임마다 순간값을 찍고 맨 끝에
    Summary 를 낸다. 그냥 첫 `I:` 를 집으면 **영상 맨 앞 무음의 순간값**
    (-70 LUFS 같은 것)을 통합값으로 읽는다. Summary 뒤에서 찾는다."""
    r = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(path),
         "-af", "ebur128", "-f", "null", "-"],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    log = r.stderr or ""
    tail = log[log.rfind("Summary:"):] if "Summary:" in log else ""
    m = re.search(r"I:\s*(-?[\d.]+)\s*LUFS", tail)
    if m:
        return float(m.group(1))
    # Summary 가 없으면(아주 짧은 파일 등) 마지막 순간값이라도 쓴다
    all_hits = re.findall(r"I:\s*(-?[\d.]+)\s*LUFS", log)
    return float(all_hits[-1]) if all_hits else None


def identifies(kind, filename):
    """이 파일이 이 종류인가. `식별` 이 있으면 그걸로, 없으면 `이름` 으로."""
    return bool(re.search(kind.get("식별") or kind.get("이름", "$^"), filename))


def check_videos(rep, paths, prof):
    spec = prof.get("영상", {})
    files = prof.get("파일", [])
    seen = []
    for p in paths:
        p = Path(p)
        g = f"영상 · {p.name}"
        if not p.exists():
            rep.add(g, "파일이 있는가", BAD, str(p))
            continue
        info = probe(p)
        seen.append((p, info))

        # 이 파일이 프로필의 어느 종류인지 가른다.
        #
        # 종류를 가리는 것과 파일명 규칙을 지켰는지는 **다른 문제**다.
        # 이름이 조금 틀렸다고 종류를 못 가르면 길이 검사까지 통째로
        # 건너뛰어 버린다. 그래서 느슨한 `식별` 로 종류를 정하고,
        # 엄격한 `이름` 으로는 규칙 준수만 따진다.
        kind = next((f for f in files if identifies(f, p.name)), None)
        if files:
            strict = kind and re.search(kind.get("이름", "$^"), p.name)
            if strict:
                rep.add(g, f"파일명 규칙 ({kind['종류']})", OK, f"`{p.name}`")
            elif kind:
                rep.add(g, f"파일명 규칙 ({kind['종류']})", BAD,
                        f"`{p.name}` 이 규칙 `{kind['이름']}` 에 안 맞는다")
            else:
                pats = " / ".join(f"`{f.get('이름')}`" for f in files)
                rep.add(g, "파일명 규칙", BAD,
                        f"어느 종류인지도 못 가리겠다. 규칙: {pats}")

        if spec.get("가로") and spec.get("세로"):
            got = f"{info['w']}×{info['h']}"
            want = f"{spec['가로']}×{spec['세로']}"
            rep.add(g, f"해상도 {want}",
                    OK if got == want else BAD, got)
        if spec.get("fps"):
            ok = abs(info["fps"] - spec["fps"]) < 0.05
            rep.add(g, f"프레임레이트 {spec['fps']}", OK if ok else BAD,
                    f"{info['fps']}fps")
        if spec.get("코덱"):
            ok = info["codec"] == spec["코덱"]
            rep.add(g, f"코덱 {spec['코덱']}", OK if ok else BAD,
                    str(info["codec"]))
        if spec.get("컨테이너"):
            ok = info["container"] == spec["컨테이너"]
            rep.add(g, f"형식 {spec['컨테이너']}", OK if ok else BAD,
                    info["container"])

        mm = f"{int(info['dur'] // 60)}분 {info['dur'] % 60:.1f}초"
        if kind and kind.get("길이초"):
            lo, hi = kind["길이초"]
            ok = lo <= info["dur"] <= hi
            rep.add(g, f"길이 {lo/60:.0f}~{hi/60:.0f}분",
                    OK if ok else BAD, mm)
        else:
            rep.add(g, "길이", SKIP, mm)

        want_audio = (kind or {}).get("오디오")
        if want_audio == "있음":
            rep.add(g, "오디오 트랙", OK if info["has_audio"] else BAD,
                    "있음" if info["has_audio"] else "없음")
        elif want_audio == "없음":
            rep.add(g, "오디오 없음", BAD if info["has_audio"] else OK,
                    "있음" if info["has_audio"] else "없음")

        lo_spec = prof.get("라우드니스", {})
        if lo_spec.get("범위") and info["has_audio"]:
            lu = loudness(p)
            lo, hi = lo_spec["범위"]
            if lu is None:
                rep.add(g, "라우드니스", SKIP, "측정 실패")
            else:
                rep.add(g, f"라우드니스 {lo}~{hi} LUFS",
                        OK if lo <= lu <= hi else WARN, f"{lu} LUFS")
                info["lufs"] = lu

    # 파일 사이 음량 차이
    diff_max = prof.get("라우드니스", {}).get("파일간차이")
    lus = [(p.name, i["lufs"]) for p, i in seen if i.get("lufs") is not None]
    if diff_max and len(lus) >= 2:
        lo, hi = min(lus, key=lambda x: x[1]), max(lus, key=lambda x: x[1])
        d = hi[1] - lo[1]
        rep.add("영상 · 파일 사이", f"음량 차이 {diff_max} LU 이내",
                OK if d <= diff_max else WARN,
                f"{d:.1f} LU ({lo[0]} {lo[1]} / {hi[0]} {hi[1]})")

    # 있어야 할 파일이 다 왔는가
    if files and paths:
        for f in files:
            found = any(identifies(f, Path(p).name) for p in paths)
            rep.add("영상 · 구성", f"{f['종류']} 파일",
                    OK if found else BAD, "있음" if found else "없음")


# ---------------------------------------------------------------- 자막

def check_captions(rep, draft, prof, banned):
    from dump_captions import lines
    g = "자막 (캡컷 드래프트)"
    try:
        caps = lines(draft)
    except SystemExit as e:
        rep.add(g, "드래프트 읽기", SKIP, str(e))
        return
    spec = prof.get("자막", {})
    rep.add(g, "자막 줄 수", SKIP, f"{len(caps)}줄")

    allowed = spec.get("허용구간")
    if allowed:
        bad = [c for c in caps
               if not any(a <= c[0] < b for a, b in allowed)]
        rng = ", ".join(f"{a:.0f}~{b:.0f}초" for a, b in allowed)
        if bad:
            ex = "; ".join(f"{c[0]:.1f}초 「{c[2][:20]}」" for c in bad[:3])
            rep.add(g, f"자막은 {rng} 안에만", BAD,
                    f"{len(bad)}줄이 밖에 있다. 예: {ex}")
        else:
            rep.add(g, f"자막은 {rng} 안에만", OK)

    if spec.get("한줄글자"):
        n = spec["한줄글자"]
        over = [c for c in caps
                for ln in c[2].split(" / ") if len(ln.strip()) > n]
        rep.add(g, f"한 줄 {n}자 이내", OK if not over else BAD,
                "" if not over else f"{len(over)}줄 초과")
    if spec.get("최대줄"):
        n = spec["최대줄"]
        over = [c for c in caps if len(c[2].split(" / ")) > n]
        rep.add(g, f"최대 {n}줄", OK if not over else BAD,
                "" if not over else f"{len(over)}개 초과")

    check_banned(rep, g, [c[2] for c in caps], banned, "자막")


# ---------------------------------------------------------------- 말

def check_speech(rep, words_path, prof, banned):
    g = "말 (전사본)"
    data = json.loads(Path(words_path).read_text(encoding="utf-8"))
    words = [w for w in data["words"] if w.get("type") == "word"]
    if not words:
        rep.add(g, "전사본 읽기", SKIP, "단어가 없다")
        return
    rep.add(g, "전사 단어 수", SKIP, f"{len(words)}개")

    # 문장으로 이어 붙여야 '앞 차시에서' 같은 두 낱말 표현이 잡힌다
    text = " ".join(w["text"] for w in words)
    check_banned(rep, g, [text], banned, "말", words=words)


def check_banned(rep, group, texts, banned, where, words=None):
    for b in banned:
        if where not in b.get("어디", ["자막", "말"]):
            continue
        pat = re.compile(b["표현"])
        hits = []
        for t in texts:
            for m in pat.finditer(t):
                snip = t[max(0, m.start() - 12):m.end() + 12].strip()
                hits.append(snip)
        label = b.get("이름") or f"`{b['표현']}`"
        if hits:
            ex = " / ".join(f"「…{h}…」" for h in hits[:3])
            more = f" 외 {len(hits)-3}건" if len(hits) > 3 else ""
            rep.add(group, label, BAD, f"{len(hits)}건. {ex}{more}"
                    + (f"<br>{b['고침']}" if b.get("고침") else ""))
        else:
            rep.add(group, label, OK)


# ---------------------------------------------------------------- 실행

def run(profile_path, videos=(), draft=None, words=None, out=None):
    prof = json.loads(Path(profile_path).read_text(encoding="utf-8"))
    banned = prof.get("금지표현", [])
    rep = Report()

    if videos:
        check_videos(rep, videos, prof)
    else:
        rep.add("영상", "영상 검사", SKIP, "--영상 을 주지 않았다")

    if draft:
        check_captions(rep, draft, prof, banned)
    else:
        rep.add("자막 (캡컷 드래프트)", "자막 검사", SKIP,
                "--드래프트 를 주지 않았다")

    if words:
        check_speech(rep, words, prof, banned)
    else:
        rep.add("말 (전사본)", "말 검사", SKIP, "--전사 를 주지 않았다")

    title = prof.get("이름", "납품 규격")
    body = [f"# {title} 점검 보고서", "",
            f"기계가 볼 수 있는 것만 봤다. 실패 {rep.count(BAD)}건 · "
            f"확인 {rep.count(WARN)}건 · 통과 {rep.count(OK)}건 · "
            f"건너뜀 {rep.count(SKIP)}건.", rep.render()]

    manual = prof.get("직접확인", [])
    if manual:
        body += ["", "## 기계가 못 보는 것 (사람이 본다)", ""]
        body += [f"- [ ] {m}" for m in manual]

    text = "\n".join(body) + "\n"
    if out:
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_text(text, encoding="utf-8")
        print(f"보고서: {out}")

    # 콘솔에는 걸린 것만
    print(f"\n{title} — 실패 {rep.count(BAD)} · 확인 {rep.count(WARN)} · "
          f"통과 {rep.count(OK)} · 건너뜀 {rep.count(SKIP)}")
    for group, item, verdict, detail in rep.rows:
        if verdict in (BAD, WARN):
            d = re.sub(r"<br>", " ", detail)
            print(f"  [{verdict}] {group} / {item}"
                  + (f"  {d}" if d else ""))
    if manual:
        print(f"\n  사람이 볼 항목 {len(manual)}개는 보고서에 있다")
    return rep


if __name__ == "__main__":
    pos, opt = split_args(
        sys.argv[1:], {"--프로필", "--드래프트", "--전사", "--보고서",
                       "--profile", "--draft", "--words", "--out"})
    prof = opt.get("--프로필") or opt.get("--profile")
    if not prof:
        raise SystemExit(__doc__)
    # --영상 뒤에 오는 위치 인자들을 전부 영상으로 본다
    run(prof, videos=pos,
        draft=opt.get("--드래프트") or opt.get("--draft"),
        words=opt.get("--전사") or opt.get("--words"),
        out=opt.get("--보고서") or opt.get("--out"))
