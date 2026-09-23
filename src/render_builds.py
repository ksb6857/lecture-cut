# -*- coding: utf-8 -*-
"""애니메이션 단계마다 슬라이드가 어떻게 보이는지 PNG 로 뽑는다 (파워포인트로 렌더).

녹화는 애니메이션 없이 찍혔다. 다시 찍지 않고, 단계별 화면을 녹화 위에 덮어
**말하는 순서대로 항목이 나타나게** 만든다. 그 단계별 화면을 여기서 뽑는다.

파워포인트에는 '애니메이션 몇 단계 상태로 내보내기' 가 없다. 그래서 뒤 단계 도형을
숨긴 채 내보낸다. 파일은 저장하지 않는다(읽기 전용으로 연 사본을 메모리에서만 바꾼다).

출력: <폴더>/S06_0.png (바탕만) · S06_1.png (1단계까지) · … · S06_3.png (전부)

사용: python render_builds.py <사본.pptx> <계획.json> <출력폴더>
      계획 파일은 ppt_anim.py 와 같다.
"""
import json
import sys
from pathlib import Path


def render(pptx, plan, out_dir, w=1920, h=1080):
    import win32com.client
    out_dir = Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    app = win32com.client.Dispatch("PowerPoint.Application")
    pres = app.Presentations.Open(str(Path(pptx).resolve()), ReadOnly=True, WithWindow=False)
    made = {}
    try:
        for key, steps in plan["slides"].items():
            s = pres.Slides(int(key))
            by_id = {s.Shapes(i).Id: s.Shapes(i) for i in range(1, s.Shapes.Count + 1)}
            orig = {i: sh.Visible for i, sh in by_id.items()}    # 원래 숨겨 둔 도형은 그대로 둔다
            n = len(steps)
            files = []
            for k in range(n + 1):
                hide = {i for g in steps[k:] for i in g}      # k 단계까지 보이고 나머지 숨김
                for i, sh in by_id.items():
                    sh.Visible = 0 if i in hide else orig[i]
                f = out_dir / f"S{int(key):02d}_{k}.png"
                s.Export(str(f), "PNG", w, h)
                files.append(str(f))
            for i, sh in by_id.items():
                sh.Visible = orig[i]
            made[int(key)] = files
    finally:
        pres.Close()
    return made


if __name__ == "__main__":
    plan = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
    m = render(sys.argv[1], plan, sys.argv[3])
    print(f"{len(m)}장 · 화면 {sum(len(v) for v in m.values())}개 → {sys.argv[3]}")
