# -*- coding: utf-8 -*-
"""드래프트의 강조 도형을 실제 화면 위에 그려 본다.

캡컷의 `clip.transform` 은 캔버스 절반을 1 로 보는 정규화 좌표다(추정).
129개를 옮겨 붙이기 전에 그 해석이 맞는지 눈으로 확인해야 한다 — 틀리면
전부 엉뚱한 자리에 놓인다. 1차시 편집본의 한 시각을 골라 그 화면을 뽑고
그 위에 도형을 그린다. 슬라이드 요소에 딱 맞으면 해석이 맞는 것이다.

사용: python src/preview_overlay.py <드래프트> <편집본 시각(초)> <출력.png>
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from learn_from_edit import draft_content_path  # noqa: E402

US = 1_000_000


def load(draft):
    return json.loads(draft_content_path(draft).read_text(encoding="utf-8"))


def resolve_path(path, draft):
    """캡컷은 드래프트 안에 든 소재를 `##_draftpath_placeholder_<GUID>_##/...`
    로 적어 둔다. 폴더를 옮겨도 깨지지 않게 하려는 것이다. 실제 파일을
    읽으려면 드래프트 최상위 폴더로 되돌려야 한다."""
    if "_draftpath_placeholder_" not in path:
        return path
    root = draft_content_path(draft).parent
    while root.parent != root and not (root / "materials").is_dir():
        root = root.parent
    tail = path.split("_##", 1)[1].lstrip("/\\")
    return str(root / tail)


def frame_at(d, t, out_png, w, h, draft):
    """편집본 시각 t 의 화면을 원본 소재에서 뽑는다.

    위에 얹은 슬라이드 덮개(`overlay_slides.py`)가 있으면 그것이 실제로 보이는
    화면이다. 덮개를 무시하면 프리뷰가 옛 화면을 보여줘 고친 걸 못 본다.
    """
    vids = {m["id"]: m for m in d["materials"]["videos"]}
    over = [x for x in d["tracks"]
            if x.get("name") == "lecture_autocut_slide_overlay"]
    vt = [x for x in d["tracks"] if x["type"] == "video"][0]
    for ot in over:
        for s in ot.get("segments") or []:
            a = s["target_timerange"]["start"] / US
            b = a + s["target_timerange"]["duration"] / US
            if a <= t < b:
                vt = ot
                break
    for s in sorted(vt["segments"], key=lambda x: x["target_timerange"]["start"]):
        a = s["target_timerange"]["start"] / US
        b = a + s["target_timerange"]["duration"] / US
        if not (a <= t < b):
            continue
        m = vids.get(s["material_id"])
        src = (s.get("source_timerange") or {}).get("start", 0) / US + (t - a)
        path = resolve_path(m.get("path") or "", draft)
        if not Path(path).exists():
            raise SystemExit(f"소재 파일이 없습니다: {path}")
        cmd = ["ffmpeg", "-v", "error"]
        if m.get("type") == "photo":
            cmd += ["-i", path]
        else:
            cmd += ["-ss", f"{src:.2f}", "-i", path, "-frames:v", "1"]
        cmd += ["-vf", f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
                       f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:black",
                "-y", str(out_png)]
        subprocess.run(cmd, check=True)
        return m.get("material_name")
    raise SystemExit(f"{t}초에 해당하는 비디오 세그먼트가 없습니다")


def stickers_at(d, t, draft):
    """그 시각에 떠 있는 스티커를 실제 이미지째로 돌려준다.

    스티커는 도형과 배율 규칙이 다르다 — `shape_size` 가 없고 원본 이미지에
    `clip.scale` 을 곱해 그린다. 그래서 캡컷 캐시에 받아둔 실제 파일을 읽어
    그대로 합성한다. 크기를 짐작하지 않는다.
    """
    stk = {m["id"]: m for m in d["materials"].get("stickers") or []}
    out = []
    for tr in d["tracks"]:
        if tr["type"] != "sticker":
            continue
        for s in tr.get("segments") or []:
            m = stk.get(s.get("material_id"))
            if not m:
                continue
            a = s["target_timerange"]["start"] / US
            b = a + s["target_timerange"]["duration"] / US
            if not (a <= t < b):
                continue
            c = s.get("clip") or {}
            tf, sc = c.get("transform") or {}, c.get("scale") or {}
            out.append({"path": resolve_path(m.get("path") or "", draft),
                        "x": tf.get("x", 0), "y": tf.get("y", 0),
                        "sx": sc.get("x", 1), "sy": sc.get("y", 1),
                        "name": m.get("name")})
    return out


def shapes_at(d, t):
    """그 시각에 떠 있는 사각형들을 픽셀 좌표로 돌려준다."""
    shp = {m["id"]: m for m in d["materials"].get("shapes", [])}
    out = []
    for tr in d["tracks"]:
        if tr["type"] != "sticker":
            continue
        for s in tr.get("segments") or []:
            m = shp.get(s.get("material_id"))
            if not m:
                continue
            a = s["target_timerange"]["start"] / US
            b = a + s["target_timerange"]["duration"] / US
            if not (a <= t < b):
                continue
            c = s.get("clip") or {}
            tf, sc = c.get("transform") or {}, c.get("scale") or {}
            out.append({"size": m["shape_size"], "color": m.get("border_color"),
                        "x": tf.get("x", 0), "y": tf.get("y", 0),
                        "sx": sc.get("x", 1), "sy": sc.get("y", 1),
                        "bw": m.get("border_width", 4.0),
                        "round": (m.get("roundness") or [5.0])[0]})
    return out


def to_px(box, W, H, k=2.64):
    """정규화 좌표 -> 픽셀 사각형.

    `clip.transform` 은 캔버스 절반을 1 로 보는 좌표다(중심 일치 확인됨).
    `shape_size` 는 픽셀이 아니라 캡컷 내부 단위이고 **1920x1080 에서 배율은
    2.4** 다(= 캔버스를 800x450 으로 보는 설계 공간). 세그먼트에 배율 필드가
    더 없음을 전체 덤프로 확인한 뒤, 1차시 116초의 카드 강조 3개를 실제
    슬라이드에 겹쳐 맞춰 구한 값이다.
    """
    w = box["size"][0] * box["sx"] * k
    h = box["size"][1] * box["sy"] * k
    cx = W / 2 + box["x"] * (W / 2)
    cy = H / 2 - box["y"] * (H / 2)
    return (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)


def run(draft, t, out_png, k=2.64):
    """캡컷이 실제로 그리는 모양 그대로 그린다.

    예전에는 ffmpeg `drawbox` 로 각진 4픽셀 선을 그렸다. 그건 캡컷 렌더가
    아니라 진단용 선이라서, 프리뷰만 보고 "테두리 굵기와 모서리 라운드가
    1차시와 다르다" 는 오해가 나왔다. 실제 도형은 `border_width`(설계 단위)
    와 `roundness` 를 쓰는 둥근 사각형이므로 그대로 재현한다.
    """
    from PIL import Image, ImageDraw       # 이 도구에서만 쓴다
    t, k = float(t), float(k)
    d = load(draft)
    cc = d.get("canvas_config") or {}
    W, H = cc.get("width", 1920), cc.get("height", 1080)
    tmp = Path(tempfile.gettempdir()) / "_overlay_src.png"
    name = frame_at(d, t, tmp, W, H, draft)
    boxes = shapes_at(d, t)
    if not boxes:
        print(f"{t}초에 강조 도형이 없습니다 (화면: {name})")
    im = Image.open(tmp).convert("RGB")
    for st in stickers_at(d, t, draft):
        p = Path(st["path"])
        if p.is_dir():
            # 캡컷은 스티커 경로를 **폴더**로 적는다. 알맹이는 그 안의
            # `final.gif` 다(초록 체크는 움직이는 스티커라 gif 다).
            # 스티커 종류마다 알맹이 파일 이름이 다르다 — 움직이는 스티커는
            # `final.gif`, 숫자·이모지 스티커는 `emoji.png` 다.
            p = next((q for q in (p / "final.gif", p / "final.png",
                                  p / "emoji.png") if q.exists()), p)
        if not p.is_file():
            print(f"   [스티커 파일 없음] {st['name']}  {p}")
            continue
        s = Image.open(p)
        # 움직이는 스티커는 첫 프레임이 비어 있다(그려지는 연출이라서).
        # 다 그려진 모습을 보려면 마지막 프레임으로 감는다.
        try:
            n = getattr(s, "n_frames", 1)
            if n > 1:
                s.seek(n - 1)
        except Exception:
            pass
        s = s.convert("RGBA")
        w = max(1, round(s.width * st["sx"]))
        h = max(1, round(s.height * st["sy"]))
        s = s.resize((w, h))
        cx = W / 2 + st["x"] * (W / 2)
        cy = H / 2 - st["y"] * (H / 2)
        im.paste(s, (round(cx - w / 2), round(cy - h / 2)), s)
        print(f"   스티커 {st['name']}  중심 {cx:.0f},{cy:.0f}  크기 {w}x{h}")
    dr = ImageDraw.Draw(im)
    for b in boxes:
        x0, y0, x1, y1 = to_px(b, W, H, k)
        wpx = max(1, round(b["bw"] * k * b["sx"]))
        rad = max(0, round(b["round"] * k * b["sx"]))
        rad = min(rad, int(min(x1 - x0, y1 - y0) / 2))
        dr.rounded_rectangle([x0, y0, x1, y1], radius=rad,
                             outline=b["color"] or "#ff0000", width=wpx)
    im.save(out_png)
    print(f"{t:.1f}초  화면={name}  도형 {len(boxes)}개  k={k}  -> {out_png}")
    for b in boxes:
        print("   {:.0f},{:.0f} ~ {:.0f},{:.0f}  {}  획 {:.0f}px 라운드 {:.0f}px"
              .format(*to_px(b, W, H, k), b["color"],
                      b["bw"] * k * b["sx"], b["round"] * k * b["sx"]))


if __name__ == "__main__":
    run(*sys.argv[1:5])
