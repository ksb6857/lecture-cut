# -*- coding: utf-8 -*-
"""장면이 바뀌는 컷에 캡컷 장면전환을 넣는다.

**전환은 사람이 직접 넣은 드래프트에서 통째로 복제한다.** 스키마를 짓지 않는다.
사용자가 쓴 전환은 'B 페이드' 0.467초(is_overlap false) 하나다.
두 플랫폼 편집본 세 벌(41곳·25곳·16곳)에서 모두 같았다.

어디에 넣는가 — 사용자가 손으로 넣은 곳을 앞뒤 화면으로 대조해 얻었다(2026-09-23).

  넣는다     슬라이드 ↔ 실습 화면
             실습 중 다른 앱·다른 화면으로 넘어가는 컷(AI 채팅 → 웹앱 미리보기,
             웹앱 → 스프레드시트, 새로고침으로 빈 화면)
             파트 사이, 인트로 ↔ 오프닝 ↔ 본편 (납품 가이드에 있으면)
  안 넣는다  슬라이드 → 슬라이드 (사용자 지시)
             같은 앱 안에서 팝업이 뜨고 닫히거나 상태만 바뀌는 컷
             (한 납품본에서 화면 차이가 커도 안 넣은 18곳이 전부 이랬다)

실습 → 실습 은 화면 차이 수치로 안 갈린다(넣은 곳 2.2~88, 안 넣은 곳 최대 95).
내용을 보고 정한다. 계획 파일에 이유와 함께 적는다.

계획 파일 (원본 시각 기준 — 컷이 바뀌어도 다시 붙이면 제자리로 간다):
  {"draft": "ep03_러프컷",
   "ref": "<전환을 손으로 넣은 드래프트>",
   "cuts": [{"src_end": 90.44, "why": "오프닝 → 본연수"}, ...]}
  src_end = 전환이 붙을 컷의 **앞 클립이 끝나는 원본 시각**

사용: python apply_transitions.py <계획.json> [--dry]
"""
import copy
import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from draft_doctor import contents, resolve  # noqa: E402
from port_effects import capcut_running  # noqa: E402

US = 1_000_000
# 참조 드래프트가 없을 때 쓰는 값. 사용자가 3차시 v5 에 손으로 넣은 것 그대로다.
B_FADE = {
    "type": "transition", "name": "B 페이드",
    "effect_id": "6724239388189921806", "resource_id": "6724239388189921806",
    "duration": 466666, "is_overlap": False, "category_id": "25835",
    "category_name": "인기", "path": "", "platform": "all", "request_id": "",
    "third_resource_id": "",
}


def uid():
    return str(uuid.uuid4()).upper()


def reference(ref, name="B 페이드"):
    """사람이 넣은 전환 material 하나를 복제해 온다."""
    if not ref:
        return dict(B_FADE)
    d = json.loads(contents(resolve(ref))[0].read_text(encoding="utf-8"))
    for m in d["materials"].get("transitions") or []:
        if m.get("name") == name:
            return copy.deepcopy(m)
    print(f"  (참조 {ref} 에 '{name}' 이 없어 기본값을 쓴다)")
    return dict(B_FADE)


def main_track(d):
    return max((t for t in d["tracks"] if t["type"] == "video"), key=lambda t: len(t["segments"]))


def patch(path, cuts, base, n_expect=None, tol=0.06):
    d = json.loads(path.read_text(encoding="utf-8"))
    vt = main_track(d)
    segs = sorted(vt["segments"], key=lambda s: s["target_timerange"]["start"])
    if n_expect is not None and len(segs) != n_expect:
        return None                                   # 다른 버전의 사본 — 건드리지 않는다
    trs = d.setdefault("materials", {}).setdefault("transitions", [])
    have = {t["id"] for t in trs}
    done, missing = 0, []
    for c in cuts:
        k = next((i for i, s in enumerate(segs[:-1])
                  if abs((s["source_timerange"]["start"] + s["source_timerange"]["duration"]) / US
                         - c["src_end"]) < tol), None)
        if k is None:
            missing.append(c)
            continue
        refs = segs[k].setdefault("extra_material_refs", [])
        if any(r in have for r in refs):
            continue                                  # 이미 있으면 둔다
        m = copy.deepcopy(base)
        m["id"] = uid()
        trs.append(m)
        refs.append(m["id"])
        done += 1
    path.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    return done, len(segs), missing


def run(plan_path, dry=False):
    plan = json.loads(Path(plan_path).read_text(encoding="utf-8"))
    cuts = plan["cuts"]
    print(f"전환 {len(cuts)}곳 → {plan['draft']}")
    if dry:
        for c in cuts:
            print(f"  원본 {c['src_end']:9.2f}  {c.get('why', '')}")
        return
    if capcut_running():
        raise SystemExit("캡컷이 실행 중입니다. 완전히 종료한 뒤 다시 실행하세요.")
    base = reference(plan.get("ref"))
    files = contents(resolve(plan["draft"]))
    r = patch(files[0], cuts, base)
    n, n_seg, missing = r
    for f in files[1:]:
        patch(f, cuts, base, n_expect=n_seg)
    print(f"  '{base.get('name')}' {n}곳 적용 (사본 {len(files)}벌, 클립 {n_seg}개)")
    if missing:
        print(f"  [못 찾음] {len(missing)}곳 — 그 컷이 편집본에 없다: "
              + ", ".join(f"{c['src_end']:.2f}" for c in missing[:10]))
    return n


if __name__ == "__main__":
    run(sys.argv[1], dry="--dry" in sys.argv)
