# -*- coding: utf-8 -*-
"""작은 글씨 화면을 확대해 원본에 굽는다 — 카메라가 다가가듯 부드럽게 들어가고 나온다.

캡컷 마스크 확대(apply_mask.py)는 세그먼트 통째로 걸리고, 확대된 부분 밖은 검게 비며,
들어가고 나올 때 뚝 끊긴다. 여기서는 **원본 시각** 구간마다 확대 화면을 따로 만들어
원본 위에 덮는다(bake_builds.py 와 같은 방식). 컷 계획(keep_ranges)은 그대로 쓴다.

  확대 배율  Z = min(0.9*1920/폭, 0.9*1080/높이, 최대배율)  (관심 영역이 화면의 90% 안쪽)
  보이는 창  1920/Z x 1080/Z, 관심 영역 한가운데. 화면 밖으로 나가면 안쪽으로 민다.
  움직임     구간 시작 ramp 초 동안 전체 화면 → 창, 끝 ramp 초 동안 창 → 전체 화면 (ease in-out)

계획 파일 (시각은 원본 파일 기준 초):
  {"source": ".../ep03_소재.mp4", "out": ".../ep03_소재_빌드.mp4",
   "zooms": [{"src": [5340.89, 5395.36], "rect": [390,150,1330,390], "max": 2.0,
              "ramp": 0.4, "ramp_in_at": 5340.89, "ramp_out_at": 5394.96, "why": "..."}]}
  ramp_in_at / ramp_out_at 은 확대가 움직이기 시작하는 시각. 컷으로 잘리는 곳이면 움직임이
  안 보이므로 남는 블록 안에 둔다(zoom_plan 쪽에서 정한다). 없으면 src 양 끝.

강조 박스가 확대 구간 안에 있으면 `box_in_zoom()` 으로 좌표를 옮긴다(확대가 멈춰 있는 동안만).

사용: python bake_zoom.py <계획.json> [--only 0,2] [--preview]
     --preview 는 구간마다 확대가 다 된 순간의 한 장을 _zoom_preview_N.jpg 로 남기고 끝낸다.
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import cv2
import numpy as np

FPS = 30
W, H = 1920, 1080


def q(t):
    return round(t * FPS) / FPS


def window(rect, zmax=2.0):
    """관심 영역 → (배율, 창 왼쪽 위 x, y)."""
    x0, y0, x1, y1 = rect
    z = min(0.9 * W / (x1 - x0), 0.9 * H / (y1 - y0), zmax)
    z = max(z, 1.0)
    ww, wh = W / z, H / z
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    left = min(max(cx - ww / 2, 0), W - ww)
    top = min(max(cy - wh / 2, 0), H - wh)
    return z, left, top


def ease(p):
    p = min(max(p, 0.0), 1.0)
    return p * p * (3 - 2 * p)


def progress(t, zm):
    """t(원본 초)에서 확대 진행도 0~1."""
    r = zm.get("ramp", 0.4)
    a_in = zm.get("ramp_in_at", zm["src"][0])
    a_out = zm.get("ramp_out_at", zm["src"][1] - r)
    if t < a_in + r:
        return ease((t - a_in) / r)
    if t >= a_out:
        return 1.0 - ease((t - a_out) / r)
    return 1.0


def box_in_zoom(rect, zm):
    """확대가 멈춰 있는 동안 원본 좌표 상자 → 화면 좌표 상자."""
    z, left, top = window(zm["rect"], zm.get("max", 2.0))
    x0, y0, x1, y1 = rect
    out = [(x0 - left) * z, (y0 - top) * z, (x1 - left) * z, (y1 - top) * z]
    return [int(round(min(max(v, 0), W if k % 2 == 0 else H))) for k, v in enumerate(out)]


def hold_range(zm):
    r = zm.get("ramp", 0.4)
    return (zm.get("ramp_in_at", zm["src"][0]) + r, zm.get("ramp_out_at", zm["src"][1] - r))


def affine(p, zm):
    z, left, top = window(zm["rect"], zm.get("max", 2.0))
    s = 1 + (z - 1) * p
    ox, oy = left * p, top * p          # 창 왼쪽 위가 (0,0) → (left,top) 로 움직인다
    # 보이는 창 = [ox, ox + W/s] x [oy, oy + H/s] (p=1 이면 창과 같다)
    # 창의 오른쪽 끝이 화면 밖으로 나가지 않게 한다
    ox = min(ox, W - W / s)
    oy = min(oy, H - H / s)
    return np.float32([[s, 0, -ox * s], [0, s, -oy * s]])


def zoom_clip(src, zm, out):
    a, b = q(zm["src"][0]), q(zm["src"][1])
    dec = subprocess.Popen(["ffmpeg", "-v", "error", "-ss", f"{a:.4f}", "-i", src, "-t", f"{b - a:.4f}",
                            "-an", "-f", "rawvideo", "-pix_fmt", "bgr24", "-r", str(FPS), "-"],
                           stdout=subprocess.PIPE)
    enc = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24",
                            "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-c:v", "libx264",
                            "-preset", "veryfast", "-crf", "14", "-pix_fmt", "yuv420p", str(out)],
                           stdin=subprocess.PIPE)
    n = 0
    while True:
        buf = dec.stdout.read(W * H * 3)
        if len(buf) < W * H * 3:
            break
        f = np.frombuffer(buf, np.uint8).reshape(H, W, 3)
        t = a + n / FPS
        p = progress(t, zm)
        if p > 0.001:
            f = cv2.warpAffine(f, affine(p, zm), (W, H), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
        enc.stdin.write(np.ascontiguousarray(f).tobytes())
        n += 1
    enc.stdin.close()
    enc.wait()
    dec.wait()
    return a, a + n / FPS


def preview(src, zm, path):
    t = sum(hold_range(zm)) / 2
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.3f}", "-i", src, "-frames:v", "1",
                          "-f", "rawvideo", "-pix_fmt", "bgr24", "-"], capture_output=True, check=True).stdout
    f = np.frombuffer(raw, np.uint8).reshape(H, W, 3)
    g = cv2.warpAffine(f, affine(1.0, zm), (W, H), flags=cv2.INTER_CUBIC)
    cv2.imencode(".jpg", cv2.resize(g, (960, 540)))[1].tofile(str(path))


def bake(plan, only=None):
    src, out = plan["source"], plan["out"]
    zooms = [z for i, z in enumerate(plan["zooms"]) if not only or i in only]
    tmp = Path(tempfile.mkdtemp(prefix="zoom_"))
    clips = []
    for i, zm in enumerate(zooms):
        f = tmp / f"zoom_{i:02d}.mp4"
        a, b = zoom_clip(src, zm, f)
        z, _, _ = window(zm["rect"], zm.get("max", 2.0))
        clips.append((f, a, b))
        print(f"  확대 {i} {a:9.3f}~{b:9.3f} x{z:.2f} {zm.get('why', '')}", flush=True)
    args = ["ffmpeg", "-v", "error", "-y", "-i", src]
    for f, a, b in clips:
        args += ["-itsoffset", f"{a:.4f}", "-i", str(f)]
    fl, prev = [], "0:v"
    for k, (f, a, b) in enumerate(clips, 1):
        fl.append(f"[{prev}][{k}:v]overlay=eof_action=pass:enable='between(t,{a:.4f},{b - 0.001:.4f})'[v{k}]")
        prev = f"v{k}"
    script = tmp / "filter.txt"
    script.write_text(";\n".join(fl), encoding="utf-8")
    args += ["-/filter_complex", str(script), "-map", f"[{prev}]", "-map", "0:a",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "17", "-r", str(FPS),
             "-pix_fmt", "yuv420p", "-c:a", "copy", "-movflags", "+faststart", out]
    subprocess.run(args, check=True)
    for f, _, _ in clips:
        f.unlink(missing_ok=True)
    return out, len(clips)


if __name__ == "__main__":
    plan = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    only = None
    if "--only" in sys.argv:
        only = {int(x) for x in sys.argv[sys.argv.index("--only") + 1].split(",")}
    if "--preview" in sys.argv:
        d = Path(sys.argv[1]).parent
        for i, zm in enumerate(plan["zooms"]):
            if not only or i in only:
                preview(plan.get("preview_source", plan["source"]), zm, d / f"_zoom_preview_{i}.jpg")
        sys.exit(0)
    o, n = bake(plan, only)
    print(f"확대 {n}개 → {o}")
