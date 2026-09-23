# -*- coding: utf-8 -*-
"""pptx 의 모든 장을 1920x1080 PNG 로 뽑는다 (파워포인트로 렌더).

python-pptx 로는 그림을 못 그린다. 녹화 화면과 픽셀로 대조하거나 영상에 덮을
화면은 실제 파워포인트가 그린 것이어야 글꼴·줄바꿈이 녹화와 같다.

**원본을 직접 열지 않는다.** 사본을 넘긴다. 파워포인트가 파일을 잠그고,
사용자가 열어 둔 창과 같은 프로세스를 쓰기 때문이다.

주의 — PPT 에 넣은 글꼴 중 OTF 는 파워포인트가 못 그린다(대체 글꼴로 조용히
바뀐다). 뽑은 뒤 녹화 화면과 대조해 글씨체가 같은지 본다.

사용: python export_slides.py <사본.pptx> <출력폴더> [장번호,장번호...]
"""
import os
import sys
from pathlib import Path


def export(pptx, out_dir, only=None, w=1920, h=1080):
    import win32com.client
    out_dir = Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    app = win32com.client.Dispatch("PowerPoint.Application")
    pres = app.Presentations.Open(str(Path(pptx).resolve()), ReadOnly=True, WithWindow=False)
    done = []
    try:
        n = pres.Slides.Count
        for i in range(1, n + 1):
            if only and i not in only:
                continue
            f = out_dir / f"S{i:02d}.png"
            pres.Slides(i).Export(str(f), "PNG", w, h)
            done.append(f)
    finally:
        pres.Close()
    return done


if __name__ == "__main__":
    only = None
    if len(sys.argv) > 3:
        only = {int(x) for x in sys.argv[3].split(",")}
    fs = export(sys.argv[1], sys.argv[2], only)
    print(f"{len(fs)}장 → {Path(sys.argv[2]).resolve()}")
