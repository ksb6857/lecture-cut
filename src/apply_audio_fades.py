# -*- coding: utf-8 -*-
"""소리가 난 채로 이어 붙은 컷에 1프레임(33ms) 오디오 페이드를 넣는다. 이음매 '틱'을 없앤다.

컷은 무음에서 자르는 게 원칙이다(refine_speech, quiet_edges). 그래도 두 테이크를 문장 한가운데서
이은 곳은 양쪽 다 말소리라 파형이 끊기며 작게 튄다. 2026-09-24 11차시 미리보기에서 489곳 중 4곳,
가장자리 정리(quiet_edges) 뒤에도 2곳이 남았다. video-use 는 모든 컷에 30ms 페이드를 넣는데,
우리는 **가장자리가 조용하지 않은 컷에만** 넣는다. 말 첫소리를 괜히 깎지 않기 위해서다.

**페이드 모양은 사람이 캡컷에서 넣은 드래프트에서 복제한다.** 비디오 클립의 소리 페이드는
materials.audio_fades 에 {fade_in_duration, fade_out_duration, fade_type, id, type} 로 있고
세그먼트의 extra_material_refs 가 id 를 가리킨다. 사용자 드래프트(1004)에 33332µs 짜리가 있다.

사용: python apply_audio_fades.py <드래프트> <참조 드래프트> --wav <wav> [--levels 캐시.npy]
        [--offset 초] [--quiet -62] [--frames 1] [--dry]
  --offset: 드래프트 원본 시각 - wav 시각 (소재 앞에 인트로를 붙였으면 그 길이)
"""
import copy
import json
import sys
import uuid
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import audio_levels as L  # noqa: E402
from draft_doctor import contents, resolve  # noqa: E402
from port_effects import capcut_running  # noqa: E402

US = 1_000_000
MARK = "_lecture_autocut"


def reference(ref):
    d = json.loads(contents(resolve(ref))[0].read_text(encoding="utf-8"))
    fs = d["materials"].get("audio_fades") or []
    if not fs:
        raise SystemExit(f"{ref} 에 오디오 페이드가 없습니다. 사람이 캡컷에서 페이드를 넣은 드래프트를 주세요.")
    return fs[0]


def win_max(db, t, guard=0.035):
    i0, i1 = max(0, int((t - guard) / L.HOP)), min(len(db), int((t + guard) / L.HOP) + 1)
    return float(db[i0:i1].max()) if i1 > i0 else -120.0


def patch(path, base, db, offset, quiet, dur, dry, n_expect=None):
    d = json.loads(path.read_text(encoding="utf-8"))
    vids = {m["id"]: m for m in d["materials"].get("videos") or []}
    vt = [t for t in d["tracks"] if t["type"] == "video"][0]
    segs = sorted(vt["segments"], key=lambda s: s["target_timerange"]["start"])
    if n_expect is not None and len(segs) != n_expect:
        return None
    main = Counter((vids.get(s["material_id"]) or {}).get("path") for s in segs).most_common(1)[0][0]
    fades = d["materials"].setdefault("audio_fades", [])
    old = {m["id"] for m in fades if m.get(MARK)}
    fades[:] = [m for m in fades if not m.get(MARK)]
    for s in segs:
        if s.get("extra_material_refs"):
            s["extra_material_refs"] = [r for r in s["extra_material_refs"] if r not in old]
    need = {}                                  # 세그먼트 번호 → [들어가기, 나가기]
    for k in range(len(segs) - 1):
        a, b = segs[k], segs[k + 1]
        if (vids.get(a["material_id"]) or {}).get("path") != main or (vids.get(b["material_id"]) or {}).get("path") != main:
            continue
        ta, tb = a["target_timerange"], b["target_timerange"]
        if abs(ta["start"] + ta["duration"] - tb["start"]) > 2000:
            continue                           # 붙어 있지 않다(전환·빈틈)
        a_end = (a["source_timerange"]["start"] + a["source_timerange"]["duration"]) / US - offset
        b_start = b["source_timerange"]["start"] / US - offset
        if a_end < 0 or b_start < 0:
            continue                           # 인트로·오프닝처럼 wav 에 없는 곳
        if win_max(db, a_end) > quiet or win_max(db, b_start) > quiet:
            need.setdefault(k, [0, 0])[1] = dur
            need.setdefault(k + 1, [0, 0])[0] = dur
    for k, (fin, fout) in need.items():
        m = copy.deepcopy(base)
        m.update({"id": str(uuid.uuid4()).upper(), "fade_in_duration": fin, "fade_out_duration": fout, MARK: True})
        fades.append(m)
        segs[k].setdefault("extra_material_refs", []).append(m["id"])
    if not dry:
        path.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    return len(need), len(segs)


def main(argv):
    pos, opt, k = [], {}, 0
    while k < len(argv):
        if argv[k] == "--dry":
            opt["--dry"] = True
            k += 1
        elif argv[k].startswith("--"):
            opt[argv[k]] = argv[k + 1]
            k += 2
        else:
            pos.append(argv[k])
            k += 1
    draft, ref = pos[:2]
    dry = bool(opt.get("--dry"))
    if not dry and capcut_running():
        raise SystemExit("캡컷이 실행 중입니다. 완전히 종료한 뒤 다시 실행하세요.")
    base = reference(ref)
    db = L.compute(opt["--wav"], opt.get("--levels"))
    dur = int(round(int(opt.get("--frames", 1)) * US / 30)) - 1      # 1프레임 = 33332µs (사용자 값과 같게)
    files = contents(resolve(draft))
    n, n_seg = patch(files[0], base, db, float(opt.get("--offset", 0)), float(opt.get("--quiet", -62)), dur, dry)
    for f in files[1:]:
        patch(f, base, db, float(opt.get("--offset", 0)), float(opt.get("--quiet", -62)), dur, dry, n_expect=n_seg)
    print(f"{'(시험) ' if dry else ''}소리 난 채 이어진 컷 가장자리 {n}개 클립에 {dur / US * 1000:.0f}ms 페이드 "
          f"(클립 {n_seg}개, 사본 {len(files)}벌)")


if __name__ == "__main__":
    main(sys.argv[1:])
