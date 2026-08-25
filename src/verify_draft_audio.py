# -*- coding: utf-8 -*-
"""
만든 드래프트에서 소리가 나는지 넘겨주기 전에 검사한다.

왜 필요한가: 2026-08-13 에 오디오 유실을 고치면서 캡컷 스키마 값을
추측으로 넣었고(extra_type_option=1), 그 결과 2·3차시 드래프트가 통째로
무음이 됐는데 하루 동안 아무도 몰랐다. draft_content.json 만 읽으면
멀쩡해 보인다 — volume 은 1.0 이고 has_audio 도 True 다. 캡컷에서 열어야만
'오디오가 분리됨' 이 뜬다. 그래서 사람 눈 대신 이 검사가 막는다.

`build_capcut_draft.py` 마지막 단계에서 자동으로 돈다. 하나라도 걸리면
빌드가 실패한다 — 무음 드래프트를 사용자에게 넘기지 않는다.

사용:
    python src/verify_draft_audio.py <드래프트이름>
    python src/verify_draft_audio.py <드래프트이름> --compare <정상드래프트이름>

--compare 는 캡컷이 **직접 만든** 드래프트와 비디오 material 필드를
전부 대조해 다른 값을 보여준다. 이번 버그를 실제로 찾아낸 방법이다.
캡컷 스키마 값을 추측해야 할 상황이 오면 추측하지 말고 이걸 먼저 돌려라.
기준으로 쓸 만한 드래프트: `2차시_자동편집` (2026-08-08, 캡컷이 저장한 것).
"""
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from draft_root import DRAFTS  # noqa: E402

# 비디오 material 이 이 값이 아니면 캡컷이 클립을 음소거한다.
# 캡컷이 직접 만든 드래프트(2차시_자동편집, 08-08)에서 읽어온 값이다.
# 추측으로 바꾸지 마라 — 바꾸려면 --compare 로 근거를 먼저 만들어라.
REQUIRED_VIDEO_FIELDS = {
    "has_audio": True,
    # 1 이면 '소리를 별도 트랙으로 떼어냈다'는 뜻 → 캡컷이 음소거로 취급
    "extra_type_option": 0,
    "has_sound_separated": False,
}


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def all_material_ids(d: dict) -> set:
    ids = set()
    for arr in d.get("materials", {}).values():
        if isinstance(arr, list):
            for m in arr:
                if isinstance(m, dict) and m.get("id"):
                    ids.add(m["id"])
    return ids


def source_has_audio(path: str):
    """원본 파일에 오디오 스트림이 실제로 있는지. ffprobe 없으면 None."""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "a",
             "-show_entries", "stream=codec_type", "-of", "csv=p=0", path],
            capture_output=True, text=True, timeout=60)
    except (FileNotFoundError, subprocess.SubprocessError):
        return None
    return "audio" in out.stdout


def resolve_path(path: str, root: Path | None) -> str:
    """캡컷은 드래프트 안에 든 소재를 `##_draftpath_placeholder_<GUID>_##/...`
    로 적는다(폴더를 옮겨도 안 깨지게). 실제 파일을 찾으려면 드래프트
    최상위로 되돌려야 한다. 안 그러면 멀쩡한 소재를 '없다' 고 한다."""
    if not path or "_draftpath_placeholder_" not in path or root is None:
        return path
    tail = path.split("_##", 1)[1].lstrip("/\\")
    base = root
    while base.parent != base and not (base / "materials").is_dir():
        base = base.parent
    return str(base / tail)


def check(d: dict, root: Path | None = None) -> tuple:
    """(실패목록, 경고목록) 을 돌려준다."""
    fails, warns = [], []
    mats = d.get("materials", {})
    vids = [v for v in mats.get("videos", []) if v.get("type") == "video"]

    if not vids:
        fails.append("비디오 material 이 없다")
        return fails, warns

    # 1) 원본 파일과 오디오 스트림
    for raw in sorted({v.get("path", "") for v in vids}):
        path = resolve_path(raw, root)
        if not path or not Path(path).exists():
            fails.append(f"원본 파일이 없다: {raw or '(경로 비어 있음)'}")
            continue
        has = source_has_audio(path)
        if has is False:
            fails.append(f"원본 파일에 오디오 스트림이 없다: {path}")
        elif has is None:
            warns.append("ffprobe 가 없어 원본 오디오 스트림을 확인하지 못했다")

    # 2) 캡컷이 클립을 음소거로 읽게 만드는 플래그
    #
    # 두 가지를 걸러야 오탐이 안 난다:
    #  - 사용자가 편집하다 보면 아무 세그먼트도 안 쓰는 고아 material 이
    #    쌓인다. 그건 화면에 없으니 무음과 무관하다.
    #  - 사용자가 **일부러** 오디오를 분리해 둔 클립이 있다. 2차시에서는
    #    재녹음할 곳 표시로 쓰고 있다. 이건 정상이고 고치면 안 된다 —
    #    분리한 오디오가 그 자리를 덮고 있으면 소리는 멀쩡히 난다.
    live = set()
    for tr in d.get("tracks", []):
        if tr.get("type") == "video":
            for s in tr.get("segments", []):
                live.add(s.get("material_id"))
    aud = []
    for tr in d.get("tracks", []):
        if tr.get("type") == "audio":
            for s in tr.get("segments", []):
                a = s["target_timerange"]["start"] / 1e6
                aud.append((a, a + s["target_timerange"]["duration"] / 1e6))

    def audio_covered(mid):
        """이 material 을 쓰는 클립이 **전부** 분리 오디오로 덮여 있나.

        캡컷은 material 을 여러 클립이 공유한다(2차시는 461컷이 2개를
        나눠 쓴다). 그래서 '하나라도 안 덮였으면 정상 분리가 아니다'.
        """
        spans = []
        for tr in d.get("tracks", []):
            if tr.get("type") != "video":
                continue
            for s in tr.get("segments", []):
                if s.get("material_id") != mid:
                    continue
                a = s["target_timerange"]["start"] / 1e6
                spans.append((a, a + s["target_timerange"]["duration"] / 1e6))
        if not spans:
            return True
        for a, b in spans:
            cov = sum(max(0.0, min(b, y) - max(a, x)) for x, y in aud)
            # 기준을 mute_under_audio.py 와 같은 0.5 로 맞춘다. 컷 경계와
            # 재녹음 구간이 딱 떨어지지 않으면(2차시에 77% 짜리가 하나 있다)
            # 0.9 로는 의도적 음소거를 버그로 잡아낸다. 안 덮인 자투리는
            # VAD 여유분(0.2~0.45초)이라 대개 무음이다.
            if cov / max(b - a, 1e-9) < 0.5:
                return False
        return True

    # material -> 그 클립이 편집본 어디에 있는지 (사람이 찾아가 보라고)
    at = {}
    for tr in d.get("tracks", []):
        if tr.get("type") != "video":
            continue
        for s in tr.get("segments", []):
            a = s["target_timerange"]["start"] / 1e6
            at.setdefault(s.get("material_id"), a)

    for field, want in REQUIRED_VIDEO_FIELDS.items():
        bad = [v for v in vids
               if v.get(field) != want
               and v.get("id") in live
               and not (field != "has_audio" and audio_covered(v.get("id")))]
        if not bad:
            continue
        got = sorted({repr(v.get(field)) for v in bad})
        when = ", ".join(
            f"{int(at.get(v['id'], 0)//60):02d}:{at.get(v['id'], 0) % 60:04.1f}"
            for v in sorted(bad, key=lambda v: at.get(v["id"], 0))[:6])
        msg = (f"비디오 material {len(bad)}/{len(vids)}개의 {field} 가 "
               f"{want!r} 가 아니다 (실제 {', '.join(got)}) — 그 클립은 "
               f"'오디오가 분리됨' 이라 소리가 없다. 위치: {when}")
        # 2026-08-13 버그는 **전 클립**이 이랬다. 몇 개만 그런 것은 사람이
        # 그 대목만 소리를 떼어낸 것일 수 있으므로(재녹음) 막지 않고 알린다.
        if len(bad) / max(len(vids), 1) > 0.2:
            fails.append(msg)
        else:
            warns.append(msg + " — 일부러 떼어낸 것이면 무시하세요")

    # 3) 세그먼트 볼륨과 오디오 채널 매핑
    scm = {m["id"] for m in mats.get("sound_channel_mappings", [])
           if isinstance(m, dict) and m.get("id")}
    ids = all_material_ids(d)
    dangling = 0
    # **소리를 통째로 갈아 끼운 경우는 정상이다.** 오디오 보정을 외부에서 돌리면
    # 전체 길이짜리 오디오 한 장을 깔고 원본 영상 트랙을 음소거한다. 그때 영상
    # 트랙의 볼륨 0 은 의도된 것이고, 여기서 실패로 잡으면 사람이 복구 스크립트를
    # 돌려 소리를 두 번 겹치게 만든다. 그래서 **대체 오디오가 깔려 있는지** 본다.
    total = (d.get("duration") or 0)
    covered = 0
    for tr in d.get("tracks", []):
        if tr.get("type") != "audio":
            continue
        for s in tr.get("segments", []):
            if (s.get("volume") or 0) > 0:
                covered = max(covered, s["target_timerange"]["start"]
                              + s["target_timerange"]["duration"])
    replaced = total > 0 and covered >= total * 0.95

    # 정지화면(photo)은 소리 자체가 없으니 음소거 검사 대상이 아니다.
    photos = {m.get("id") for m in mats.get("videos", [])
              if isinstance(m, dict) and m.get("type") == "photo"}

    for tr in d.get("tracks", []):
        segs = tr.get("segments", [])
        if tr.get("type") in ("video", "audio"):
            mute = [s for s in segs
                    if not (s.get("volume") or 0) > 0
                    and s.get("material_id") not in photos]
            if mute:
                msg = (f"{tr.get('type')} 트랙에 볼륨 0 인 세그먼트 "
                       f"{len(mute)}/{len(segs)}개")
                if replaced and tr.get("type") == "video":
                    # 소리를 통짜 오디오로 갈아 끼웠으면 영상 쪽 음소거는 의도다
                    warns.append(msg + " — 전체 길이 오디오가 따로 깔려 있어"
                                       " 일부러 음소거한 것으로 봅니다")
                else:
                    fails.append(msg)
        if tr.get("type") == "video":
            nomap = [s for s in segs
                     if not (set(s.get("extra_material_refs", [])) & scm)]
            if nomap:
                fails.append(
                    f"비디오 세그먼트 {len(nomap)}/{len(segs)}개에 "
                    f"sound_channel_mapping 참조가 없다 "
                    f"— 캡컷이 저장할 때 소리를 떨어뜨린다")
        for s in segs:
            dangling += sum(1 for r in s.get("extra_material_refs", [])
                            if r not in ids)
    if dangling:
        warns.append(f"어느 material 도 가리키지 않는 참조 {dangling}건 "
                     f"(pycapcut import_srt 가 만든다. 캡컷은 무시한다)")

    return fails, warns


def compare(draft: dict, ref: dict) -> None:
    """캡컷이 직접 만든 드래프트와 비디오 material 필드를 대조한다."""
    a = [v for v in draft.get("materials", {}).get("videos", [])
         if v.get("type") == "video"]
    b = [v for v in ref.get("materials", {}).get("videos", [])
         if v.get("type") == "video"]
    if not a or not b:
        print("  대조할 비디오 material 이 없다")
        return
    a, b = a[0], b[0]
    # 드래프트마다 다른 게 당연한 값들
    skip = {"id", "material_id", "material_name", "path", "media_path",
            "local_material_id", "duration", "width", "height",
            "category_id", "category_name", "crop", "crop_ratio",
            "crop_scale", "intensifies_audio_path"}
    keys = sorted(set(a) | set(b))
    rows = []
    for k in keys:
        if k in skip:
            continue
        av, bv = a.get(k, "(없음)"), b.get(k, "(없음)")
        if av != bv:
            rows.append((k, av, bv))
    if not rows:
        print("  다른 필드 없음")
        return
    print(f"  {'필드':<28} {'이 드래프트':<22} 정상본")
    for k, av, bv in rows:
        print(f"  {k:<28} {str(av)[:20]:<22} {str(bv)[:28]}")


def main(argv):
    if not argv:
        raise SystemExit(__doc__)
    name = argv[0]
    ref_name = None
    if "--compare" in argv:
        i = argv.index("--compare")
        ref_name = argv[i + 1] if i + 1 < len(argv) else None

    folder = DRAFTS / name if not Path(name).is_dir() else Path(name)
    if not folder.is_dir():
        raise SystemExit(f"드래프트가 없습니다: {folder}")

    files = sorted(folder.rglob("draft_content.json"))
    if not files:
        raise SystemExit(f"draft_content.json 이 없습니다: {folder}")

    total_fail = 0
    for f in files:
        d = load(f)
        # **길이 0짜리 `subdraft/` 는 타임라인이 아니다.** 캡컷이 합성 클립을
        # 위해 만들어 두는 빈 껍데기라 경로도 비어 있고 값도 본편 규칙과 다르다.
        # 이걸 실패로 잡으면 멀쩡한 드래프트가 매번 실패로 뜬다. 길이가 있는
        # subdraft(사람이 만든 합성 클립)는 그대로 검사한다.
        if "subdraft" in f.parts and not d.get("duration"):
            print(f"[건너뜀] {f.relative_to(folder)} — 빈 subdraft")
            continue
        fails, warns = check(d, f.parent)
        total_fail += len(fails)
        rel = f.relative_to(folder)
        head = "OK  " if not fails else "실패"
        print(f"[{head}] {rel}")
        for m in fails:
            print(f"    X {m}")
        for m in warns:
            print(f"    ! {m}")

    if ref_name:
        ref_path = DRAFTS / ref_name / "draft_content.json"
        if not ref_path.exists():
            raise SystemExit(f"기준 드래프트가 없습니다: {ref_path}")
        print(f"\n[대조] {name} vs {ref_name} (캡컷이 만든 정상본)")
        compare(load(files[0]), load(ref_path))

    if total_fail:
        raise SystemExit(
            f"\n소리가 안 나는 드래프트입니다 (문제 {total_fail}건). "
            f"사용자에게 넘기지 마세요.\n"
            f"  이미 만든 드래프트라면: "
            f"python src/repair_sound_separated.py {name}\n"
            f"  값을 뭘로 고쳐야 할지 모르겠으면 추측하지 말고: "
            f"python src/verify_draft_audio.py {name} --compare 2차시_자동편집")
    print("\n소리 관련 검사 통과.")


if __name__ == "__main__":
    main(sys.argv[1:])
