# -*- coding: utf-8 -*-
"""계획 파일대로 강조 사각형을 드래프트에 넣는다.

1차시가 쓴 도형을 **통째로 복제**해서 크기·위치·색만 바꾼다. 캡컷 도형
material 에는 뜻을 모르는 필드가 많아 새로 지으면 조용히 깨진다
(CLAUDE.md 5번). 붙는 애니메이션도 1차시 것을 그대로 쓴다.

좌표 규약 (`preview_overlay.py` 에서 실측):
  transform = 캔버스 절반을 1 로 보는 정규화 좌표, y 는 위가 +
  shape_size = 픽셀 / 2.4

계획 파일 형식:
  {"draft": "2차시_효과_v1",
   "items": [{"t": 93.5, "dur": 6.0, "rect": [185,428,1737,502],
              "color": "red", "why": "의도 파악 행"}]}
  rect 는 1920x1080 기준 [x0,y0,x1,y1] 픽셀.

사용: python src/apply_highlights.py <계획.json> <참조 드래프트> [--dry]

참조 드래프트: 사람이 캡컷에서 직접 그린 사각형 도형이 든 드래프트. 도형·애니메이션을
통째로 복제한다. 어느 드래프트를 쓰는지는 프로젝트 폴더의 규격 문서에 적어 둔다.
"""
import copy
import json
import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from learn_from_edit import draft_content_path  # noqa: E402
from port_effects import capcut_running, localize  # noqa: E402
from timemap import resolve_item, timeline  # noqa: E402
from draft_root import DRAFTS  # noqa: E402,F401

US = 1_000_000
# shape_size -> 픽셀 배율. **캡컷 실제 렌더에서 역산한 값이다.**
#
# 처음엔 2.4 로 썼다(1920/800). 1차시 도형을 슬라이드 카드에 맞춰보고 얻은
# 값인데, 그게 순환논리였다 — "상자가 카드에 딱 맞는다"고 가정하고 배율을
# 맞췄지만 1차시 상자도 실은 카드보다 10% 크게 나가 있었다. 그래서 2.4 로
# 만든 상자가 캡컷에서는 표 밖으로 삐져나왔다(2026-08-17, 사용자가 두 번
# 지적함).
#
# 지금 값은 캡컷 화면 스크린샷에서 랜드마크(카드 테두리·⊖ 표식·표 좌우 끝)로
# 화면/캔버스 배율을 구한 뒤 렌더된 상자 폭을 재서 얻었다: 지정 1526px 이
# 1677px 로 그려졌다 = 1.099배. 2.4 x 1.099 = 2.638.
#
# **다시 어긋나 보이면 추측하지 말고 같은 방법으로 다시 재라.** 정지 프레임에
# 맞춰보는 방식은 캡컷 렌더러와 다르다.
K = 2.64
COLORS = {"red": "#ab0000", "green": "#4bab00"}
RENDER_INDEX = 14001          # 1차시가 도형에 쓴 값


def uid():
    return str(uuid.uuid4()).upper()


def reference(ref_draft):
    """1차시에서 사각형 도형 하나와 거기 붙은 애니메이션을 가져온다."""
    d = json.loads(draft_content_path(ref_draft).read_text(encoding="utf-8"))
    shp = {m["id"]: m for m in d["materials"].get("shapes") or []}
    anim = {m["id"]: m for m in d["materials"].get("material_animations") or []}
    for tr in d["tracks"]:
        if tr["type"] != "sticker":
            continue
        for s in tr.get("segments") or []:
            m = shp.get(s.get("material_id"))
            if not m:
                continue
            a = next((anim[r] for r in s.get("extra_material_refs") or []
                      if r in anim), None)
            return localize(m), localize(a), localize(s)
    raise SystemExit(f"{ref_draft} 에서 사각형 도형을 못 찾았습니다")


def base_scale(base_seg):
    """1차시가 도형 세그먼트에 쓴 배율. 캡컷은 테두리 굵기(`border_width`)도
    이 배율로 그리므로, 우리가 1.0 을 쓰면 같은 material 인데도 획이 1픽셀
    두꺼워져 1차시와 미묘하게 달라 보인다. 그래서 배율은 1차시 값을 그대로
    쓰고 `shape_size` 쪽에서 나눠 상쇄한다 — 크기는 지정한 픽셀 그대로,
    획과 모서리 라운드는 1차시와 똑같이."""
    sc = (base_seg.get("clip") or {}).get("scale") or {}
    return float(sc.get("x", 1.0)) or 1.0


def make_shape(base, rect, scale=1.0):
    x0, y0, x1, y1 = rect
    w, h = (x1 - x0) / K / scale, (y1 - y0) / K / scale
    m = copy.deepcopy(base)
    m["id"] = uid()
    m["shape_size"] = [w, h]
    m["custom_points"] = [-w / 2, h / 2, w / 2, h / 2,
                          w / 2, -h / 2, -w / 2, -h / 2]
    return m


def make_segment(base_seg, mat_id, rect, t, dur, W, H, anim_id, scale=1.0):
    x0, y0, x1, y1 = rect
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    s = copy.deepcopy(base_seg)
    s["id"] = uid()
    s["material_id"] = mat_id
    s["target_timerange"] = {"start": int(t * US), "duration": int(dur * US)}
    s["clip"] = dict(s.get("clip") or {}, scale={"x": scale, "y": scale},
                     transform={"x": (cx - W / 2) / (W / 2),
                                "y": (H / 2 - cy) / (H / 2)})
    s["extra_material_refs"] = [anim_id] if anim_id else []
    s["render_index"] = RENDER_INDEX
    return s


def patch(path, plan, base_m, base_a, base_s, n_expect=None):
    d = json.loads(path.read_text(encoding="utf-8"))
    cc = d.get("canvas_config") or {}
    W, H = cc.get("width", 1920), cc.get("height", 1080)
    vt = [t for t in d["tracks"] if t["type"] == "video"][0]
    if n_expect is not None and len(vt["segments"]) != n_expect:
        return None                       # 다른 버전의 사본 — 건드리지 않는다

    shapes = d["materials"].setdefault("shapes", [])
    anims = d["materials"].setdefault("material_animations", [])
    # 이 도구가 만든 트랙이 이미 있으면 지우고 다시 넣는다 (재실행 안전)
    d["tracks"] = [t for t in d["tracks"]
                   if t.get("name") != "lecture_autocut_highlights"]
    used = {t.get("track_render_index", 0) for t in d["tracks"]}
    track = {"attribute": 0, "flag": 0, "id": uid(),
             "is_default_name": False, "name": "lecture_autocut_highlights",
             "segments": [], "type": "sticker",
             "track_render_index": max(used, default=0) + 1}

    sc = base_scale(base_s)
    tl = timeline(d)
    skipped = 0
    for it in plan["items"]:
        pos = resolve_item(tl, it, 5.5)
        if pos is None:            # 그 대목이 잘려나갔다
            skipped += 1
            continue
        t, dur = pos
        m = make_shape(base_m, it["rect"], sc)
        m["border_color"] = COLORS.get(it.get("color", "red"),
                                       it.get("color"))
        shapes.append(m)
        aid = None
        if base_a:
            a = copy.deepcopy(base_a)
            a["id"] = uid()
            aid = a["id"]
            anims.append(a)
        track["segments"].append(make_segment(
            base_s, m["id"], it["rect"], t, dur, W, H, aid, sc))
    if skipped:
        print(f"  [건너뜀] {skipped}개 — 해당 대목이 편집본에 없다")

    d["tracks"].append(track)
    path.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    return len(track["segments"]), len(vt["segments"])


def run(plan_path, ref_draft, dry=False):
    plan = json.loads(Path(plan_path).read_text(encoding="utf-8"))
    base_m, base_a, base_s = reference(ref_draft)
    name = plan["draft"]
    print(f"계획 {len(plan['items'])}개 -> {name}")
    for it in plan["items"]:
        a = it.get("src", [it.get("t", 0)])[0]
        print(f"  원본 {int(a//60):02d}:{a % 60:04.1f} "
              f"{it.get('color', 'red'):5s} {it['rect']}  {it.get('why', '')}")
    if dry:
        return
    if capcut_running():
        raise SystemExit("캡컷이 실행 중입니다. 완전히 종료한 뒤 다시 실행하세요.")

    # 폴더 이름으로 직접 찾지 않는다 — 캡컷이 `(1)` 을 붙여 바꿔치면 조용히
    # 실패한다(2026-08-17에 실제로 이래서 적용이 안 된 채 넘어갔다).
    from draft_doctor import resolve, contents          # noqa: E402
    root = resolve(name)
    print(f"대상 폴더: {root}")
    files = contents(root)
    if not files:
        raise SystemExit(f"draft_content.json 이 없습니다: {root}")
    n, n_seg = patch(files[0], plan, base_m, base_a, base_s)
    for f in files[1:]:
        patch(f, plan, base_m, base_a, base_s, n_expect=n_seg)
    print(f"강조 {n}개 적용 (사본 {len(files)}벌)")


def main(argv):
    run(argv[0], argv[1], dry="--dry" in argv)


if __name__ == "__main__":
    main(sys.argv[1:])
