# -*- coding: utf-8 -*-
"""드래프트의 판(버전)을 저장하고, 목록을 보고, 되돌린다.

**왜.** "수정했을 때 옛것과 헷갈린다"는 문제를 캡컷 목록에 날짜 이름을
쌓아서 풀면 두 가지 사고가 난다: 이름을 바꿀 때마다 안의 절대경로가 끊기고
(2026-08-17, 08-24 두 번), 목록의 옛 항목을 최신인 줄 알고 여는 일이 생긴다
(2026-08-24 밤). 그래서 **캡컷 목록에는 살아 있는 최신 하나만 두고,
역사는 여기 스냅샷으로** 남긴다.

스냅샷은 드래프트의 JSON(타임라인·미디어 목록)만 담는다. 한 판에 십수 MB.
소재 파일은 `C:\\projects\\video\\` 에 그대로 있으므로 다시 담지 않는다.

사용 (Claude 가 실행):
    python src/draft_snapshot.py 저장 <드래프트> [메모]
    python src/draft_snapshot.py 목록 <드래프트>
    python src/draft_snapshot.py 복원 <드래프트> <스냅샷이름>
"""
import json
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from draft_doctor import DRAFTS, contents, resolve  # noqa: E402
from port_effects import capcut_running  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

US = 1_000_000
STORE = DRAFTS.parent / "_lecture_autocut_snapshots"


def describe(doc):
    """판을 알아볼 수 있는 한 줄: 길이·자막 수."""
    caps = sub = 0
    for tr in doc.get("tracks") or []:
        n = len(tr.get("segments") or [])
        if tr.get("name") == "lecture_autocut_keycaption":
            caps = n
        elif tr.get("name") == "lecture_autocut_subtopic":
            sub = n
    dur = (doc.get("duration") or 0) / US
    return "%d:%04.1f · 핵심자막 %d · 소주제 %d" % (dur // 60, dur % 60, caps, sub)


def draft_files(root):
    """스냅샷에 담을 파일: 타임라인 전부 + 미디어 목록 전부."""
    return sorted(root.rglob("draft_content.json")) + \
        sorted(root.rglob("draft_meta_info.json"))


def save(draft, memo=""):
    root = resolve(draft)
    tag = time.strftime("%m%d-%H%M") + (("_" + memo.replace(" ", "_")) if memo else "")
    dst = STORE / root.name / tag
    if dst.exists():
        raise SystemExit(f"이미 있는 스냅샷 이름입니다: {tag}")
    for f in draft_files(root):
        out = dst / f.relative_to(root)
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, out)
    doc = json.loads(contents(root)[0].read_text(encoding="utf-8"))
    (dst / "_설명.txt").write_text(describe(doc) + ("\n" + memo if memo else ""),
                                  encoding="utf-8")
    print(f"스냅샷 저장: {root.name} / {tag}  ({describe(doc)})")
    return dst


def listing(draft):
    root = resolve(draft)
    base = STORE / root.name
    rows = sorted(base.iterdir()) if base.is_dir() else []
    if not rows:
        print(f"{root.name}: 스냅샷이 없습니다")
        return
    print(f"{root.name} 스냅샷 {len(rows)}개  (최신이 아래)")
    for d in rows:
        note = (d / "_설명.txt")
        desc = note.read_text(encoding="utf-8").splitlines()[0] if note.exists() else ""
        print(f"  {d.name:28s} {desc}")


def restore(draft, tag):
    if capcut_running():
        raise SystemExit("캡컷이 실행 중입니다. 완전히 종료한 뒤 다시 실행하세요.")
    root = resolve(draft)
    src = STORE / root.name / tag
    if not src.is_dir():
        # 폴더 이름이 그새 바뀌었을 수 있다 — 전 폴더에서 찾는다
        hits = [p for p in STORE.glob(f"*/{tag}") if p.is_dir()]
        if len(hits) != 1:
            raise SystemExit(f"스냅샷을 못 찾았습니다: {tag} (목록: 목록 명령)")
        src = hits[0]
    save(draft, "복원전_자동")           # 되돌리기 전 상태도 판으로 남긴다
    n = 0
    for f in sorted(src.rglob("draft_*.json")):
        rel = f.relative_to(src)
        dst = root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, dst)
        n += 1
    print(f"복원 완료: {tag} -> {root.name}  (파일 {n}개)")
    print("경로가 그새 바뀌었을 수 있으니 진단을 돌린다:")
    import draft_doctor
    draft_doctor.repair(root)


if __name__ == "__main__":
    a = sys.argv[1:]
    if not a:
        raise SystemExit(__doc__)
    cmd = a[0]
    if cmd == "저장":
        save(a[1], a[2] if len(a) > 2 else "")
    elif cmd == "목록":
        listing(a[1])
    elif cmd == "복원":
        restore(a[1], a[2])
    else:
        raise SystemExit(__doc__)
