# -*- coding: utf-8 -*-
"""검토 표시: 사람이 영상을 보며 정할 곳을 드래프트에 글자 트랙으로 붙인다.

뺄 후보, 확인할 곳처럼 **사람이 보고 판단할 것**을 그 구간 위에 글자로 띄운다. 사람은 캡컷에서
보고 정한 뒤 트랙째 지운다. 자막과 섞이지 않게 따로 트랙을 만들고 색과 자리를 달리한다
(기본: 노란 글자, 화면 위쪽).

- 시각은 원본(강의 소재) 기준 `src: [a, b]` 로 받는다. 붙일 때 지금 드래프트의 컷으로 편집본 시각을
  계산한다(timemap). 구간 안쪽이 일부 잘렸으면 처음 남은 곳부터 마지막 남은 곳까지 한 덩어리로 띄운다
- 글자 소재는 지어내지 않는다. 드래프트 '자막' 트랙의 첫 줄을 복제해 글·색·크기·자리만 바꾼다
- 한 트랙 안에서 글자 조각은 겹칠 수 없다. 겹치면 둘째 트랙("<이름> 2")에 놓는다
- 같은 이름 트랙이 있으면 지우고 다시 만든다(다시 돌려도 두 벌이 안 생긴다)
- 캡컷이 떠 있으면 멈춘다. 고치기 전에 스냅샷을 남긴다

계획 파일:
  {"track": "검토 표시", "items": [{"src": [1940.4, 1950.4], "text": "첫 줄\\n둘째 줄"}, ...],
   "color": [1.0, 0.85, 0.0], "size": 6.0, "y": 0.72}      # color·size·y 는 생략 가능

사용: python apply_notes.py <드래프트> <계획.json> [--dry]
"""
import copy
import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from draft_doctor import contents, resolve  # noqa: E402
from port_effects import capcut_running  # noqa: E402
import timemap  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

US = 1_000_000


def new_id():
    return uuid.uuid4().hex


def material_index(d):
    idx = {}
    for key, lst in (d.get("materials") or {}).items():
        if isinstance(lst, list):
            for m in lst:
                if isinstance(m, dict) and "id" in m:
                    idx[m["id"]] = (key, m)
    return idx


def template(d):
    """복제할 틀: '자막' 트랙 첫 줄과 그 글자 소재."""
    caps = [t for t in d["tracks"] if t["type"] == "text" and t.get("name") == "자막" and t["segments"]]
    if not caps:
        caps = [t for t in d["tracks"] if t["type"] == "text" and t["segments"]]
    if not caps:
        raise SystemExit("복제할 글자 줄이 드래프트에 없습니다. 자막이 있는 드래프트에만 붙일 수 있습니다.")
    seg = caps[0]["segments"][0]
    idx = material_index(d)
    if seg["material_id"] not in idx:
        raise SystemExit("자막 줄의 글자 소재를 못 찾았습니다.")
    return caps[0], seg, idx[seg["material_id"]][1], idx


def text_material(tmpl, text, color, size):
    m = copy.deepcopy(tmpl)
    m["id"] = new_id()
    c = json.loads(m["content"])
    st = copy.deepcopy(c["styles"][0])
    st["range"] = [0, len(text)]
    st["size"] = size
    st["fill"]["content"]["solid"]["color"] = list(color)
    c["styles"] = [st]
    c["text"] = text
    m["content"] = json.dumps(c, ensure_ascii=False)
    return m


def lanes(spans):
    """겹치지 않게 트랙 번호를 나눈다. spans: [(시작, 끝, i)] 시작순."""
    ends, out = [], {}
    for a, b, i in spans:
        for k, e in enumerate(ends):
            if a >= e:
                ends[k] = b
                out[i] = k
                break
        else:
            ends.append(b)
            out[i] = len(ends) - 1
    return out


def apply(draft, plan_path, dry=False):
    plan = json.loads(Path(plan_path).read_text(encoding="utf-8"))
    name = plan.get("track", "검토 표시")
    color = plan.get("color", [1.0, 0.85, 0.0])
    size = float(plan.get("size", 6.0))
    y = float(plan.get("y", 0.72))
    if capcut_running() and not dry:
        raise SystemExit("캡컷이 실행 중입니다. 완전히 종료한 뒤 다시 실행하세요.")
    files = contents(resolve(draft))
    d0 = json.loads(files[0].read_text(encoding="utf-8"))
    tl = timemap.timeline(d0)
    placed, skipped = [], []
    for i, it in enumerate(plan["items"]):
        r = timemap.span_to_edit(tl, float(it["src"][0]), float(it["src"][1]))
        if r is None:
            skipped.append(it)
            continue
        placed.append((round(r[0], 6), round(r[0] + r[1], 6), i))
    placed.sort()
    lane = lanes(placed)
    for a, b, i in placed:
        first = plan["items"][i]["text"].splitlines()[0]
        print(f"  {a // 60:02.0f}:{a % 60:04.1f}~{b // 60:02.0f}:{b % 60:04.1f} ({b - a:5.1f}초) "
              f"트랙{lane[i] + 1}  {first}")
    for it in skipped:
        print(f"  [건너뜀] 원본 {it['src']} 는 지금 컷에 남은 곳이 없다: {it['text'].splitlines()[0]}")
    if dry:
        print(f"(시험) 표시 {len(placed)}개 · 트랙 {max(lane.values(), default=-1) + 1}개 · 건너뜀 {len(skipped)}")
        return placed, skipped

    import draft_snapshot
    draft_snapshot.save(draft, "검토표시_붙이기전")
    for f in files:
        d = json.loads(f.read_text(encoding="utf-8"))
        # 같은 이름(과 "이름 N") 트랙과 그 소재를 먼저 지운다
        names = {name} | {f"{name} {k}" for k in range(2, 10)}
        old = [t for t in d["tracks"] if t["type"] == "text" and t.get("name") in names]
        old_mats = {s["material_id"] for t in old for s in t["segments"]}
        d["tracks"] = [t for t in d["tracks"] if t not in old]
        d["materials"]["texts"] = [m for m in d["materials"]["texts"] if m["id"] not in old_mats]
        track_t, seg_t, mat_t, idx = template(d)
        top = max((s.get("render_index", 0) for t in d["tracks"] if t["type"] == "text"
                   for s in t["segments"]), default=15000)
        tracks = {}
        for a, b, i in placed:
            it = plan["items"][i]
            m = text_material(mat_t, it["text"], color, size)
            d["materials"]["texts"].append(m)
            s = copy.deepcopy(seg_t)
            s["id"] = new_id()
            s["material_id"] = m["id"]
            s["target_timerange"] = {"start": int(round(a * US)), "duration": int(round((b - a) * US))}
            s["clip"]["transform"]["y"] = y
            s["render_index"] = top + 1 + lane[i]
            # 틀의 추가 소재 참조는 줄마다 따로 가진다(틀과 같은 모양으로)
            refs = []
            for ref in seg_t.get("extra_material_refs") or []:
                if ref in idx:
                    key, rm = idx[ref]
                    rm2 = copy.deepcopy(rm)
                    rm2["id"] = new_id()
                    d["materials"][key].append(rm2)
                    refs.append(rm2["id"])
                else:
                    refs.append(new_id())
            s["extra_material_refs"] = refs
            k = lane[i]
            if k not in tracks:
                t = copy.deepcopy(track_t)
                t["id"] = new_id()
                t["name"] = name if k == 0 else f"{name} {k + 1}"
                t["is_default_name"] = False
                t["segments"] = []
                tracks[k] = t
            tracks[k]["segments"].append(s)
        for k in sorted(tracks):
            tracks[k]["segments"].sort(key=lambda s: s["target_timerange"]["start"])
            d["tracks"].append(tracks[k])
        f.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    check(draft, name)
    return placed, skipped


def check(draft, name):
    """붙인 뒤 다시 읽어 잰다: 소재가 다 있나, 한 트랙 안에서 겹치지 않나."""
    for f in contents(resolve(draft)):
        d = json.loads(f.read_text(encoding="utf-8"))
        idx = material_index(d)
        ts = [t for t in d["tracks"] if t["type"] == "text" and (t.get("name") or "").startswith(name)]
        n = bad = over = 0
        for t in ts:
            prev = -1
            for s in t["segments"]:
                n += 1
                if s["material_id"] not in idx:
                    bad += 1
                tr = s["target_timerange"]
                if tr["start"] < prev:
                    over += 1
                prev = tr["start"] + tr["duration"]
        end = d["duration"]
        late = sum(1 for t in ts for s in t["segments"]
                   if s["target_timerange"]["start"] + s["target_timerange"]["duration"] > end)
        print(f"검사 {f.parent.name}: 트랙 {len(ts)} · 표시 {n} · 소재 없음 {bad} · 겹침 {over} · 영상 끝 넘음 {late}")
        if bad or over or late:
            raise SystemExit("검사를 통과하지 못했습니다. 스냅샷(검토표시_붙이기전)으로 되돌리세요.")


if __name__ == "__main__":
    a = [x for x in sys.argv[1:] if not x.startswith("--")]
    if len(a) != 2:
        raise SystemExit(__doc__)
    apply(a[0], a[1], dry="--dry" in sys.argv)
