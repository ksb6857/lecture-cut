# -*- coding: utf-8 -*-
"""
words.json -> LLM 분석용 전사본 청크 파일들

형식 (단어마다 전역 인덱스 부착, 긴 공백은 무음 마커로 표시):
  ### t=18.8s
  123:선생님 124:작가 125:되세요 ...
  --- 무음 2.3s ---
"""
import json
import sys
from pathlib import Path

GAP_MARK = 0.8      # 이 이상 공백이면 무음 마커 표시 (초)
CHUNK_WORDS = 450   # 청크당 단어 수
OVERLAP = 50        # 청크 간 겹침


def make(words_path, out_dir):
    data = json.loads(Path(words_path).read_text(encoding="utf-8"))
    words = [w for w in data["words"] if w["type"] == "word"]
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    # 전체를 라인 단위 텍스트로 먼저 조립
    def render(ws):
        lines = []
        cur = []
        prev_end = None
        for w in ws:
            if prev_end is not None and w["start"] - prev_end >= GAP_MARK:
                if cur:
                    lines.append(" ".join(cur))
                    cur = []
                lines.append(f"--- 무음 {w['start']-prev_end:.1f}s ---")
                lines.append(f"### t={w['start']:.1f}s")
            elif not cur and not lines:
                lines.append(f"### t={w['start']:.1f}s")
            cur.append(f"{w['i']}:{w['text']}")
            prev_end = w["end"]
        if cur:
            lines.append(" ".join(cur))
        return "\n".join(lines)

    chunks = []
    step = CHUNK_WORDS - OVERLAP
    for s in range(0, len(words), step):
        chunk = words[s:s + CHUNK_WORDS]
        if not chunk:
            break
        chunks.append(chunk)
        if s + CHUNK_WORDS >= len(words):
            break

    for n, chunk in enumerate(chunks):
        p = out / f"chunk_{n:02d}.txt"
        header = (f"# 청크 {n+1}/{len(chunks)} | 단어 인덱스 "
                  f"{chunk[0]['i']}~{chunk[-1]['i']} | "
                  f"시간 {chunk[0]['start']:.0f}s~{chunk[-1]['end']:.0f}s\n\n")
        p.write_text(header + render(chunk), encoding="utf-8")
    print(f"OK: {len(chunks)} chunks -> {out_dir}")
    return len(chunks)


if __name__ == "__main__":
    make(sys.argv[1], sys.argv[2])
