# -*- coding: utf-8 -*-
"""1차시가 쓴 마스크를 2차시에 옮긴다. 두 가지 용도가 있다.

**가리기(hide).** 1차시는 화면 공유 구간의 우상단 '업그레이드' 광고 버튼을
반전 직사각형 마스크로 지웠다(76개, 전부 같은 자리). 2차시에도 같은 버튼이
찍혀 있다. 지정한 **원본 시각** 구간에 걸치는 비디오 세그먼트에만 붙인다 —
슬라이드 구간에 붙이면 슬라이드 모서리가 뚫린다.

**확대(zoom).** 1차시는 화면 일부를 직사각형으로 잘라 1.05~2.28배로 키워
보여줬다(39개). 글씨가 작은 화면 공유 구간에 쓴다.

좌표 규약은 1차시 값에서 역산했다:
  마스크 config 의 centerX/centerY 는 캔버스 절반을 1 로 보는 좌표(y 위가 +),
  width/height 는 화면 대비 비율.
  **세그먼트 transform = -마스크중심 x 배율** 이면 잘라낸 부분이 화면 한가운데
  온다. 1차시 02:50.8 에서 검증했다(계산 -0.556,+0.871 / 실제 -0.538,+0.886).

계획 파일 형식:
  {"draft": "2차시_효과_v2(1)",
   "hide": [{"src": [1620, 1659], "why": "..."}],
   "zoom": [{"t": 246.0, "dur": 21.8, "rect": [700,300,1600,800], "fill": 0.85,
             "why": "..."}]}
  hide.src 는 **원본 mp4 시각(초)**, zoom.t 는 **편집본 시각(초)**,
  zoom.rect 는 1920x1080 기준 픽셀.

사용: python src/apply_mask.py <계획.json> <참조 1차시 드래프트> [--dry]
"""
import copy
import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from draft_doctor import contents, resolve  # noqa: E402
from port_effects import capcut_running, localize  # noqa: E402

US = 1_000_000


def uid():
    return str(uuid.uuid4()).upper()


def reference(ref_draft, invert):
    """1차시에서 반전/비반전 직사각형 마스크를 하나 가져온다."""
    d = json.loads(contents(resolve(ref_draft))[0].read_text(encoding="utf-8"))
    for m in d["materials"].get("common_mask") or []:
        cfg = m.get("config") or {}
        if m.get("name") == "직사각형" and bool(cfg.get("invert")) == invert:
            return localize(m)
    raise SystemExit(f"{ref_draft} 에서 invert={invert} 직사각형 마스크를 못 찾았습니다")


def make_mask(base, cx, cy, w, h, invert):
    m = copy.deepcopy(base)
    m["id"] = uid()
    cfg = dict(m.get("config") or {})
    cfg.update({"centerX": cx, "centerY": cy, "width": w, "height": h,
                "invert": invert, "rotation": 0.0})
    m["config"] = cfg
    return m


def seg_source(s):
    st = s.get("source_timerange") or {}
    a = st.get("start", 0) / US
    return a, a + st.get("duration", 0) / US


def patch(path, plan, hide_base, zoom_base, n_expect=None):
    d = json.loads(path.read_text(encoding="utf-8"))
    cc = d.get("canvas_config") or {}
    W, H = cc.get("width", 1920), cc.get("height", 1080)
    vt = [t for t in d["tracks"] if t["type"] == "video"][0]
    segs = sorted(vt["segments"], key=lambda s: s["target_timerange"]["start"])
    if n_expect is not None and len(segs) != n_expect:
        return None
    masks = d["materials"].setdefault("common_mask", [])
    old = {m["id"] for m in masks if m.get("_lecture_autocut")}
    masks[:] = [m for m in masks if not m.get("_lecture_autocut")]
    for s in segs:                       # 우리가 전에 붙인 것만 떼어낸다
        refs = s.get("extra_material_refs") or []
        if refs:
            s["extra_material_refs"] = [r for r in refs if r not in old]

    n_hide = n_zoom = 0
    for it in plan.get("hide", []):
        a, b = it["src"]
        cfg = hide_base.get("config") or {}
        for s in segs:
            sa, sb = seg_source(s)
            if sb <= a or sa >= b:       # 겹치지 않음
                continue
            m = make_mask(hide_base, cfg.get("centerX"), cfg.get("centerY"),
                          cfg.get("width"), cfg.get("height"), True)
            m["_lecture_autocut"] = True
            masks.append(m)
            s.setdefault("extra_material_refs", []).append(m["id"])
            n_hide += 1

    for it in plan.get("zoom", []):
        x0, y0, x1, y1 = it["rect"]
        cx = ((x0 + x1) / 2 - W / 2) / (W / 2)
        cy = (H / 2 - (y0 + y1) / 2) / (H / 2)
        w, h = (x1 - x0) / W, (y1 - y0) / H
        fill = it.get("fill", 0.85)
        sc = round(min(fill / w, fill / h), 3)
        # 확대도 **원본 시각**으로 잡는다. 편집본 시각에 박으면 앞에 오프닝이
        # 붙거나 컷이 바뀔 때 엉뚱한 화면을 확대한다.
        a0, b0 = it["src"]
        for s in segs:
            sa, sb = seg_source(s)
            if sb <= a0 or sa >= b0:
                continue
            m = make_mask(zoom_base, cx, cy, w, h, False)
            m["_lecture_autocut"] = True
            masks.append(m)
            s.setdefault("extra_material_refs", []).append(m["id"])
            s["clip"] = dict(s.get("clip") or {},
                             scale={"x": sc, "y": sc},
                             transform={"x": -cx * sc, "y": -cy * sc})
            n_zoom += 1

    path.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    return (n_hide, n_zoom), len(segs)


def run(plan_path, ref_draft, dry=False):
    plan = json.loads(Path(plan_path).read_text(encoding="utf-8"))
    hide_base = reference(ref_draft, True)
    zoom_base = reference(ref_draft, False)
    hc = hide_base.get("config") or {}
    print(f"가리기 마스크: 중심({hc.get('centerX'):.3f},{hc.get('centerY'):.3f}) "
          f"폭{hc.get('width'):.3f} 높이{hc.get('height'):.3f}  "
          f"= 캔버스 x{960 + hc.get('centerX') * 960 - hc.get('width') * 960:.0f}"
          f"~{960 + hc.get('centerX') * 960 + hc.get('width') * 960:.0f}")
    for it in plan.get("hide", []):
        a, b = it["src"]
        print(f"  가리기 원본 {int(a//60):02d}:{a % 60:04.1f}~"
              f"{int(b//60):02d}:{b % 60:04.1f}  {it.get('why', '')}")
    for it in plan.get("zoom", []):
        a, b = it["src"]
        print(f"  확대 원본 {int(a//60):02d}:{a % 60:04.1f}~"
              f"{int(b//60):02d}:{b % 60:04.1f}  {it['rect']}  {it.get('why', '')}")
    if dry:
        return
    if capcut_running():
        raise SystemExit("캡컷이 실행 중입니다. 완전히 종료한 뒤 다시 실행하세요.")
    root = resolve(plan["draft"])
    print(f"대상 폴더: {root}")
    files = contents(root)
    (nh, nz), n_seg = patch(files[0], plan, hide_base, zoom_base)
    for f in files[1:]:
        patch(f, plan, hide_base, zoom_base, n_expect=n_seg)
    print(f"가리기 {nh}개 / 확대 {nz}개 세그먼트에 적용 (사본 {len(files)}벌)")


def main(argv):
    run(argv[0], argv[1], dry="--dry" in argv)


if __name__ == "__main__":
    main(sys.argv[1:])
