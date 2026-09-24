# -*- coding: utf-8 -*-
"""강의 녹음에서 목소리 복제(ElevenLabs Professional Voice Cloning) 학습용 음성 묶음을 만든다.

학습에 좋은 소리 = 한 사람 목소리만, 배경음 없이, 말투가 고르게. 권장 길이 2~3시간(최소 30분),
파일은 MP3 192kbps 이상(ElevenLabs 안내, 2026-09).

컷 편집이 끝난 강의가 가장 좋다. 재발화·헛시작·긴 쉼이 이미 빠져 있다.
  - 편집본 음성 파일(러프컷 오디오를 내보낸 것)은 그대로 쓴다
  - 원본 + keep.json 이면 남는 블록만 이어 쓴다(from 초 앞은 뺀다. 인트로·오프닝 음악을 넣지 않으려고)

  - 편집본이 30분이 안 되면 원본 녹음 + 발화 구간(speech.json 에서 전사 낱말이 있는 것만, 앞뒤 0.15초)을 keep 으로 준다.
    재발화도 같은 목소리·같은 마이크라 학습에 써도 된다

검사
  - 표본율: 32kHz 아래 소재는 뺀다. 전사용으로 줄인 16kHz wav 는 8kHz 위가 비어서 원본으로 만든 묶음과
    음색이 10.5dB 달랐다(2026-09-24). 목소리 학습은 원본 소재(48kHz)에서 뽑는다
  - 배경음: 쉼(-55dB 아래) 비율이 너무 낮으면 음악이 깔린 것으로 보고 뺀다
  - 크기: -20 LUFS 로 맞춘다(강의마다 크기가 달라도 한 목소리로 배우게)
  - 여러 강의를 섞을 때는 음색을 먼저 잰다. 복제는 마이크 색깔과 후처리까지 따라 하므로 성질이 다른 녹음을 섞으면
    그 평균 소리가 난다

만든 뒤 업로드와 본인 확인(화면에 나온 문장을 직접 읽기)은 목소리 주인이 ElevenLabs 에서 직접 한다.

목록 파일(JSON):
  [{"name": "11차시", "media": ".../vh11_최종소재.mp4", "keep": ".../vh11_final_keep.json", "from": 90.44},
   {"name": "12차시", "media": ".../vs12_러프컷.wav"}]

사용: python voice_dataset.py <목록.json> <출력폴더> [--part 900] [--lufs -20]
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

SR = 44100


def pcm(media, keep=None, start_from=0.0):
    """소재 → 모노 44.1kHz float32. keep 이 있으면 남는 블록만 잇는다."""
    with tempfile.TemporaryDirectory() as td:
        raw = Path(td) / "a.raw"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(media), "-vn", "-ac", "1", "-ar", str(SR),
                        "-f", "f32le", str(raw)], check=True)
        x = np.fromfile(raw, dtype=np.float32)
    if keep is None:
        return x
    parts = []
    for a, b in keep:
        a = max(a, start_from)
        if b <= a:
            continue
        parts.append(x[int(a * SR):int(b * SR)])
    return np.concatenate(parts) if parts else np.zeros(0, np.float32)


def sample_rate(media):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=sample_rate",
                        "-of", "csv=p=0", str(media)], capture_output=True, text=True)
    try:
        return int(r.stdout.strip().splitlines()[0])
    except (ValueError, IndexError):
        return 0


def quiet_ratio(x, thr=-55.0):
    n = SR // 100
    m = len(x) // n
    if m == 0:
        return 0.0
    rms = np.sqrt((x[:m * n].reshape(m, n) ** 2).mean(axis=1))
    db = 20 * np.log10(np.maximum(rms, 1e-7))
    return float((db < thr).mean())


def cut_points(x, part):
    """part 초마다, 근처에서 가장 조용한 10ms 에서 나눈다."""
    n = SR // 100
    m = len(x) // n
    rms = np.sqrt((x[:m * n].reshape(m, n) ** 2).mean(axis=1))
    cuts, t = [0], part * 100
    while t < m - 60 * 100:
        lo, hi = int(t - 3000), int(min(m, t + 3000))
        k = lo + int(np.argmin(rms[lo:hi]))
        cuts.append(k * n)
        t = k + part * 100
    cuts.append(len(x))
    return list(zip(cuts[:-1], cuts[1:]))


def write_mp3(x, out, lufs):
    with tempfile.TemporaryDirectory() as td:
        raw = Path(td) / "a.raw"
        x.astype(np.float32).tofile(raw)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "f32le", "-ar", str(SR), "-ac", "1", "-i", str(raw),
                        "-af", f"loudnorm=I={lufs}:TP=-2:LRA=11", "-ar", str(SR), "-c:a", "libmp3lame",
                        "-b:a", "192k", str(out)], check=True)


def main(argv):
    pos, opt, k = [], {}, 0
    while k < len(argv):
        if argv[k].startswith("--"):
            opt[argv[k]] = argv[k + 1]
            k += 2
        else:
            pos.append(argv[k])
            k += 1
    items = json.loads(Path(pos[0]).read_text(encoding="utf-8"))
    out = Path(pos[1])
    out.mkdir(parents=True, exist_ok=True)
    part, lufs = float(opt.get("--part", 900)), float(opt.get("--lufs", -20))
    rows, total = [], 0.0
    for it in items:
        sr = sample_rate(it["media"])
        if 0 < sr < 32000:
            rows.append(f"| {it['name']} | - | 표본율 {sr}Hz | **뺌: 전사용으로 줄인 소리로 보임. 원본 소재를 주세요** |")
            print(rows[-1], flush=True)
            continue
        keep = json.loads(Path(it["keep"]).read_text(encoding="utf-8"))["keep_ranges"] if it.get("keep") else None
        x = pcm(it["media"], keep, float(it.get("from", 0)))
        qr = quiet_ratio(x)
        dur = len(x) / SR
        if qr < 0.05:
            rows.append(f"| {it['name']} | {dur / 60:.1f}분 | 쉼 비율 {qr:.0%} | **뺌: 배경음이 깔린 것으로 보임** |")
            continue
        for n, (a, b) in enumerate(cut_points(x, part), 1):
            f = out / f"{it['name']}_{n:02d}.mp3"
            write_mp3(x[a:b], f, lufs)
        total += dur
        rows.append(f"| {it['name']} | {dur / 60:.1f}분 | 쉼 비율 {qr:.0%} | 넣음 |")
        print(rows[-1], flush=True)
    text = "\n".join([f"# 목소리 학습용 음성 묶음", "", f"합계 **{total / 60:.1f}분** (권장 120~180분, 최소 30분)", "",
                      "| 강의 | 길이 | 확인 | 결과 |", "|---|---|---|---|", *rows, "",
                      f"파일: MP3 192kbps · 모노 · {lufs:.0f} LUFS · {part / 60:.0f}분 안팎으로 나눔"])
    (out / "목록.md").write_text(text + "\n", encoding="utf-8")
    print(f"합계 {total / 60:.1f}분 → {out}")


if __name__ == "__main__":
    main(sys.argv[1:])
