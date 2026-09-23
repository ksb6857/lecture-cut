# -*- coding: utf-8 -*-
"""원본 wav 의 10ms 프레임 세기(dBFS).

컷 지점이 소리 위에 떨어졌는지, 발화 덩어리 안에 끊어도 되는 짧은 무음이
있는지를 이 값으로 잰다. 위스퍼 낱말 시각은 ±0.1~0.3초 어긋나서 그것만 믿고
자르면 말 위에 컷이 떨어진다(2026-09-20, 컷 지점 904곳 중 84곳).

기준값은 실측에서 잡았다(2권 11차시, 191분 녹화, OBS 노이즈 게이트 켬).

    발화 안   중앙 -34dB · 25분위 -44.5dB · 10분위 -56dB
    발화 밖   거의 전부 -120dB (게이트가 닫혀 완전한 0)

그래서 **-45dB 를 넘으면 소리 위**, **-50dB 아래면 끊어도 되는 무음**으로 본다.
사람이 손본 편집본은 컷 지점 84곳이 전부 -50dB 아래였다.
"""
import wave
from pathlib import Path

import numpy as np

HOP = 0.01          # 프레임 간격 (초)
WIN = 0.02          # 세기를 재는 창 (초)
ON_SOUND = -45.0    # 이보다 크면 소리 위
SILENT = -50.0      # 이보다 작으면 끊어도 되는 무음


def compute(wav_path, cache=None):
    """프레임별 dBFS 배열. i 번째 프레임은 [i*HOP, i*HOP+WIN] 구간이다."""
    if cache and Path(cache).exists():
        return np.load(cache)
    w = wave.open(str(wav_path), "rb")
    sr, n, ch = w.getframerate(), w.getnframes(), w.getnchannels()
    a = np.frombuffer(w.readframes(n), dtype=np.int16).astype(np.float64)
    if ch > 1:
        a = a.reshape(-1, ch).mean(axis=1)
    a /= 32768.0
    hop, win = int(HOP * sr), int(WIN * sr)
    cs = np.concatenate([[0.0], np.cumsum(a * a)])
    nf = max(0, (len(a) - win) // hop)
    i0 = np.arange(nf) * hop
    ms = (cs[i0 + win] - cs[i0]) / win
    db = (10 * np.log10(ms + 1e-12)).astype(np.float32)
    if cache:
        np.save(cache, db)
    return db


def _idx(t):
    return int(round((t - WIN / 2) / HOP))


def level_at(db, t, half=0.01):
    """t 앞뒤 half 초 안에서 가장 큰 세기(dB). 범위 밖이면 -120."""
    i0, i1 = _idx(t - half), _idx(t + half)
    i0, i1 = max(0, i0), min(len(db) - 1, i1)
    if i1 < i0:
        return -120.0
    return float(db[i0:i1 + 1].max())


def silences(db, a, b, thr=SILENT, min_len=0.04):
    """[a, b] 안에서 thr 아래로 min_len 이상 이어지는 무음 구간들 [(시작, 끝)]."""
    i0, i1 = max(0, _idx(a)), min(len(db) - 1, _idx(b))
    if i1 <= i0:
        return []
    q = db[i0:i1 + 1] < thr
    out, k = [], 0
    while k < len(q):
        if not q[k]:
            k += 1
            continue
        j = k
        while j + 1 < len(q) and q[j + 1]:
            j += 1
        s = (i0 + k) * HOP + WIN / 2 - HOP / 2
        e = (i0 + j) * HOP + WIN / 2 + HOP / 2
        if e - s >= min_len:
            out.append((round(s, 3), round(e, 3)))
        k = j + 1
    return out


if __name__ == "__main__":
    import sys
    d = compute(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
    print(f"프레임 {len(d)} · 분위수 10/50/90: "
          f"{np.percentile(d, 10):.1f} / {np.percentile(d, 50):.1f} / "
          f"{np.percentile(d, 90):.1f} dB")
