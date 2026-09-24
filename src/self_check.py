# -*- coding: utf-8 -*-
"""렌더한 미리보기를 보여 드리기 전에 스스로 검사한다 (video-use 의 self-eval 에서 가져온 절차).

계획 파일이 아니라 **렌더된 결과**를 본다. 계획이 맞아도 굽기·렌더에서 틀어질 수 있다
(2026-09-24 숨긴 자리 테두리, 상자 윗부분 노출은 계획이 아니라 결과에서만 보였다).

  숫자 검사  영상 길이 = 컷 계획 길이(프레임 단위), 영상·소리 길이 같음,
            컷 경계마다 소리가 튀나(경계 ±3ms 의 샘플 차이가 주변의 10배 넘고 -40dBFS 넘으면 튐)
  그림 검사  박스(시작 직후·끝 직전), 확대(멈춘 가운데), 교안 단계(나타난 직후), 장면 전환(컷 직전·직후)
            프레임을 모아 확인 그림(4x3)으로 만든다. **이 그림은 반드시 눈으로 본다**

고치고 다시 렌더하고 다시 검사하는 것은 **3번까지만** 한다. 그래도 남으면 무엇이 남았는지 사용자에게 알린다.

사용: python self_check.py <미리보기.mp4> <keep.json> --out <폴더>
        [--boxes 박스.json] [--zooms 확대.json] [--builds 빌드굽기.json] [--transitions 전환.json] [--fps 30]
  계획 파일의 시각은 모두 원본(소재) 시각이다. 미리보기는 keep 블록을 프레임 단위로 이은 것이어야 한다
"""
import json
import math
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

FONT = "C:/Windows/Fonts/malgunbd.ttf"


def blocks_of(keep, fps):
    out, e = [], 0.0
    for a, b in keep:
        f0, f1 = math.ceil(a * fps - 1e-6), math.ceil(b * fps - 1e-6)
        if f1 > f0:
            out.append((f0 / fps, f1 / fps, e))
            e += (f1 - f0) / fps
    return out, e


def to_edit(blocks, t):
    for a, b, e0 in blocks:
        if a <= t < b:
            return e0 + (t - a)
    return None


def probe(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,duration", "-of", "json",
                          str(path)], capture_output=True, text=True).stdout
    return {s["codec_type"]: float(s.get("duration", 0)) for s in json.loads(out)["streams"]}


def clicks(path, cuts, sr=48000):
    with tempfile.TemporaryDirectory() as td:
        raw = Path(td) / "a.raw"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(path), "-vn", "-ac", "1", "-ar", str(sr),
                        "-f", "s16le", str(raw)], check=True)
        x = np.fromfile(raw, dtype=np.int16).astype(np.float32) / 32768
    bad = []
    w, near = int(0.003 * sr), int(0.05 * sr)
    for t in cuts:
        i = int(t * sr)
        if i - near < 1 or i + near >= len(x):
            continue
        dx = np.abs(np.diff(x[i - near:i + near]))
        center = dx[near - w:near + w].max()
        around = np.median(np.concatenate([dx[:near - w], dx[near + w:]])) + 1e-6
        level = 20 * math.log10(max(np.abs(x[i - w:i + w]).max(), 1e-6))
        if center / around > 10 and level > -40:
            bad.append((round(t, 3), round(center / around, 1), round(level, 1)))
    return bad


def grab(path, t):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{max(0, t):.3f}", "-i", str(path), "-frames:v", "1",
                          "-vf", "scale=480:270", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         capture_output=True).stdout
    if len(raw) < 480 * 270 * 3:
        return Image.new("RGB", (480, 270), (60, 60, 60))
    return Image.fromarray(np.frombuffer(raw[:480 * 270 * 3], np.uint8).reshape(270, 480, 3))


def sheets(path, shots, out_dir, per=12):
    f = ImageFont.truetype(FONT, 15)
    files = []
    for s in range(0, len(shots), per):
        grp = shots[s:s + per]
        sheet = Image.new("RGB", (480 * 4, 300 * math.ceil(len(grp) / 4)), "white")
        for k, (t, label) in enumerate(grp):
            im = grab(path, t)
            tile = Image.new("RGB", (480, 300), "white")
            tile.paste(im, (0, 30))
            d = ImageDraw.Draw(tile)
            d.text((4, 6), f"{int(t // 60)}:{t % 60:04.1f} {label}"[:52], fill=(180, 0, 0), font=f)
            sheet.paste(tile, ((k % 4) * 480, (k // 4) * 300))
        p = Path(out_dir) / f"확인_{s // per + 1:02d}.jpg"
        sheet.save(p, quality=82)
        files.append(p)
    return files


def main(argv):
    pos, opt, k = [], {}, 0
    while k < len(argv):
        if argv[k].startswith("--"):
            opt[argv[k]] = argv[k + 1]
            k += 2
        else:
            pos.append(argv[k])
            k += 1
    video, keep_p = pos[:2]
    fps = int(opt.get("--fps", 30))
    out_dir = Path(opt.get("--out", Path(video).parent / "self_check"))
    out_dir.mkdir(parents=True, exist_ok=True)
    keep = json.loads(Path(keep_p).read_text(encoding="utf-8"))["keep_ranges"]
    blocks, total = blocks_of(keep, fps)
    load = lambda key, name: (json.loads(Path(opt[key]).read_text(encoding="utf-8")).get(name, [])  # noqa: E731
                              if key in opt else [])
    lines, fails = [], 0
    # 숫자 검사
    st = probe(video)
    v, a = st.get("video", 0), st.get("audio", 0)
    ok_len = abs(v - total) <= 1.5 / fps
    ok_av = abs(v - a) <= 0.05
    fails += (not ok_len) + (not ok_av)
    lines += [f"- 길이: 영상 {v:.3f}초 · 계획 {total:.3f}초 {'맞음' if ok_len else '**다름**'}",
              f"- 영상·소리 길이 차이 {abs(v - a):.3f}초 {'맞음' if ok_av else '**다름**'}"]
    cuts = [e0 for _, _, e0 in blocks[1:]]
    bad = clicks(video, cuts)
    fails += len(bad)
    lines.append(f"- 컷 경계 {len(cuts)}곳 중 소리 튐 {len(bad)}곳" + (": " + ", ".join(f"{t}s(x{r}, {l}dB)" for t, r, l in bad[:10]) if bad else ""))
    # 그림 검사
    shots = []
    for it in load("--boxes", "items"):
        s, e = it["src"]
        es, ee = to_edit(blocks, s), to_edit(blocks, e - 0.05)
        if es is not None:
            shots.append((es + 0.35, f"박스 시작 {it.get('why', '')}"))
        if ee is not None:
            shots.append((ee - 0.2, f"박스 끝 {it.get('why', '')}"))
    for zm in load("--zooms", "zooms"):
        mid = (zm["src"][0] + zm["src"][1]) / 2
        t = to_edit(blocks, mid) or to_edit(blocks, zm["src"][0] + 1.0)
        if t is not None:
            shots.append((t, f"확대 {zm.get('why', '')}"))
    for sp in load("--builds", "spans"):
        for r in sp.get("reveal", []):
            t = to_edit(blocks, r + 0.6)
            if t is not None:
                shots.append((t, f"S{sp['slide']:02d} 단계 나타남"))
    for c in load("--transitions", "cuts"):
        for a_, b_, e0 in blocks:
            if abs(b_ - c["src_end"]) < 0.06:
                cut = e0 + (b_ - a_)
                shots += [(cut - 0.12, f"전환 앞 {c.get('why', '')}"), (cut + 0.12, "전환 뒤")]
                break
    shots.sort()
    files = sheets(video, shots, out_dir)
    lines.append(f"- 확인 그림 {len(files)}장 · 프레임 {len(shots)}개 → {out_dir}")
    report = out_dir / "자가검사.md"
    report.write_text("# 렌더 자가 검사\n\n" + "\n".join(lines) + "\n\n**확인 그림을 전부 본다.** "
                      "틀린 곳이 있으면 고쳐 다시 렌더하고 다시 검사한다(3번까지).\n", encoding="utf-8")
    print("\n".join(lines))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
