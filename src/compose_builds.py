# -*- coding: utf-8 -*-
"""녹화 화면 + 파워포인트 바탕 = 애니메이션 단계 화면.

파워포인트가 교안 글꼴을 못 그리는 경우가 있다(캔바 글꼴을 품은 pptx 를 이 PC 에서 열 때).
그래서 **보이는 글자는 녹화 화면 그대로** 쓰고, 아직 나오지 않은 항목 자리만 파워포인트가
그린 바탕(그 항목을 숨긴 상태)으로 덮는다. 바탕은 녹화와 밝기가 조금 다르므로 숨길 자리 바로
바깥 띠에서 잰 차이를 한 값으로 더해 붙인다. 이음매는 2px 로 부드럽게 섞는다.

  깨끗한 녹화 화면: 그 장이 떠 있는 동안의 프레임 여러 장의 중앙값(움직이는 커서를 지운다)
  숨길 자리: 아직 안 나온 묶음의 도형 테두리 + 12px (이미 나온 묶음과 겹치는 곳은 뺀다)

사용: python compose_builds.py <원본.pptx> <계획.json> <렌더폴더> <구간.json> <원본영상> <출력폴더>
"""
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter
from pptx import Presentation

# 숨길 자리 = 도형 테두리 + 12px. 녹화에는 카드 밖 7px 쯤까지 옅은 그림자가 있어 8px 이면 흐리게 섞는
# 가장자리(2px)에 그림자가 걸려 카드 모양 선이 남았다(2026-09-24)
PAD = 12


def shape_boxes(prs, idx):
    s = prs.slides[idx - 1]
    W, H = prs.slide_width, prs.slide_height
    out = {}
    for sh in s.shapes:
        x0, y0 = sh.left / W * 1920, sh.top / H * 1080
        out[sh.shape_id] = (x0, y0, x0 + sh.width / W * 1920, y0 + sh.height / H * 1080,
                            sh.has_text_frame and bool(sh.text_frame.text.strip()))
    return out


def mask_of(boxes, ids, pad=PAD, shape=(1080, 1920)):
    m = np.zeros(shape, bool)
    for i in ids:
        x0, y0, x1, y1, _ = boxes[i]
        m[max(0, int(y0) - pad):min(shape[0], int(np.ceil(y1)) + pad),
          max(0, int(x0) - pad):min(shape[1], int(np.ceil(x1)) + pad)] = True
    return m


def clean_frame(video, times, out_png):
    """여러 시각 프레임의 중앙값."""
    frames = []
    for t in times:
        p = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.3f}", "-i", video, "-frames:v", "1",
                            "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True)
        a = np.frombuffer(p.stdout, dtype=np.uint8)
        if a.size == 1920 * 1080 * 3:
            frames.append(a.reshape(1080, 1920, 3))
    med = np.median(np.stack(frames), axis=0).astype(np.uint8)
    Image.fromarray(med).save(out_png)
    return med.astype(np.float32), len(frames)


def compose(prs, slide, steps, render_dir, rec, out_dir):
    boxes = shape_boxes(prs, slide)
    content = [i for g in steps for i in g]
    # 색 맞춤 표본: 어떤 묶음·글자에도 안 걸리는 곳
    busy = mask_of(boxes, content, 24) | mask_of(boxes, [i for i, b in boxes.items() if b[4]], 12)
    sample = ~busy
    files = []
    n = len(steps)
    texts = [i for i, b in boxes.items() if b[4] and i not in content]
    ren_full = np.asarray(Image.open(Path(render_dir) / f"S{slide:02d}_{n}.png").convert("RGB"),
                          dtype=np.float32)
    for k in range(n + 1):
        ren = np.asarray(Image.open(Path(render_dir) / f"S{slide:02d}_{k}.png").convert("RGB"),
                         dtype=np.float32)
        hidden_ids = [i for g in steps[k:] for i in g]
        shown_ids = [i for g in steps[:k] for i in g]
        # 색 맞춤은 **숨길 자리 전체에 한 값**을 더한다. 숨길 자리 바로 바깥 띠(보이는 도형·글자는 뺀다)에서
        # 녹화와 렌더의 차이(중앙값)를 잰다.
        # - 화면 전체 직선 맞춤만 쓰면 흰색이 255→254 로 어두워져 숨긴 자리에 흐린 네모가 비친다(2026-09-23)
        # - 묶음마다 따로 맞추면 어떤 묶음은 255, 어떤 묶음은 254 가 되어 그 경계가 도형 테두리
        #   (카드·탭 모양)를 따라 1~2단계 선으로 남는다. 인코딩하면 5단계까지 벌어져 보인다(2026-09-24)
        ring = (mask_of(boxes, hidden_ids, PAD + 14) & ~mask_of(boxes, hidden_ids, PAD + 4)
                & ~mask_of(boxes, shown_ids, 4) & ~mask_of(boxes, texts, 4))
        if ring.sum() < 200:
            ring = sample
        off = np.median(rec[ring] - ren[ring], axis=0)
        ren_m = np.clip(ren + off, 0, 255)
        hide = mask_of(boxes, hidden_ids)
        shown = mask_of(boxes, shown_ids, 0)
        if k < n and shown.any():
            # 이미 나온 도형의 테두리 상자가 숨길 도형에 걸쳐 있으면(글상자 틀이 글자보다 훨씬 클 때)
            # 그 겹친 곳 가운데 **숨길 도형이 실제로 그려지는 곳**은 숨긴다. 전체 렌더와 이 단계 렌더가
            # 다른 곳이 숨길 도형이 그려지는 곳이다. S07 에서 글상자 틀 아래로 프롬프트 상자 윗부분
            # 75px 가 먼저 드러났다(2026-09-24)
            draws = (np.abs(ren - ren_full).max(axis=2) > 8).astype(np.uint8) * 255
            draws = np.asarray(Image.fromarray(draws).filter(ImageFilter.MaxFilter(9))) > 0
            shown = shown & ~draws
        m = (hide & ~shown).astype(np.float32)
        m = np.asarray(Image.fromarray((m * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(2)),
                       dtype=np.float32)[..., None] / 255.0
        img = rec * (1 - m) + ren_m * m
        f = Path(out_dir) / f"S{slide:02d}_{k}.png"
        # 반올림한다. 버리면(astype) 섞는 가장자리의 254.9 가 254 로 떨어져 선이 된다
        Image.fromarray(np.clip(np.rint(img), 0, 255).astype(np.uint8)).save(f)
        files.append(str(f))
    return files


def main(argv):
    pptx, plan_p, render_dir, spans_p, video, out_dir, keep_p = argv[:7]
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    plan = json.loads(Path(plan_p).read_text(encoding="utf-8"))
    spans = json.loads(Path(spans_p).read_text(encoding="utf-8"))
    keep = json.loads(Path(keep_p).read_text(encoding="utf-8"))["keep_ranges"]
    prs = Presentation(pptx)
    made = {}
    for key, steps in plan["slides"].items():
        slide = int(key)
        sp = [s for s in spans if s["slide"] == slide]
        if not sp:
            continue
        # 그 장이 떠 있는 동안, **남는 구간 안에서만** 고르게 7장
        # (구간 사이 잘려 나간 곳에는 다른 화면이 떠 있을 수 있다)
        parts = [(max(s["a"], p) + 0.1, min(s["b"], q) - 0.1) for s in sp for p, q in keep
                 if q > s["a"] and p < s["b"]]
        parts = [(x, y) for x, y in parts if y > x]
        tot = sum(y - x for x, y in parts)
        ts = []
        for j in range(7):
            r = tot * (j + 0.5) / 7
            for x, y in parts:
                if r <= y - x:
                    ts.append(x + r)
                    break
                r -= y - x
        rec, nf = clean_frame(video, ts, Path(out_dir) / f"S{slide:02d}_녹화.png")
        made[slide] = compose(prs, slide, steps, render_dir, rec, out_dir)
        print(f"S{slide:02d}: 녹화 {nf}장 중앙값 · 단계 화면 {len(made[slide])}개")
    return made


if __name__ == "__main__":
    main(sys.argv[1:])
