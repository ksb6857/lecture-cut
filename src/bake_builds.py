# -*- coding: utf-8 -*-
"""녹화 원본에 슬라이드 단계 화면을 구워 넣는다 — 말하는 순서대로 항목이 나타나게.

녹화는 애니메이션 없이 찍혔다. `render_builds.py` 가 뽑은 단계별 화면을, 그 장이
떠 있던 **원본 시각** 구간에 덮고, 항목을 말하기 시작하는 시각에 0.5초 동안
밝기 변화(페이드)로 다음 단계로 넘긴다. 단계 화면끼리는 새 항목 말고 픽셀이 같으므로
전체를 겹쳐 페이드해도 새 항목만 서서히 나타난다(파워포인트의 밝기 변화와 같다).

**캡컷 스키마로 애니메이션을 넣지 않고 원본에 굽는다.** 블러·크로마키와 같은 방식이다.
원본과 시각이 1:1 로 같은 새 파일을 만들므로 컷 계획(keep_ranges)을 그대로 쓴다.
장면 전환(B 페이드)이 슬라이드 쪽에도 제대로 걸린다(덮개 트랙이면 전환을 가린다).

계획 파일 (시각은 원본 파일 기준 초):
  {"source": ".../ep03_소재.mp4", "out": ".../ep03_소재_빌드.mp4", "fade": 0.5,
   "spans": [{"slide": 6, "a": 610.2, "b": 700.1,
              "images": [".../S06_0.png", ".../S06_1.png", ...],
              "reveal": [612.4, 640.8, ...]}]}
  images 는 단계 0(바탕)부터. reveal[k] 는 images[k+1] 로 넘어가기 시작하는 시각.
  a·b 는 그 장이 화면에 떠 있는 첫·끝 프레임 시각(프레임 경계로 맞춘다).
  "zooms": [...] 를 넣으면 bake_zoom.py 의 확대도 같은 판에 덮는다(형식은 bake_zoom.py).

사용: python bake_builds.py <계획.json> [--only 6,9] [--keep-clips]
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

FPS = 30


def q(t):
    """프레임 경계로 맞춘다."""
    return round(t * FPS) / FPS


def place_reveal(onset, keep, fade=0.5, tail=0.6):
    """항목을 말하기 시작하는 시각(onset)에 **다 보이도록** fade 만큼 먼저 나타나기 시작할 시각.

    video-use 의 '효과는 그 낱말을 말할 때 다 떠 있게' 원칙이다. 말과 동시에 페이드를 시작하면
    말을 시작하고 0.5초 뒤에야 항목이 다 보인다.
    - 앞당길 자리가 잘려 나간 곳이면 그 블록 시작 0.03초 뒤까지만 당긴다
    - onset 이 잘린 곳이거나 블록 끝 tail 초 안이면 페이드가 잘리므로 다음 블록 시작 0.03초 뒤로 민다
    keep 은 원본 시각 [[시작, 끝], ...].
    """
    for p, q in keep:
        if p <= onset < q:
            if q - onset >= tail:
                return round(max(p + 0.03, onset - fade), 3)
            break
    nxt = next((p for p, q in keep if p > onset), None)
    return round(nxt + 0.03, 3) if nxt is not None else onset


def span_clip(sp, out, fade=0.5):
    a, b = q(sp["a"]), q(sp["b"])
    D = b - a
    imgs = sp["images"]
    rv = [q(t) for t in sp.get("reveal", [])]
    if len(rv) != len(imgs) - 1:
        raise SystemExit(f"S{sp['slide']}: 단계 {len(imgs) - 1}개인데 시각이 {len(rv)}개")
    # 구간이 시작할 때 이미 나와 있는 단계(같은 장이 두 번째로 나올 때)는 처음부터 보인다
    k0 = sum(1 for t in rv if t <= a + 1e-6)
    later = [(t - a, imgs[k + 1]) for k, t in enumerate(rv) if a + 1e-6 < t < b - 0.05]
    seq = [imgs[k0]] + [f for _, f in later]
    args = ["ffmpeg", "-v", "error", "-y"]
    for f in seq:
        args += ["-loop", "1", "-framerate", str(FPS), "-t", f"{D:.4f}", "-i", str(f)]
    fl = [f"[0:v]scale=1920:1080,setsar=1,format=yuv420p[b0]"]
    prev = "b0"
    for k, (st, _) in enumerate(later, 1):
        fl.append(f"[{k}:v]scale=1920:1080,setsar=1,format=yuva420p,"
                  f"fade=t=in:st={st:.4f}:d={fade}:alpha=1[f{k}]")
        fl.append(f"[{prev}][f{k}]overlay=format=auto,format=yuv420p[b{k}]")
        prev = f"b{k}"
    args += ["-filter_complex", ";".join(fl), "-map", f"[{prev}]", "-t", f"{D:.4f}",
             "-r", str(FPS), "-c:v", "libx264", "-preset", "veryfast", "-crf", "14",
             "-pix_fmt", "yuv420p", str(out)]
    subprocess.run(args, check=True)
    return a, b


def bake(plan, only=None, keep_clips=False):
    src, out = plan["source"], plan["out"]
    spans = [s for s in plan["spans"] if not only or s["slide"] in only]
    tmp = Path(tempfile.mkdtemp(prefix="builds_"))
    clips = []
    for i, sp in enumerate(spans):
        f = tmp / f"span_{i:03d}_S{sp['slide']:02d}.mp4"
        a, b = span_clip(sp, f, plan.get("fade", 0.5))
        clips.append((f, a, b))
        print(f"  S{sp['slide']:02d} {a:9.3f}~{b:9.3f} 단계 {len(sp['images']) - 1}", flush=True)
    # 작은 글씨 확대(bake_zoom.py)도 같은 판에 덮는다. 따로 구우면 전체를 두 번 인코딩한다
    if plan.get("zooms") and not only:
        from bake_zoom import zoom_clip
        for i, zm in enumerate(plan["zooms"]):
            f = tmp / f"zoom_{i:02d}.mp4"
            a, b = zoom_clip(src, zm, f)
            clips.append((f, a, b))
            print(f"  확대 {a:9.3f}~{b:9.3f} {zm.get('why', '')}", flush=True)
    clips.sort(key=lambda c: c[1])
    # 덮개가 많으면 한 번에 다 못 받는다 — 필터 스크립트로 넘긴다
    args = ["ffmpeg", "-v", "error", "-y", "-i", src]
    for f, a, b in clips:
        args += ["-itsoffset", f"{a:.4f}", "-i", str(f)]
    fl, prev = [], "0:v"
    for k, (f, a, b) in enumerate(clips, 1):
        nxt = f"v{k}"
        fl.append(f"[{prev}][{k}:v]overlay=eof_action=pass:enable='between(t,{a:.4f},{b - 0.001:.4f})'[{nxt}]")
        prev = nxt
    script = tmp / "filter.txt"
    script.write_text(";\n".join(fl), encoding="utf-8")
    args += ["-/filter_complex", str(script), "-map", f"[{prev}]", "-map", "0:a",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "19", "-r", str(FPS),
             "-pix_fmt", "yuv420p", "-c:a", "copy", "-movflags", "+faststart", out]
    subprocess.run(args, check=True)
    if not keep_clips:
        for f, _, _ in clips:
            f.unlink(missing_ok=True)
    return out, len(clips)


if __name__ == "__main__":
    plan = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    only = None
    if "--only" in sys.argv:
        only = {int(x) for x in sys.argv[sys.argv.index("--only") + 1].split(",")}
    o, n = bake(plan, only, "--keep-clips" in sys.argv)
    print(f"덮개 {n}개 → {o}")
