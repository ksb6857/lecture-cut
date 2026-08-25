# -*- coding: utf-8 -*-
"""
words.json 의 타임스탬프가 실제 오디오와 얼마나 맞는지 측정한다.

- 오디오에서 10ms 단위 RMS 에너지를 뽑아 실제 발화/무음 마스크를 만든다
- words.json 으로 만든 마스크와 교차상관 → 전역 오프셋 추정
- 타임라인을 10구간으로 나눠 구간별 오프셋 → 드리프트 여부 판정
"""
import json
import sys
import wave
from pathlib import Path

import numpy as np

FRAME_MS = 10


def load_energy_db(wav_path):
    with wave.open(str(wav_path), "rb") as w:
        sr = w.getframerate()
        n = w.getnframes()
        raw = w.readframes(n)
    x = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    hop = int(sr * FRAME_MS / 1000)
    nf = len(x) // hop
    frames = x[: nf * hop].reshape(nf, hop)
    rms = np.sqrt((frames ** 2).mean(axis=1) + 1e-12)
    return 20 * np.log10(rms + 1e-12), sr


def speech_mask_from_audio(db, margin_db=12.0):
    """소음 바닥 대비 margin_db 이상이면 발화로 본다"""
    floor = np.percentile(db, 20)     # 조용한 20% 를 소음 바닥으로
    peak = np.percentile(db, 95)
    thr = max(floor + margin_db, peak - 25)
    return db > thr, floor, peak, thr


def mask_from_words(words, n_frames):
    m = np.zeros(n_frames, dtype=bool)
    for w in words:
        if w["type"] != "word":
            continue
        a = int(w["start"] * 1000 / FRAME_MS)
        b = int(w["end"] * 1000 / FRAME_MS)
        if b > a:
            m[max(0, a):min(n_frames, b)] = True
    return m


def best_offset(ref, test, max_shift_frames):
    """test 를 ±max_shift 만큼 밀어보며 일치도가 가장 높은 지점"""
    best, best_score = 0, -1
    scores = {}
    for s in range(-max_shift_frames, max_shift_frames + 1):
        shifted = np.roll(test, s)
        score = float((shifted == ref).mean())
        scores[s] = score
        if score > best_score:
            best_score, best = score, s
    return best * FRAME_MS / 1000.0, best_score, scores


def run(wav_path, words_path):
    db, sr = load_energy_db(wav_path)
    audio_mask, floor, peak, thr = speech_mask_from_audio(db)
    data = json.loads(Path(words_path).read_text(encoding="utf-8"))
    words = data["words"]
    vrew_mask = mask_from_words(words, len(db))

    print(f"오디오 {len(db)*FRAME_MS/1000/60:.1f}분, "
          f"소음바닥 {floor:.1f}dB, 피크 {peak:.1f}dB, 판정선 {thr:.1f}dB")
    print(f"실제 발화 비율 {audio_mask.mean()*100:.1f}% / "
          f"브루 단어 비율 {vrew_mask.mean()*100:.1f}%")
    print()

    off, score, _ = best_offset(audio_mask, vrew_mask, 200)  # ±2초
    base = float((vrew_mask == audio_mask).mean())
    print(f"[전역] 최적 오프셋 {off:+.2f}초 (일치율 {score*100:.1f}%, "
          f"보정 전 {base*100:.1f}%)")
    print()

    print("[구간별] 드리프트 점검")
    n = len(db)
    seg = n // 10
    offs = []
    for i in range(10):
        a, b = i * seg, (i + 1) * seg
        o, s, _ = best_offset(audio_mask[a:b], vrew_mask[a:b], 200)
        offs.append(o)
        print(f"  {a*FRAME_MS/1000/60:5.1f}~{b*FRAME_MS/1000/60:5.1f}분 : "
              f"오프셋 {o:+.2f}초 (일치율 {s*100:.1f}%)")
    spread = max(offs) - min(offs)
    print(f"\n  구간별 오프셋 편차 {spread:.2f}초 → "
          f"{'드리프트 있음(선형 보정 필요)' if spread > 0.3 else '드리프트 없음(단순 오프셋)'}")
    print()

    # 단어 경계가 실제로 소리 위에 있는지
    starts = [w["start"] for w in words if w["type"] == "word"]
    ends = [w["end"] for w in words if w["type"] == "word"]

    def hit_rate(times, delta):
        idx = [int((t + delta) * 1000 / FRAME_MS) for t in times]
        idx = [i for i in idx if 0 <= i < len(audio_mask)]
        return audio_mask[idx].mean() * 100

    print("[경계 정밀도] 단어 시작/끝 지점에 실제 소리가 있는 비율")
    for d in (-0.3, -0.15, 0.0, 0.15, 0.3):
        print(f"  {d:+.2f}초 지점 → 시작 {hit_rate(starts, d):5.1f}% / "
              f"끝 {hit_rate(ends, d):5.1f}%")

    # 무음이라 판단한 곳에 실제 소리가 있었는가 (= 말 잘림 위험)
    gaps = 0
    bad = 0
    prev_end = None
    for w in words:
        if w["type"] != "word":
            continue
        if prev_end is not None and w["start"] - prev_end >= 1.0:
            a = int(prev_end * 1000 / FRAME_MS)
            b = int(w["start"] * 1000 / FRAME_MS)
            if b > a and a >= 0 and b <= len(audio_mask):
                gaps += 1
                if audio_mask[a:b].mean() > 0.30:
                    bad += 1
        prev_end = max(prev_end or 0, w["end"])
    print(f"\n[컷 위험] 브루가 무음이라 본 1초 이상 구간 {gaps}곳 중 "
          f"실제로는 30% 이상 소리가 있던 곳: {bad}곳 ({100*bad/max(gaps,1):.1f}%)")


if __name__ == "__main__":
    run(sys.argv[1], sys.argv[2])
