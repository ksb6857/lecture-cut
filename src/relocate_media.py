# -*- coding: utf-8 -*-
"""드래프트가 물고 있는 소재 파일을 안전한 자리로 옮기고 경로를 고친다.

**다운로드 폴더에 둔 소재는 시한폭탄이다.** 캡컷 드래프트는 절대경로를 그대로
물기 때문에, 다운로드 폴더를 정리하는 순간 그 차시가 통째로 무음이 되거나
화면이 빈다. 원본 영상·오디오는 `C:\\projects\\video\\` 에 둔다(CLAUDE.md 4번).

**옮기기 전에 확인하고, 확인한 뒤에 지운다.** 새 자리에 복사해서 크기가 같은지
보고, 드래프트의 경로를 모두 고치고, 고친 경로가 실제로 존재하는지 다시 본 뒤
원래 파일을 지운다. 중간에 하나라도 어긋나면 멈춘다.

사용: python src/relocate_media.py <드래프트> [<드래프트> ...] [--to 폴더] [--dry]
      드래프트가 물고 있는 소재 중 **대상 폴더 밖에 있는 것**을 옮긴다.
"""
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from draft_doctor import contents, resolve  # noqa: E402
from port_effects import capcut_running  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

DEST = Path(r"C:\projects\video")
# 드래프트 폴더 안에 캡컷이 스스로 넣어 둔 것은 건드리지 않는다
SAFE = ("com.lveditor.draft", "\\projects\\", "/projects/")


def media_paths(d):
    out = []
    for kind in ("videos", "audios"):
        for m in d["materials"].get(kind) or []:
            p = m.get("path") or ""
            if p and "_draftpath_placeholder_" not in p:
                out.append((m, p))
    return out


def risky(p):
    q = p.replace("/", "\\").lower()
    return not any(s.replace("/", "\\").lower() in q for s in SAFE)


def run(drafts, dest=DEST, dry=False):
    dest = Path(dest)
    if not dry and capcut_running():
        raise SystemExit("캡컷이 실행 중입니다. 완전히 종료한 뒤 다시 실행하세요.")
    dest.mkdir(parents=True, exist_ok=True)

    # 1) 옮길 것을 모은다
    plan = {}
    files = {}
    for name in drafts:
        root = resolve(name)
        files[name] = contents(root)
        for f in files[name]:
            d = json.loads(f.read_text(encoding="utf-8"))
            for m, p in media_paths(d):
                if risky(p):
                    plan.setdefault(p, dest / Path(p).name)
    if not plan:
        print("옮길 소재가 없습니다.")
        return
    for src, dst in plan.items():
        s = Path(src)
        print(f"  {s.name}\n      {src}\n   -> {dst}"
              + ("" if s.exists() else "   [원본 없음!]"))
    if dry:
        return

    # 2) 복사하고 크기를 맞춰 본다
    for src, dst in plan.items():
        s = Path(src)
        if not s.exists():
            raise SystemExit(f"원본이 없습니다: {src}")
        if dst.exists() and dst.stat().st_size == s.stat().st_size:
            print(f"  이미 있음(크기 같음): {dst.name}")
            continue
        shutil.copy2(s, dst)
        if dst.stat().st_size != s.stat().st_size:
            raise SystemExit(f"복사 크기가 다릅니다: {dst}")
        print(f"  복사 완료: {dst.name} ({dst.stat().st_size:,} 바이트)")

    # 3) 드래프트 경로를 고친다
    lower = {k.replace("/", "\\").lower(): v for k, v in plan.items()}
    for name, fs in files.items():
        for f in fs:
            d = json.loads(f.read_text(encoding="utf-8"))
            n = 0
            for m, p in media_paths(d):
                key = p.replace("/", "\\").lower()
                if key in lower:
                    m["path"] = str(lower[key]).replace("\\", "/")
                    n += 1
            if n:
                f.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
            print(f"  {name}: {f.name} 경로 {n}개 고침")

    # 3b) **캡컷 미디어 목록(draft_meta_info.json)도 고친다.** draft_content 만
    # 고치면 타임라인은 멀쩡한데 캡컷이 열자마자 '미디어 연결' 창을 띄운다 —
    # 그 창은 이 목록을 읽기 때문이다. 2026-08-24 에 실제로 그랬다.
    for name in drafts:
        root = resolve(name)
        for mp in sorted(root.rglob("draft_meta_info.json")):
            try:
                d = json.loads(mp.read_text(encoding="utf-8"))
            except Exception:
                continue
            n = 0
            for grp in d.get("draft_materials") or []:
                for it in grp.get("value") or []:
                    key = (it.get("file_Path") or "").replace("/", "\\").lower()
                    if key in lower:
                        it["file_Path"] = str(lower[key]).replace("\\", "/")
                        n += 1
            if n:
                mp.write_text(json.dumps(d, ensure_ascii=False),
                              encoding="utf-8")
                print(f"  {name}: {mp.name} 미디어 목록 {n}개 고침")

    # 4) 고친 경로가 실제로 있는지 다시 본다
    for name, fs in files.items():
        for f in fs:
            d = json.loads(f.read_text(encoding="utf-8"))
            for m, p in media_paths(d):
                if not Path(p).exists():
                    raise SystemExit(f"고친 뒤에도 없는 경로: {p}")
    print("모든 경로 확인 완료")

    # 5) 그제서야 원본을 지운다
    for src in plan:
        Path(src).unlink()
        print(f"  원본 지움: {src}")


if __name__ == "__main__":
    a = sys.argv[1:]
    dest = DEST
    if "--to" in a:
        i = a.index("--to")
        dest = a[i + 1]
        a = a[:i] + a[i + 2:]
    run([x for x in a if not x.startswith("--")], dest, dry="--dry" in a)
