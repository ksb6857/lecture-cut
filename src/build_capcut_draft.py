# -*- coding: utf-8 -*-
"""
keep_ranges.json + words.json + analysis.json(자막교정) + 원본 mp4
  -> CapCut 드래프트 생성 (+ 검수용 SRT)

- 비디오 트랙: keep_range 마다 원본에서 해당 구간을 잘라 이어붙인 세그먼트
- 자막 트랙: 편집 후 타임라인 기준 SRT를 만들어 import_srt
- 자막 문구는 Vrew 클립 단위로 묶고, corrections 를 적용
"""
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pycapcut as cc
from pycapcut import trange, tim

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cliargs import split_args  # noqa: E402
from caption_split import split_words  # noqa: E402
from draft_root import find_draft_root  # noqa: E402,F401


def capcut_running() -> bool:
    """캡컷이 떠 있는 동안 드래프트 폴더를 건드리면 안 된다.
    실제로 2026-08-08 23:48 에 이걸 어겨서 사용자가 편집 중이던 프로젝트가
    깨졌다. 캡컷은 열려 있는 프로젝트 폴더가 밖에서 바뀌면 사본을 만들거나
    메모리 상태로 되돌려 저장해 버린다."""
    try:
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq CapCut.exe"],
                             capture_output=True, text=True, timeout=15)
        return "CapCut.exe" in out.stdout
    except Exception:
        return False


def backup_existing(folder: Path) -> Path | None:
    """덮어쓰기 전에 기존 드래프트를 통째로 복사해 둔다."""
    if not folder.is_dir():
        return None
    stamp = time.strftime("%Y%m%d_%H%M%S")
    dest = folder.parent.parent / "_lecture_autocut_backup" / \
        f"{folder.name}_{stamp}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(folder, dest)
    print(f"  기존 드래프트 백업: {dest}")
    return dest


def fmt_srt_time(sec: float) -> str:
    ms = int(round(sec * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


class TimeMapper:
    """원본 시간 -> 편집 후 타임라인 시간 매핑"""

    def __init__(self, keep_ranges):
        self.ranges = keep_ranges
        self.offsets = []  # 각 range 시작 시점의 편집 타임라인 시간
        t = 0.0
        for s, e in keep_ranges:
            self.offsets.append(t)
            t += e - s
        self.total = t

    def map(self, src_t: float):
        """잘려나간 시간이면 None"""
        for (s, e), off in zip(self.ranges, self.offsets):
            if s <= src_t <= e:
                return off + (src_t - s)
        return None

    def map_clamp(self, src_t: float):
        prev_end_mapped = 0.0
        for (s, e), off in zip(self.ranges, self.offsets):
            if src_t < s:
                return prev_end_mapped
            if src_t <= e:
                return off + (src_t - s)
            prev_end_mapped = off + (e - s)
        return self.total


def make_snapper(speech_segments, tol=0.6):
    """자막 경계를 실제 발화 시작/끝에 붙인다.

    STT 단어 타임스탬프는 앞뒤로 0.3초씩 헐렁해서 그대로 쓰면 자막이
    말보다 먼저 뜨고 늦게 사라진다. 근처에 VAD 경계가 있으면 그쪽으로 당긴다.
    """
    starts = sorted(s for s, _ in speech_segments)
    ends = sorted(e for _, e in speech_segments)

    def nearest(arr, t):
        import bisect
        i = bisect.bisect_left(arr, t)
        cands = [arr[j] for j in (i - 1, i) if 0 <= j < len(arr)]
        if not cands:
            return t
        best = min(cands, key=lambda v: abs(v - t))
        return best if abs(best - t) <= tol else t

    return (lambda t: nearest(starts, t)), (lambda t: nearest(ends, t))


def build_subtitles(words_data, corrections, deleted, mapper, srt_path,
                    speech_segments=None):
    """Vrew 클립 단위로 자막 라인 구성 -> 편집 타임라인 기준 SRT"""
    fix = {c["i"]: c["fixed"] for c in corrections}
    snap_start, snap_end = (make_snapper(speech_segments)
                            if speech_segments else (lambda t: t, lambda t: t))
    lines = []  # (start_edit, end_edit, text)
    cur_words = []

    def flush():
        if not cur_words:
            return
        s = mapper.map_clamp(snap_start(cur_words[0]["start"]))
        e = mapper.map_clamp(snap_end(cur_words[-1]["end"]))
        if e - s < 0.05:
            return
        text = " ".join(fix.get(w["i"], w["text"]) for w in cur_words)
        lines.append((s, e, text))

    # 자막 줄 나누기
    # 1단계: 문장 단위로 모은다 (문장부호 또는 긴 쉼)
    # 2단계: 문장이 길면 **한국어 어미·조사를 보고 의미 단위로** 끊는다.
    #   글자수만 보고 끊으면 '좌측 / 사이드바를' 처럼 수식어가 갈라진다.
    #   말 사이 간격으로 끊을 수는 없다 — Whisper 는 한 세그먼트 안에서
    #   단어 타임스탬프를 빈틈없이 붙여서 실제 쉼이 0.00초로 나온다.
    # 길이 기준은 사람이 손본 편집본에서 역산: 한 줄 19자 / 2.4초 안팎.
    MAX_CHARS, BREAK_GAP, MAX_SHOW = 24, 0.45, 5.0
    src = [w for w in words_data["words"]
           if w["type"] == "word" and w["i"] not in deleted]

    sentences, cur = [], []
    for k, w in enumerate(src):
        cur.append(w)
        nxt = src[k + 1] if k + 1 < len(src) else None
        ends_sentence = fix.get(w["i"], w["text"]).rstrip()[-1:] in ".?!。"
        gap = (nxt["start"] - w["end"]) if nxt else 1e9
        if ends_sentence or gap >= BREAK_GAP or nxt is None:
            sentences.append(cur)
            cur = []
    if cur:
        sentences.append(cur)

    for sent in sentences:
        texts = [fix.get(w["i"], w["text"]) for w in sent]
        for a, b in split_words(texts, max_chars=MAX_CHARS):
            cur_words = sent[a:b]
            flush()
    cur_words = []

    # 짧은 라인 병합(1초 미만이거나 5자 이하면 다음 라인과 합침)
    merged = []
    for s, e, t in lines:
        # 너무 짧은 줄만 앞 줄에 붙인다. 합쳐도 한 줄 상한을 넘지 않을 때만
        # (넘게 두면 애써 나눈 의미 단위가 다시 뭉개진다)
        if merged and (e - s < 0.8 or len(t) <= 4) \
                and s - merged[-1][1] < 0.4 \
                and len(merged[-1][2]) + len(t) + 1 <= 24:
            ps, pe, pt = merged[-1]
            merged[-1] = (ps, e, pt + " " + t)
        else:
            merged.append((s, e, t))

    # 겹침 제거: 스냅 때문에 앞 라인 끝을 파고들 수 있다 (캡컷이 거부함)
    GAP = 0.04
    clean = []
    for s, e, t in sorted(merged, key=lambda x: x[0]):
        if clean and s < clean[-1][1] + GAP:
            s = clean[-1][1] + GAP
        e = min(e, s + MAX_SHOW)   # 무음까지 자막이 늘어져 있지 않게
        if e - s < 0.2:            # 밀린 끝에 너무 짧아지면 앞 라인에 흡수
            if clean and len(clean[-1][2]) + len(t) < 60:
                ps, pe, pt = clean[-1]
                clean[-1] = (ps, max(pe, e), pt + " " + t)
            continue
        clean.append((s, e, t))

    with open(srt_path, "w", encoding="utf-8-sig") as f:
        for n, (s, e, t) in enumerate(clean, 1):
            f.write(f"{n}\n{fmt_srt_time(s)} --> {fmt_srt_time(e)}\n{t}\n\n")
    return len(clean)


def build(words_path, ranges_path, analysis_path, video_path, draft_name,
          speech_path=None, fps=30, captions=True):
    """captions=False 면 SRT 파일은 만들되 드래프트에는 넣지 않는다.

    나레이션 전체 자막을 금지하는 납품 규격이 있다(화면에 이미 있는 말을
    자막으로 되풀이하지 말라는 것). 그런 규격에서는 드래프트에 자막을 깔아
    두면 편집자가 그걸 일일이 지워야 하고, 한둘 남으면 검수에 걸린다.
    SRT 는 검수·자막 문구 작성에 쓰이므로 파일로는 계속 남긴다."""
    words_data = json.loads(Path(words_path).read_text(encoding="utf-8"))
    plan = json.loads(Path(ranges_path).read_text(encoding="utf-8"))
    analysis = {"corrections": [], "deletions": []}
    if analysis_path and Path(analysis_path).exists():
        analysis = json.loads(Path(analysis_path).read_text(encoding="utf-8"))

    speech_segments = None
    if speech_path and Path(speech_path).exists():
        speech_segments = json.loads(
            Path(speech_path).read_text(encoding="utf-8"))["speech"]

    # 삭제된 재발화의 단어는 자막에서도 빼야 한다.
    # 단어 인덱스 지시와 시간 범위 지시 두 형식을 모두 처리한다.
    #
    # 환각(kind="hallucination")은 STT 가 지어낸 말이라 잘라낼 소리가 없다.
    # 영상 컷에는 반영되지 않지만(=미적용) 자막에서는 반드시 빼야 한다.
    # 이걸 빼먹으면 "배달의민족", "시청해주셔서 감사합니다" 같은 유튜브
    # 상투구가 강의 자막 한복판에 남는다.
    deleted = set()
    dele_spans = []
    halluc = [d for d in plan.get("retakes_unapplied", [])
              if d.get("kind") == "hallucination" and "from_i" in d]
    for d in halluc:
        deleted.update(range(d["from_i"], d["to_i"] + 1))
    if halluc:
        print(f"  자막에서만 제거(환각): {len(halluc)}건 "
              f"— {', '.join(d.get('text', '')[:12] for d in halluc)}")
    for d in plan.get("retakes_applied", []):
        if "from_i" in d:
            deleted.update(range(d["from_i"], d["to_i"] + 1))
        else:
            dele_spans.append((float(d["from_t"]), float(d["to_t"])))
    if dele_spans:
        for w in words_data["words"]:
            if w["type"] != "word":
                continue
            mid = (w["start"] + w["end"]) / 2
            if any(a <= mid <= b for a, b in dele_spans):
                deleted.add(w["i"])

    keep = plan["keep_ranges"]
    mapper = TimeMapper(keep)

    root = find_draft_root()
    if capcut_running():
        raise SystemExit(
            "캡컷이 실행 중입니다. 완전히 종료한 뒤 다시 실행하세요.\n"
            "  (열려 있는 상태에서 드래프트를 건드리면 편집 중이던 작업이\n"
            "   캡컷에 의해 덮어써지거나 사본으로 갈라져 사라질 수 있습니다)")
    backup_existing(root / draft_name)

    folder = cc.DraftFolder(str(root))
    script = folder.create_draft(draft_name, 1920, 1080, fps=fps,
                                 allow_replace=True)
    script.add_track(cc.TrackType.video)

    material = cc.VideoMaterial(str(video_path))
    t = 0.0
    for s, e in keep:
        dur = e - s
        seg = cc.VideoSegment(
            material,
            trange(tim(f"{t}s"), tim(f"{dur}s")),
            source_timerange=trange(tim(f"{s}s"), tim(f"{dur}s")),
        )
        script.add_segment(seg)
        t += dur

    # 자막: SRT 생성 후 임포트
    srt_path = Path(ranges_path).parent / (Path(ranges_path).stem + ".srt")
    n_subs = build_subtitles(words_data, analysis.get("corrections", []),
                             deleted, mapper, srt_path, speech_segments)
    if captions:
        script.import_srt(
            str(srt_path),
            track_name="자막",
            style_reference=cc.TextSegment(
                "", trange("0s", "1s"),
                style=cc.TextStyle(size=8.0, auto_wrapping=True,
                                   align=1, color=(1.0, 1.0, 1.0)),
                clip_settings=cc.ClipSettings(transform_y=-0.85),
                border=cc.TextBorder(color=(0.0, 0.0, 0.0)),
            ),
        )
    else:
        print(f"  자막 {n_subs}줄은 SRT 로만 남기고 드래프트에는 넣지 않았다")
    script.save()

    # pycapcut 은 오디오 채널 매핑을 안 넣어서, 캡컷이 저장할 때마다
    # 원본 소리가 떨어져 나간다('오디오 복구'를 눌러야 돌아옴). 여기서 보강.
    from fix_draft_audio import fix as fix_audio
    content_path = root / draft_name / "draft_content.json"
    r = fix_audio(content_path)
    print(f"  오디오 정보 보강: 세그먼트 {r['segments_fixed']}개")

    # pycapcut 은 같은 파일을 쓰는 클립 전부가 material 하나를 공유하게 만든다.
    # 캡컷은 클립당 material 하나다. '오디오 분리'는 material 단위 플래그라,
    # 공유 상태에서 클립 하나만 분리해도 그 material 을 쓰는 클립이 전부
    # 음소거된다. 캡컷처럼 클립마다 따로 준다.
    from split_materials import split as split_mats
    s = split_mats(content_path, respect_audio_track=False)
    print(f"  클립별 material 분리: {s['segments']}개")

    # 소리가 나는지 확인하고 넘긴다. draft_content.json 만 읽으면 무음
    # 드래프트도 멀쩡해 보이므로(volume 1.0, has_audio True) 사람 눈으로는
    # 못 잡는다. 2026-08-13 에 이걸로 2·3차시가 하루 동안 무음이었다.
    from verify_draft_audio import check as check_audio
    fails, warns = check_audio(
        json.loads(content_path.read_text(encoding="utf-8")))
    for m in warns:
        print(f"  ! {m}")
    if fails:
        for m in fails:
            print(f"  X {m}")
        raise SystemExit(
            f"'{draft_name}' 은 소리가 안 나는 드래프트입니다. 넘기지 마세요.\n"
            f"  무엇을 어떤 값으로 고쳐야 할지 모르겠으면 추측하지 말고\n"
            f"  캡컷이 직접 만든 정상본과 대조하세요:\n"
            f"    python src/verify_draft_audio.py {draft_name} "
            f"--compare <캡컷이 직접 만든 정상 드래프트 이름>")
    print("  소리 검사 통과")

    print(f"OK: draft '{draft_name}' 생성")
    print(f"    비디오 세그먼트 {len(keep)}개, 자막 {n_subs}줄, "
          f"길이 {mapper.total/60:.1f}분")
    print(f"    SRT: {srt_path}")
    return draft_name


if __name__ == "__main__":
    pos, opt = split_args(sys.argv[1:], {"--fps"})
    if len(pos) < 5:
        raise SystemExit(__doc__)
    build(*pos[:6], fps=int(opt.get("--fps", 30)),
          captions="--no-captions" not in opt)
