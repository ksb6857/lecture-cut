# -*- coding: utf-8 -*-
"""구간 한 곳을 한 장에: 프레임 띠 + 실제 세기(dB) + 낱말 + 남는 곳·잘린 곳 + 강조 박스.

컷 경계가 말 위에 떨어졌나, 헛시작이 남았나, 박스가 제자리에 붙었나를 판단할 때 쓴다.
**훑는 데 쓰지 않는다.** 판단이 필요한 자리에서만 부른다(video-use 의 timeline_view 에서 가져온 원칙).

video-use 판과 다른 점
- 파형 대신 10ms 단위 세기(dBFS)를 그리고 -45dB(소리)·-50dB(무음) 선을 긋는다. 컷 판단 기준과 같다
- 남는 구간(초록)·잘린 구간(빨강)과 컷 선을 겹쳐 그린다
- 박스 계획을 주면 그 시각 프레임에 박스를 그린다. 좌표는 원본 1920x1080 픽셀 그대로 적어 둔다

시각은 전부 이 영상 파일의 시각이다(keep·낱말·박스 계획이 같은 기준이어야 한다).

사용: python timeline_view.py <영상 또는 wav> <시작초> <끝초> [-o 출력.png]
        [--words words.json] [--keep keep.json] [--boxes 박스.json] [--n 8]
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

FONT = "C:/Windows/Fonts/malgun.ttf"
FW, FH = 320, 180          # 프레임 한 칸
WAVE_H, WORD_H = 170, 90


def font(size):
    try:
        return ImageFont.truetype(FONT, size)
    except OSError:
        return ImageFont.load_default()


def has_video(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v", "-show_entries", "stream=index",
                          "-of", "csv=p=0", str(path)], capture_output=True, text=True).stdout
    return bool(out.strip())


def frame(path, t):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.3f}", "-i", str(path), "-frames:v", "1",
                          "-vf", "scale=1920:1080", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         capture_output=True).stdout
    if len(raw) < 1920 * 1080 * 3:
        return Image.new("RGB", (1920, 1080), (40, 40, 40))
    return Image.fromarray(np.frombuffer(raw[:1920 * 1080 * 3], np.uint8).reshape(1080, 1920, 3))


def levels(path, a, b, hop=0.01):
    with tempfile.TemporaryDirectory() as td:
        wav = Path(td) / "a.raw"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{a:.3f}", "-t", f"{b - a:.3f}", "-i", str(path),
                        "-vn", "-ac", "1", "-ar", "16000", "-f", "s16le", str(wav)], check=True)
        x = np.fromfile(wav, dtype=np.int16).astype(np.float32) / 32768
    n = int(16000 * hop)
    m = len(x) // n
    if m == 0:
        return np.full(1, -120.0)
    rms = np.sqrt((x[:m * n].reshape(m, n) ** 2).mean(axis=1))
    return 20 * np.log10(np.maximum(rms, 1e-6))


def render(path, a, b, out, words=None, keep=None, boxes=None, n=8):
    W = FW * n
    img = Image.new("RGB", (W, FH + WAVE_H + WORD_H + 30), "white")
    d = ImageDraw.Draw(img)
    f12, f14 = font(13), font(15)
    X = lambda t: int((t - a) / (b - a) * (W - 1))       # noqa: E731
    # 프레임 띠
    ts = [a + (b - a) * (k + 0.5) / n for k in range(n)]
    if has_video(path):
        for k, t in enumerate(ts):
            fr = frame(path, t)
            for it in boxes or []:
                s, e = it["src"]
                if s <= t <= e:
                    ImageDraw.Draw(fr).rectangle(it["rect"], outline=(255, 0, 0), width=8)
            img.paste(fr.resize((FW, FH)), (k * FW, 0))
            d.rectangle([k * FW, 0, k * FW + 70, 16], fill=(255, 255, 255))
            d.text((k * FW + 3, 0), f"{t:.2f}", fill=(0, 0, 0), font=f12)
    y0 = FH
    # 남는 곳·잘린 곳
    if keep is not None:
        d.rectangle([0, y0, W, y0 + WAVE_H], fill=(255, 225, 225))
        for p, q in keep:
            if q > a and p < b:
                d.rectangle([X(max(p, a)), y0, X(min(q, b)), y0 + WAVE_H], fill=(225, 245, 225))
        for p, q in keep:
            for t in (p, q):
                if a < t < b:
                    d.line([X(t), 0, X(t), y0 + WAVE_H], fill=(0, 90, 200), width=2)
    # 세기
    db = levels(path, a, b)
    top, bot = 0.0, -70.0
    Y = lambda v: int(y0 + (top - max(bot, min(top, v))) / (top - bot) * WAVE_H)   # noqa: E731
    pts = [(int(i / len(db) * (W - 1)), Y(v)) for i, v in enumerate(db)]
    d.line(pts, fill=(40, 40, 40), width=1)
    for v, col, lab in ((-45, (230, 120, 0), "-45dB 소리"), (-50, (150, 0, 150), "-50dB 무음")):
        d.line([0, Y(v), W, Y(v)], fill=col, width=1)
        d.text((4, Y(v) - 15), lab, fill=col, font=f12)
    # 낱말
    wy = y0 + WAVE_H + 4
    row = 0
    for w in words or []:
        if w.get("type", "word") != "word" or w["end"] < a or w["start"] > b:
            continue
        x = X(max(a, w["start"]))
        d.line([x, y0, x, y0 + WAVE_H], fill=(170, 170, 170), width=1)
        d.text((x + 2, wy + row * 22), w["text"], fill=(0, 0, 160), font=f14)
        row = (row + 1) % 4
    # 눈금
    step = 0.5 if b - a <= 12 else (1 if b - a <= 30 else 5)
    t = np.ceil(a / step) * step
    while t <= b:
        d.line([X(t), y0 + WAVE_H + WORD_H, X(t), y0 + WAVE_H + WORD_H + 8], fill=(0, 0, 0))
        d.text((X(t) + 2, y0 + WAVE_H + WORD_H + 8), f"{t:.1f}", fill=(0, 0, 0), font=f12)
        t += step
    img.save(out)
    return out


def main(argv):
    pos, opt, k = [], {}, 0
    while k < len(argv):
        if argv[k] in ("-o", "--words", "--keep", "--boxes", "--n"):
            opt[argv[k]] = argv[k + 1]
            k += 2
        else:
            pos.append(argv[k])
            k += 1
    path, a, b = pos[0], float(pos[1]), float(pos[2])
    words = json.loads(Path(opt["--words"]).read_text(encoding="utf-8"))["words"] if "--words" in opt else None
    keep = json.loads(Path(opt["--keep"]).read_text(encoding="utf-8"))["keep_ranges"] if "--keep" in opt else None
    boxes = json.loads(Path(opt["--boxes"]).read_text(encoding="utf-8"))["items"] if "--boxes" in opt else None
    out = opt.get("-o", f"timeline_{a:.1f}-{b:.1f}.png")
    render(path, a, b, out, words, keep, boxes, int(opt.get("--n", 8)))
    print(out)


if __name__ == "__main__":
    main(sys.argv[1:])
