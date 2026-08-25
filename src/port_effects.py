# -*- coding: utf-8 -*-
"""1차시 편집본의 자막 스타일·등장 애니메이션을 2·3차시 드래프트에 입힌다.

**값을 짓지 않는다.** 1차시 `template.json` 에서 자막 material 을 통째로
복제해 글자만 갈아끼운다 (CLAUDE.md 5번). 캡컷 스키마에는 우리가 뜻을
모르는 필드가 수십 개 있는데, 그중 하나만 틀려도 조용히 깨진다.

바꾸는 것은 세 가지뿐이다:
  - `content.text` 와 `styles[0].range` (글자 수가 다르므로)
  - material `id` (드래프트 안에서 유일해야 한다)
  - 캐시 경로의 계정명 (참조본은 `C:/Users/경남교육청/...` 로 박혀 있다)

애니메이션 길이는 자막이 짧으면 줄인다. 1차시 자막은 2~5초라 인 1.0초 +
아웃 0.5초가 들어갔지만, 실황 녹화의 말자막에는 1초짜리도 있어 그대로
넣으면 뜨자마자 사라진다.

사용:
    python src/port_effects.py <참조 template.json> <대상 드래프트> [--anim] [--dry]
"""
import copy
import getpass
import json
import os
import re
import subprocess
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from draft_root import DRAFTS  # noqa: E402
US = 1_000_000
ANIM_MIN_RATIO = 0.8        # 인+아웃이 자막 길이의 80% 를 넘지 않게


def uid():
    return str(uuid.uuid4()).upper()


def capcut_running() -> bool:
    """`build_capcut_draft.capcut_running` 과 같다. 여기에 다시 적은 이유는
    이 파일이 pycapcut 없이도 돌아야 하기 때문이다(그쪽은 모듈 최상단에서
    pycapcut 을 import 한다)."""
    try:
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq CapCut.exe"],
                             capture_output=True, text=True, timeout=15)
        return "CapCut.exe" in out.stdout
    except Exception:
        return False


def localize(obj, user=None):
    """참조본에 박힌 남의 PC 캐시 경로를 이 PC 계정으로 바꾼다."""
    user = user or getpass.getuser()
    pat = re.compile(r"(C:/Users/)[^/]+(/AppData/Local/CapCut/)", re.I)

    def walk(o):
        if isinstance(o, str):
            return pat.sub(rf"\g<1>{user}\g<2>", o)
        if isinstance(o, list):
            return [walk(x) for x in o]
        if isinstance(o, dict):
            return {k: walk(v) for k, v in o.items()}
        return o
    return walk(obj)


def pick_reference(ref_path):
    """참조본에서 가장 많이 쓰인 자막 스타일 한 벌과 그 애니메이션을 고른다."""
    d = json.loads(Path(ref_path).read_text(encoding="utf-8"))
    idx = {}
    for kind, arr in d["materials"].items():
        if isinstance(arr, list):
            for m in arr:
                if isinstance(m, dict) and m.get("id"):
                    idx[m["id"]] = (kind, m)

    counts, sample, anim_by_style = {}, {}, {}
    for tr in d["tracks"]:
        if tr["type"] != "text":
            continue
        for s in tr.get("segments") or []:
            kind, m = idx.get(s.get("material_id"), (None, None))
            if kind != "texts":
                continue
            key = m.get("font_size")
            counts[key] = counts.get(key, 0) + 1
            sample.setdefault(key, m)
            for r in s.get("extra_material_refs") or []:
                k2, m2 = idx.get(r, (None, None))
                if k2 == "material_animations":
                    anim_by_style.setdefault(key, m2)

    key = max(counts, key=counts.get)
    return (localize(sample[key]), localize(anim_by_style.get(key)),
            counts[key], key)


def scale_anim(anim, seg_us):
    """자막이 짧으면 인/아웃 길이를 비례 축소한다."""
    a = copy.deepcopy(anim)
    subs = a.get("animations") or []
    total = sum(x.get("duration", 0) for x in subs)
    budget = seg_us * ANIM_MIN_RATIO
    if total > budget and total > 0:
        f = budget / total
        for x in subs:
            x["duration"] = max(100_000, int(x["duration"] * f))
    return a


def restyle_text(base, text):
    """참조 자막 material 을 복제해 글자만 갈아끼운다."""
    m = copy.deepcopy(base)
    m["id"] = uid()
    c = json.loads(m["content"])
    c["text"] = text
    for st in c.get("styles") or []:
        st["range"] = [0, len(text)]
    m["content"] = json.dumps(c, ensure_ascii=False)
    for f in m.get("fonts") or []:
        f["id"] = uid()
    return m


def patch(path, base, anim, use_anim, n_expect=None):
    d = json.loads(path.read_text(encoding="utf-8"))
    idx = {m["id"]: m for m in d["materials"].get("texts") or []}
    segs = [(tr, s) for tr in d["tracks"] if tr["type"] == "text"
            for s in tr.get("segments") or []]
    if n_expect is not None and len(segs) != n_expect:
        return None                      # 다른 버전의 사본 — 건드리지 않는다

    new_texts, anims = [], d["materials"].setdefault("material_animations", [])
    done = 0
    for _tr, s in segs:
        old = idx.get(s.get("material_id"))
        if not old:
            continue
        try:
            text = json.loads(old["content"])["text"]
        except Exception:
            continue
        m = restyle_text(base, text)
        s["material_id"] = m["id"]
        new_texts.append(m)
        if use_anim and anim:
            refs = s.setdefault("extra_material_refs", [])
            # 이미 붙어 있는 애니메이션은 떼고 새것으로 간다
            have = {a["id"] for a in anims}
            refs[:] = [r for r in refs if r not in have]
            a = scale_anim(anim, s["target_timerange"]["duration"])
            a["id"] = uid()
            anims.append(a)
            refs.append(a["id"])
        done += 1

    keep = {m["id"] for m in new_texts}
    d["materials"]["texts"] = new_texts + [
        m for m in d["materials"]["texts"] if m["id"] not in keep
        and m["id"] not in idx]
    path.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    return done, len(segs)


def strip_text_anim(draft_name, dry=False):
    """자막에 붙은 등장/퇴장 애니메이션만 떼어낸다. 글꼴·크기·색은 그대로.

    665줄 말자막에 매 줄 반짝이는 효과가 들어가면 과하다는 판단이 나오면
    쓴다. material_animations 자체를 지우지 않고 자막 세그먼트의 참조만
    끊는다 — 영상 클립이 쓰는 애니메이션까지 건드리면 안 되기 때문이다.
    """
    if not dry and capcut_running():
        raise SystemExit("캡컷이 실행 중입니다. 완전히 종료한 뒤 다시 실행하세요.")
    root = Path(draft_name) if Path(draft_name).is_dir() \
        else DRAFTS / draft_name
    files = sorted(root.rglob("draft_content.json"))
    total = 0
    for p in files:
        d = json.loads(p.read_text(encoding="utf-8"))
        anims = {a["id"] for a in d["materials"].get("material_animations")
                 or []}
        n = 0
        for tr in d["tracks"]:
            if tr["type"] != "text":
                continue
            for s in tr.get("segments") or []:
                refs = s.get("extra_material_refs") or []
                keep = [r for r in refs if r not in anims]
                if len(keep) != len(refs):
                    s["extra_material_refs"] = keep
                    n += 1
        if not dry:
            p.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        total = max(total, n)
        print(f"  {p.parent.name}: 자막 {n}줄에서 애니메이션 제거")
    return total


def run(ref_path, draft_name, use_anim=False, dry=False):
    base, anim, n_ref, size = pick_reference(ref_path)
    print(f"참조 스타일: 글꼴 {base.get('font_resource_id')} "
          f"({(base.get('fonts') or [{}])[0].get('title', '?')}) "
          f"크기 {size} — 참조본 {n_ref}줄에 쓰임")
    if anim:
        names = " + ".join(f"{a['type']}:{a['name']}({a['duration']/US:.2f}s)"
                           for a in anim["animations"])
        print(f"등장 애니메이션: {names}" + ("" if use_anim else "  (--anim 없으면 안 넣음)"))

    root = Path(draft_name) if Path(draft_name).is_dir() else DRAFTS / draft_name
    files = sorted(root.rglob("draft_content.json"),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        raise SystemExit(f"draft_content.json 이 없습니다: {root}")
    if dry:
        print(f"[dry] 사본 {len(files)}벌을 고칠 예정")
        return
    if capcut_running():
        raise SystemExit("캡컷이 실행 중입니다. 완전히 종료한 뒤 다시 실행하세요.")

    first = patch(files[0], base, anim, use_anim)
    n, n_seg = first
    for f in files[1:]:
        patch(f, base, anim, use_anim, n_expect=n_seg)
    print(f"자막 {n}줄에 스타일 적용 (사본 {len(files)}벌)")


def main(argv):
    if argv[0] == "--strip-anim":
        strip_text_anim(argv[1], dry="--dry" in argv)
        return
    ref, draft = argv[0], argv[1]
    run(ref, draft, use_anim="--anim" in argv, dry="--dry" in argv)


if __name__ == "__main__":
    main(sys.argv[1:])
