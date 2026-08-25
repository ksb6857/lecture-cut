# -*- coding: utf-8 -*-
"""
.vrew 파일(ZIP)에서 단어 단위 타임라인을 추출한다.

출력: words.json
[
  {"i": 0, "type": "word"|"silence"|"pause"|"clip_end",
   "text": "선생님", "start": 18.82, "end": 19.52, "clip": 3},
  ...
]

- type 0 → word   (실제 발화 단어)
- type 1 → silence (브루가 검출한 무음 구간, duration 보유)
- type 3 → pause   (단어 사이 짧은 쉼, duration 보유)
- type 2 → clip_end (클립 경계 마커, duration 0)
"""
import json
import sys
import zipfile
from pathlib import Path

TYPE_MAP = {0: "word", 1: "silence", 2: "clip_end", 3: "pause"}


def extract(vrew_path: str, out_path: str) -> dict:
    with zipfile.ZipFile(vrew_path) as z:
        with z.open("project.json") as f:
            project = json.load(f)

    clips = project["transcript"]["clips"]
    words = []
    i = 0
    for ci, clip in enumerate(clips):
        for w in clip["words"]:
            start = w["originalStartTime"]
            dur = w["originalDuration"]
            words.append({
                "i": i,
                "type": TYPE_MAP.get(w["type"], str(w["type"])),
                "text": w["text"],
                "start": round(start, 3),
                "end": round(start + dur, 3),
                "clip": ci,
            })
            i += 1

    result = {
        "source_vrew": str(Path(vrew_path).name),
        "media_files": [f.get("name") for f in project.get("files", [])],
        "total_end": max((w["end"] for w in words), default=0),
        "words": words,
    }
    Path(out_path).write_text(
        json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    n_word = sum(1 for w in words if w["type"] == "word")
    print(f"OK: {len(words)} tokens ({n_word} words), "
          f"{result['total_end']/60:.1f} min -> {out_path}")
    return result


if __name__ == "__main__":
    extract(sys.argv[1], sys.argv[2])
