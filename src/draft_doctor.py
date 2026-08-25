# -*- coding: utf-8 -*-
"""캡컷 드래프트 폴더를 진단하고 끊어진 소재 경로를 고친다.

**왜 필요한가.** 캡컷은 드래프트 폴더를 마음대로 다룬다:

  - 같은 이름이 이미 있으면 폴더 이름 뒤에 `(1)` 을 붙인다.
  - 처음 열 때 같은 이름의 **하위 폴더**를 만들고 그 뒤로는 거기에만 저장한다.
  - 그런데 `draft_content.json` 안의 소재 경로 일부는 **절대경로**라
    폴더 이름이 바뀌어도 따라오지 않는다.

그래서 2026-08-17 에 `2차시_효과_v2` 가 `2차시_효과_v2(1)` 로 바뀌면서
영상 425개와 사용자가 재녹음한 오디오 20개가 통째로 끊어진 참조가 됐다.
캡컷에서는 편집한 게 안 보이고, 우리 도구는 옛 이름을 못 찾아 실패했다.

**규칙 세 가지**

1. 드래프트는 폴더 이름이 아니라 `draft_meta_info.json` 의 `draft_name`
   으로 찾는다. 폴더 이름은 캡컷이 언제든 바꾼다.
2. 붙이기 전에 `진단` 을 돌려 끊어진 경로가 0인지 본다.
3. 고치기 전에 원본을 `_doctor_backup` 에 복사한다.

사용:
    python src/draft_doctor.py 진단                 # 전체 목록
    python src/draft_doctor.py 진단 <드래프트>
    python src/draft_doctor.py 수리 <드래프트>       # 끊어진 절대경로 재작성
"""
import json
import os
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from port_effects import capcut_running  # noqa: E402

from draft_root import DRAFTS  # noqa: E402
US = 1_000_000
MEDIA = ("videos", "audios", "images", "stickers")


def folders():
    return [p for p in DRAFTS.iterdir() if p.is_dir()]


def meta_name(folder: Path):
    f = folder / "draft_meta_info.json"
    if not f.exists():
        return None
    try:
        return json.loads(f.read_text(encoding="utf-8")).get("draft_name")
    except Exception:
        return None


def resolve(name):
    """폴더 이름이든 프로젝트 이름이든 받아 실제 폴더 하나를 돌려준다.

    여러 개가 걸리면 **고르지 않고 멈춘다.** 조용히 하나를 골랐다가 엉뚱한
    사본을 고치는 게 지금까지의 사고 원인이었다.
    """
    p = Path(name)
    if p.is_dir():
        return p
    hits = [f for f in folders() if f.name == name or meta_name(f) == name]
    if not hits:
        raise SystemExit(f"그런 드래프트가 없습니다: {name}\n"
                         f"  `python src/draft_doctor.py 진단` 으로 목록을 보세요.")
    if len(hits) > 1:
        joined = "\n".join(f"  - {h.name}  (프로젝트명 {meta_name(h)})"
                           for h in hits)
        raise SystemExit(f"'{name}' 에 여러 폴더가 걸립니다. 하나를 정확히 "
                         f"지정하세요:\n{joined}")
    return hits[0]


BACKUP = DRAFTS.parent / "_lecture_autocut_doctor_backup"
SKIP = ("_doctor_backup", "_lecture_autocut_backup")


def contents(root: Path):
    """캡컷이 실제로 읽는 것부터 순서대로. 하위 사본이 최신이다.

    백업 사본은 반드시 걸러낸다. 백업을 드래프트 폴더 안에 두었다가 그게
    '가장 깊은 사본' 으로 잡혀 수리 결과를 잘못 읽은 적이 있다(2026-08-17).
    그래서 백업은 아예 드래프트 폴더 **바깥**에 만든다.
    """
    cs = [q for q in root.rglob("draft_content.json")
          if not any(s in q.parts for s in SKIP)]
    return sorted(cs, key=lambda q: (len(q.relative_to(root).parts),
                                     q.stat().st_mtime), reverse=True)


def scan(path: Path):
    d = json.loads(path.read_text(encoding="utf-8"))
    ok = broken = ph = 0
    samples = []
    for kind in MEDIA:
        for m in d["materials"].get(kind) or []:
            raw = m.get("path") or ""
            if not raw:
                continue
            if "_draftpath_placeholder_" in raw:
                ph += 1
            elif Path(raw.replace("/", "\\")).exists():
                ok += 1
            else:
                broken += 1
                if len(samples) < 2:
                    samples.append(raw)
    return ok, broken, ph, samples


def repair(root: Path, dry=False):
    """끊어진 절대경로를 이 폴더 기준으로 다시 쓴다.

    `.../com.lveditor.draft/<옛이름>/materials/...` 의 <옛이름> 만 실제
    폴더 이름으로 바꾼다. 파일명·하위 구조는 건드리지 않는다 — 캡컷이 폴더
    이름만 바꿨을 뿐 안의 파일은 그대로 따라왔기 때문이다.
    """
    pat = re.compile(r"(com\.lveditor\.draft/)([^/]+)(/materials/)", re.I)
    real = root.name
    total = fixed = still = 0
    for p in contents(root):
        d = json.loads(p.read_text(encoding="utf-8"))
        changed = 0
        for kind in MEDIA:
            for m in d["materials"].get(kind) or []:
                raw = m.get("path") or ""
                if not raw or "_draftpath_placeholder_" in raw:
                    continue
                total += 1
                if Path(raw.replace("/", "\\")).exists():
                    continue
                new = pat.sub(rf"\g<1>{real}\g<3>", raw)
                if new != raw and Path(new.replace("/", "\\")).exists():
                    m["path"] = new
                    changed += 1
                else:
                    still += 1
        fixed += changed
        rel = p.relative_to(root)
        print(f"  {rel}: {changed}개 재작성" + ("  [dry]" if dry else ""))
        if changed and not dry:
            bak = BACKUP / root.name / rel
            bak.parent.mkdir(parents=True, exist_ok=True)
            if not bak.exists():
                shutil.copy2(p, bak)
            p.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")

    # **캡컷의 미디어 목록(draft_meta_info.json)도 같이 고친다.** 여기의
    # `draft_materials[].value[].file_Path` 가 끊겨 있으면 캡컷이 열자마자
    # '미디어 연결' 창을 띄운다. 2026-08-24 에 소재를 옮기고 draft_content 만
    # 고쳤더니 타임라인은 멀쩡한데 이 창이 떠서 사용자가 파일이 사라진 줄 알았다.
    for mp in sorted(root.rglob("draft_meta_info.json")):
        try:
            d = json.loads(mp.read_text(encoding="utf-8"))
        except Exception:
            continue
        changed = 0
        for grp in d.get("draft_materials") or []:
            for it in grp.get("value") or []:
                raw = it.get("file_Path") or ""
                if not raw or Path(raw.replace("/", "\\")).exists():
                    continue
                new = pat.sub(rf"\g<1>{real}\g<3>", raw.replace("\\", "/"))
                if new == raw or not Path(new.replace("/", "\\")).exists():
                    # 폴더 이름 문제가 아니면 파일 이름으로 새 위치를 찾아본다
                    # (소재를 다른 폴더로 옮긴 경우: relocate_media)
                    cand = Path(r"C:\projects\video") / Path(raw).name
                    if cand.exists():
                        new = str(cand).replace("\\", "/")
                    else:
                        still += 1
                        continue
                it["file_Path"] = new
                changed += 1
        if changed:
            fixed += changed
            print(f"  {mp.relative_to(root)}: 미디어 목록 {changed}개 재작성"
                  + ("  [dry]" if dry else ""))
            if not dry:
                bak = BACKUP / root.name / mp.relative_to(root)
                bak.parent.mkdir(parents=True, exist_ok=True)
                if not bak.exists():
                    shutil.copy2(mp, bak)
                mp.write_text(json.dumps(d, ensure_ascii=False),
                              encoding="utf-8")
    return total, fixed, still


def diagnose(one=None):
    targets = [resolve(one)] if one else sorted(folders())
    print(f"{'폴더':30s} {'프로젝트명':22s} {'사본':>3s} {'정상':>5s} "
          f"{'끊김':>5s} {'placeholder':>11s}")
    for f in targets:
        cs = contents(f)
        if not cs:
            print(f"{f.name:30s} {'-':22s}   0  (draft_content.json 없음)")
            continue
        ok, broken, ph, samples = scan(cs[0])
        mark = "  <-- 끊어짐" if broken else ""
        print(f"{f.name:30s} {str(meta_name(f)):22s} {len(cs):3d} "
              f"{ok:5d} {broken:5d} {ph:11d}{mark}")
        for s in samples:
            print(f"      끊긴 예: {s}")


def main(argv):
    cmd = argv[0] if argv else "진단"
    if cmd in ("진단", "diagnose"):
        diagnose(argv[1] if len(argv) > 1 else None)
    elif cmd in ("수리", "repair"):
        if capcut_running():
            raise SystemExit("캡컷이 실행 중입니다. 완전히 종료한 뒤 다시 실행하세요.")
        root = resolve(argv[1])
        print(f"수리 대상: {root}")
        total, fixed, still = repair(root, dry="--dry" in argv)
        print(f"절대경로 {total}개 중 {fixed}개 재작성, 아직 못 찾은 것 {still}개")
        print()
        diagnose(str(root))
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
