# -*- coding: utf-8 -*-
"""캡컷을 못 여는 기기에서 볼 미리보기 영상(720p)을 드래프트와 같은 컷으로 만든다. self_check.py 가 이걸 검사한다.

  화면  소재에서 남는 블록의 **프레임 번호**를 골라 잇는다(select). 원본은 고정 프레임률이어야 한다
  소리  블록마다 고른 프레임 수만큼 PCM 으로 정확히 잘라 잇는다. 수백 번 이어도 밀리지 않는다
        (concat 디먹서 inpoint/outpoint 는 키프레임이 아닌 곳에서 앞 프레임이 섞여 쓰지 않는다)
  페이드 가장자리가 조용하지 않은 이음매 양쪽에 1프레임 페이드(apply_audio_fades.py 와 같게)
  박스  박스 계획을 편집본 시각으로 옮겨 빨간 테두리로 그린다(캡컷의 등장 페이드는 없다)
  전환  전환 계획 자리에서 0.47초 동안 어두워졌다 밝아진다(캡컷 'B 페이드' 흉내)
  표시  검토 표시 계획(apply_notes.py 와 같은 파일)이 있으면 그 구간 화면 위쪽에 노란 글자를 입힌다.
        캡컷을 못 여는 휴대폰에서도 뺄 후보를 보며 고를 수 있다

ffmpeg 식에 수백 항을 평평하게 더하면 해석이 안 된다. 괄호로 균형 잡아 더한다(balanced).
출력은 -frames:v 로 끊는다. -t 로 끊으면 원본 끝까지 디코딩한다.

사용: python render_preview.py <소재.mp4> <keep.json> <출력.mp4>
        [--boxes 박스.json] [--transitions 전환.json] [--notes 검토표시.json]
        [--levels 세기.npy --offset 초] [--until 편집초] [--fps 30]
  --levels·--offset: 이음매 페이드를 판단할 세기 캐시와 (소재 시각 - 세기 시각)
"""
import json
import math
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

SR = 48000


FONTS = ["C:/Windows/Fonts/malgun.ttf", "/System/Library/Fonts/AppleSDGothicNeo.ttc",
         "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"]


def balanced(terms):
    if len(terms) == 1:
        return terms[0]
    m = len(terms) // 2
    return f"({balanced(terms[:m])}+{balanced(terms[m:])})"


def render(src, keep, out, boxes=(), cuts=(), db=None, offset=0.0, until=None, fps=30, quiet=-62.0, notes=()):
    blocks, edges, e = [], [], 0.0
    for a, b in keep:
        f0, f1 = math.ceil(a * fps - 1e-6), math.ceil(b * fps - 1e-6)
        if f1 <= f0:
            continue
        blocks.append((a, b, f0, f1))
        edges.append(e)
        e += (f1 - f0) / fps
        if until and e >= until:
            break
    nframes = sum(f1 - f0 for _, _, f0, f1 in blocks)

    def span(a, b):
        hits = []
        for (x, y, f0, f1), e0 in zip(blocks, edges):
            lo, hi = max(a, f0 / fps), min(b, f1 / fps)
            if hi > lo:
                hits.append((e0 + lo - f0 / fps, e0 + hi - f0 / fps))
        return (hits[0][0], hits[-1][1]) if hits else None

    tmp = Path(tempfile.mkdtemp(prefix="preview_"))
    vf = [f"select='{balanced([f'between(n,{f0},{f1 - 1})' for _, _, f0, f1 in blocks])}'",
          "setpts=N/FRAME_RATE/TB", "scale=1280:720"]
    dips = []
    for c in cuts:
        for (a, b, f0, f1), e0 in zip(blocks, edges):
            if abs(b - c["src_end"]) < 0.06:
                dips.append(e0 + (f1 - f0) / fps)
                break
    if dips:
        vf.append(f"eq=brightness='-min(1,{balanced([f'max(0,1-abs(t-{t:.3f})/0.2335)' for t in dips])})':eval=frame")
    s = 1280 / 1920
    nb = 0
    for it in boxes:
        sp = span(*it["src"])
        if not sp:
            continue
        x0, y0, x1, y1 = [round(v * s) for v in it["rect"]]
        vf.append(f"drawbox=x={x0}:y={y0}:w={x1 - x0}:h={y1 - y0}:color=0xE00000:t=4:"
                  f"enable='between(t,{sp[0]:.3f},{sp[1]:.3f})'")
        nb += 1
    nn = 0
    font = next((f for f in FONTS if Path(f).exists()), None)
    if notes and font:
        # 경로의 ':' 를 식에서 피하려고 글꼴과 글을 임시 폴더에 두고 그 폴더에서 ffmpeg 를 돌린다
        shutil.copy(font, tmp / ("font" + Path(font).suffix))
        for i, it in enumerate(notes):
            sp = span(*it["src"])
            if not sp:
                continue
            (tmp / f"n{i}.txt").write_bytes(it["text"].encode("utf-8"))   # \r\n 이면 줄이 두 번 바뀐다
            vf.append(f"drawtext=fontfile=font{Path(font).suffix}:textfile=n{i}.txt:expansion=none:fontsize=22:"
                      f"fontcolor=0xFFD900:borderw=2:bordercolor=black:line_spacing=6:box=1:boxcolor=black@0.45:"
                      f"boxborderw=8:x=(w-text_w)/2:y=24:enable='between(t,{sp[0]:.3f},{sp[1]:.3f})'")
            nn += 1
        print(f"  검토 표시 {nn}개를 입힘")
    elif notes:
        print("  한글 글꼴을 못 찾아 검토 표시를 입히지 않았다")
    script = tmp / "vf.txt"
    script.write_text(",\n".join(vf), encoding="utf-8")

    noisy = set()
    if db is not None:
        from apply_audio_fades import win_max
        for k in range(len(blocks) - 1):
            a_end, b_start = blocks[k][1] - offset, blocks[k + 1][0] - offset
            if a_end > 0 and b_start > 0 and (win_max(db, a_end) > quiet or win_max(db, b_start) > quiet):
                noisy.add(k)
    raw, cut = tmp / "a.raw", tmp / "cut.raw"
    need = blocks[-1][3] / fps + 1.0
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-t", f"{need:.3f}", "-vn", "-ac", "2",
                    "-ar", str(SR), "-f", "s16le", str(raw)], check=True)
    fl = SR // fps
    ramp = np.linspace(0, 1, fl, dtype=np.float32)[:, None]
    with open(raw, "rb") as fi, open(cut, "wb") as fo:
        for k, (a, b, f0, f1) in enumerate(blocks):
            s0, n = f0 * SR // fps, (f1 - f0) * SR // fps
            fi.seek(s0 * 4)
            buf = fi.read(n * 4)
            buf += bytes(n * 4 - len(buf))
            if (k in noisy or k - 1 in noisy) and n > 2 * fl:
                x = np.frombuffer(buf, np.int16).reshape(-1, 2).astype(np.float32)
                if k - 1 in noisy:
                    x[:fl] *= ramp
                if k in noisy:
                    x[-fl:] *= ramp[::-1]
                buf = np.clip(np.rint(x), -32768, 32767).astype(np.int16).tobytes()
            fo.write(buf)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(Path(src).resolve()), "-f", "s16le", "-ar", str(SR),
                    "-ac", "2", "-i", str(cut), "-/vf", str(script), "-map", "0:v", "-map", "1:a", "-c:v", "libx264",
                    "-preset", "veryfast", "-crf", "24", "-r", str(fps), "-c:a", "aac", "-b:a", "128k",
                    "-frames:v", str(nframes), "-movflags", "+faststart", str(Path(out).resolve())],
                   check=True, cwd=str(tmp))
    for f in (raw, cut):
        f.unlink(missing_ok=True)
    return e, len(blocks), nb, len(dips), len(noisy)


def main(argv):
    pos, opt, k = [], {}, 0
    while k < len(argv):
        if argv[k].startswith("--"):
            opt[argv[k]] = argv[k + 1]
            k += 2
        else:
            pos.append(argv[k])
            k += 1
    src, keep_p, out = pos[:3]
    keep = json.loads(Path(keep_p).read_text(encoding="utf-8"))["keep_ranges"]
    boxes = json.loads(Path(opt["--boxes"]).read_text(encoding="utf-8"))["items"] if "--boxes" in opt else []
    cuts = json.loads(Path(opt["--transitions"]).read_text(encoding="utf-8"))["cuts"] if "--transitions" in opt else []
    db = np.load(opt["--levels"]) if "--levels" in opt else None
    notes = json.loads(Path(opt["--notes"]).read_text(encoding="utf-8"))["items"] if "--notes" in opt else []
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    total, nb_, nbox, ndip, nfade = render(src, keep, out, boxes, cuts, db, float(opt.get("--offset", 0)),
                                           float(opt["--until"]) if "--until" in opt else None,
                                           int(opt.get("--fps", 30)), notes=notes)
    print(f"미리보기 {total / 60:.2f}분 · 블록 {nb_} · 박스 {nbox} · 전환 {ndip} · 이음매 페이드 {nfade} → {out}")


if __name__ == "__main__":
    main(sys.argv[1:])
