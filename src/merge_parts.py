# -*- coding: utf-8 -*-
"""파트별로 나눠 찍은 촬영 원본을 순서대로 하나로 잇는다.

한 번에 20분을 이어 찍지 않고 파트마다 끊어 찍는 촬영 방식이 있다. 그러면
원본이 여러 벌이 되고, 같은 파트를 다시 찍은 테이크까지 섞인다.

    06_01_오프닝_T1.mp4
    06_01_오프닝_T2_OK.mp4     <- 다시 찍은 것, 이게 최종
    06_02_도입_T1_OK.mp4
    06_03_파트1_T1.mp4

이 도구는 파트마다 쓸 테이크 하나를 고르고, **촬영 순서가 아니라 파트번호
순서로** 이어 붙인다. 뒤 파이프라인(발화 검출·전사·컷 계획·드래프트)은
원본이 하나라고 전제하므로 여기서 한 벌로 만들어 준다.

테이크를 고르는 규칙
  1. 이름 끝에 `_OK` 가 붙은 것이 있으면 그것 (사람이 고른 결과)
  2. 없으면 테이크 번호가 가장 큰 것 (마지막에 다시 찍은 것)

파일 이름이 `차시_파트번호_파트명_테이크` 형식이 아니면 이름순으로 잇는다.

**파트 경계를 JSON 으로 남긴다.** 나중에 "이 구간이 몇 번 파트였는지"를 알아야
슬레이트를 찾거나(`find_slates.py`) 다시 찍을 파트를 짚을 수 있다.

규격이 서로 다른 파트가 섞여 있으면(해상도·fps·코덱) 재인코딩해서 잇는다.
전부 같으면 무재인코딩으로 잇는다. 90분 분량이 몇 초에 끝난다.

사용: python src/merge_parts.py <원본폴더|파일...> <출력.mp4> [--json <경계.json>]
                                [--fps 30] [--size 1920x1080]
"""
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cliargs import split_args  # noqa: E402

NAME = re.compile(r"^(?P<ep>[^_]+)_(?P<part>\d+)_(?P<title>.+?)"
                  r"(?:_T(?P<take>\d+))?(?P<ok>_OK)?$", re.I)
VIDEO_EXT = (".mp4", ".mov", ".mkv", ".m4v")


def probe(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height,r_frame_rate,codec_name",
         "-show_entries", "format=duration", "-of", "json", str(path)],
        capture_output=True, text=True, encoding="utf-8")
    if out.returncode:
        raise SystemExit(f"ffprobe 실패: {path}\n{out.stderr}")
    d = json.loads(out.stdout)
    st = (d.get("streams") or [{}])[0]
    num, _, den = (st.get("r_frame_rate") or "0/1").partition("/")
    fps = float(num) / float(den or 1) if float(den or 1) else 0.0
    return {
        "path": str(path),
        "name": Path(path).stem,
        "w": st.get("width"), "h": st.get("height"),
        "fps": round(fps, 3), "codec": st.get("codec_name"),
        "dur": float(d.get("format", {}).get("duration", 0.0)),
    }


def pick_takes(files):
    """파트마다 쓸 테이크 하나를 고른다. -> [(정렬키, path, 파트명)]"""
    parsed, plain = {}, []
    for f in files:
        m = NAME.match(Path(f).stem)
        if not m:
            plain.append(f)
            continue
        part = int(m.group("part"))
        take = int(m.group("take") or 0)
        ok = bool(m.group("ok"))
        cur = parsed.get(part)
        # _OK 가 최우선, 그다음 테이크 번호가 큰 것
        rank = (1 if ok else 0, take)
        if cur is None or rank > cur[0]:
            parsed[part] = (rank, f, m.group("title"))

    if plain and parsed:
        print(f"  [주의] 이름 형식이 다른 파일 {len(plain)}개는 건너뛴다:")
        for f in plain:
            print(f"         {Path(f).name}")
    if not parsed:
        return [(i, f, Path(f).stem) for i, f in enumerate(sorted(plain))]
    return [(p, parsed[p][1], parsed[p][2]) for p in sorted(parsed)]


def uniform(infos):
    first = infos[0]
    return all(i["w"] == first["w"] and i["h"] == first["h"]
               and i["codec"] == first["codec"]
               and abs(i["fps"] - first["fps"]) < 0.01 for i in infos)


def merge(sources, out_path, json_path=None, fps=None, size=None):
    out = Path(out_path).resolve()
    files = []
    for s in sources:
        p = Path(s)
        if p.is_dir():
            files += [q.resolve() for q in sorted(p.iterdir())
                      if q.suffix.lower() in VIDEO_EXT]
        else:
            files.append(p.resolve())
    # 같은 폴더에 남아 있는 지난번 결과물을 입력으로 다시 삼지 않는다
    files = [str(f) for f in files if f != out]
    if not files:
        raise SystemExit("이어 붙일 영상을 찾지 못했습니다.")

    chosen = pick_takes(files)
    infos = [probe(f) for _, f, _ in chosen]

    print(f"파트 {len(chosen)}개")
    for (part, _, title), info in zip(chosen, infos):
        print(f"  {part:>3}  {title:<12} {info['dur']:8.2f}초  "
              f"{info['w']}x{info['h']} {info['fps']}fps  {info['name']}")

    same = uniform(infos)
    tgt_fps = fps or infos[0]["fps"]
    tgt_size = size or f"{infos[0]['w']}x{infos[0]['h']}"
    if same and not fps and not size:
        print("  규격이 전부 같다 -> 무재인코딩으로 잇는다")
    else:
        print(f"  규격이 다르거나 지정됐다 -> {tgt_size} {tgt_fps}fps 로 재인코딩")

    out.parent.mkdir(parents=True, exist_ok=True)
    # concat 목록은 출력 폴더에 두고 **절대경로**를 적는다. 상대경로를 적으면
    # ffmpeg 이 목록 파일 위치를 기준으로 풀어서 엉뚱한 곳을 찾는다.
    lst = out.parent / "_lecture_cut_concat.txt"
    lst.write_text("".join(
        "file '%s'\n" % info["path"].replace("\\", "/").replace("'", "'\\''")
        for info in infos), encoding="utf-8")

    cmd = ["ffmpeg", "-v", "error", "-stats", "-f", "concat", "-safe", "0",
           "-i", str(lst)]
    if same and not fps and not size:
        cmd += ["-c", "copy"]
    else:
        cmd += ["-vf", f"scale={tgt_size.replace('x', ':')}:force_original_"
                       f"aspect_ratio=decrease,pad={tgt_size.replace('x', ':')}"
                       f":(ow-iw)/2:(oh-ih)/2,fps={tgt_fps}",
                "-c:v", "libx264", "-preset", "medium", "-crf", "18",
                "-c:a", "aac", "-b:a", "192k"]
    cmd += ["-y", str(out)]
    r = subprocess.run(cmd)
    lst.unlink(missing_ok=True)
    if r.returncode:
        raise SystemExit("이어 붙이기 실패. 규격이 다르면 --fps/--size 로 "
                         "재인코딩을 지정해 보세요.")

    # 붙인 결과의 실제 길이로 경계를 다시 잰다. 무재인코딩이라도 파트마다
    # 끝 프레임이 미세하게 달라져 합이 딱 맞지 않는다.
    total = probe(out)["dur"]
    bounds, t = [], 0.0
    for (part, _, title), info in zip(chosen, infos):
        bounds.append({"part": part, "title": title, "file": info["path"],
                       "start": round(t, 3), "end": round(t + info["dur"], 3),
                       "dur": round(info["dur"], 3)})
        t += info["dur"]
    drift = total - t
    print(f"\n완성: {out}  {total:.2f}초 ({total/60:.1f}분)")
    if abs(drift) > 0.5:
        print(f"  [주의] 파트 길이 합과 {drift:+.2f}초 차이. 경계값이 그만큼 "
              f"밀려 있을 수 있다")

    if json_path:
        Path(json_path).parent.mkdir(parents=True, exist_ok=True)
        Path(json_path).write_text(json.dumps(
            {"output": str(out), "total": round(total, 3),
             "drift": round(drift, 3), "parts": bounds},
            ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"  파트 경계: {json_path}")
    return {"output": str(out), "total": total, "parts": bounds}


if __name__ == "__main__":
    pos, opt = split_args(sys.argv[1:], {"--json", "--fps", "--size"})
    if len(pos) < 2:
        raise SystemExit(__doc__)
    merge(pos[:-1], pos[-1], json_path=opt.get("--json"),
          fps=float(opt["--fps"]) if "--fps" in opt else None,
          size=opt.get("--size"))
