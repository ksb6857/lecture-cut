# -*- coding: utf-8 -*-
"""위스퍼 전사를 CTC 모델로 한 번 더 받아 적어 맞춰 본다.

위스퍼는 자기회귀 디코더라 소리가 없는 데서도 그럴듯한 문장을 지어낸다
(「시청해주셔서 감사합니다」 「자막 제공 및 광고를 포함하고 있습니다」).
CTC 는 언어모델 없이 프레임마다 글자를 뱉으므로 소리가 없으면 아무것도
못 내놓는다. 그래서 환각을 기계로 판정할 수 있다.

VAD 가 찾은 발화 덩어리마다 따로 돌려 `compare_transcripts.py` 에 넘긴다.
실측: 110분 강의(발화 덩어리 767개)가 CPU 로 3.9분. GPU 는 필요 없다.

정확도는 위스퍼보다 낮다. **자막 문구를 여기서 가져오지 마라.**
소리가 있었는지 없었는지, 두 모델이 같은 말을 들었는지만 본다.

사용: python src/crosscheck_ctc.py <16k.wav> <speech.json> <out.json>
                                   [--모델 <hf이름>] [--device cpu|cuda]
"""
import json
import sys
import time
from pathlib import Path

import numpy as np
import soundfile as sf
import torch
from transformers import Wav2Vec2ForCTC, Wav2Vec2Processor

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cliargs import split_args  # noqa: E402

MODEL = "kresnik/wav2vec2-large-xlsr-korean"
SR = 16000
PAD = 0.10          # 덩어리 앞뒤 여유 (초)
CACHE = Path(__file__).resolve().parent.parent / "models" / "hf"


def run(wav_path, speech_path, out_path, model=MODEL, device="cpu"):
    import os
    os.environ.setdefault("HF_HOME", str(CACHE))
    speech = json.loads(Path(speech_path).read_text(encoding="utf-8"))["speech"]
    audio, sr = sf.read(wav_path, dtype="float32")
    if sr != SR:
        raise SystemExit(f"16kHz 모노 wav 가 아니다: {sr}Hz")
    if audio.ndim > 1:
        audio = audio.mean(axis=1)

    print(f"CTC 교차검증 시작: {model} ({device}) · 덩어리 {len(speech)}개")
    proc = Wav2Vec2Processor.from_pretrained(model)
    net = Wav2Vec2ForCTC.from_pretrained(model).to(device).eval()

    partial = Path(str(out_path) + ".partial.jsonl")
    done = {}
    if partial.exists():
        for line in partial.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                done[r["i"]] = r
        print(f"  이어서 시작 (이미 {len(done)}개)")

    out, t0 = [], time.time()
    with partial.open("a", encoding="utf-8") as fp:
        for i, (a, b) in enumerate(speech):
            if i in done:
                out.append(done[i])
                continue
            s = max(0, int((a - PAD) * SR))
            e = min(len(audio), int((b + PAD) * SR))
            chunk = audio[s:e]
            if len(chunk) < SR // 20:
                rec = {"i": i, "start": a, "end": b, "text": "",
                       "conf": 0.0, "frames": 0}
            else:
                inp = proc(chunk, sampling_rate=SR, return_tensors="pt",
                           padding=True)
                with torch.no_grad():
                    logits = net(inp.input_values.to(device)).logits
                probs = torch.softmax(logits, dim=-1)
                ids = torch.argmax(logits, dim=-1)
                nonblank = ids[0] != 0
                conf = (float(probs[0].max(-1).values[nonblank].mean())
                        if bool(nonblank.any()) else 0.0)
                rec = {"i": i, "start": a, "end": b,
                       "text": proc.batch_decode(ids)[0].strip(),
                       "conf": round(conf, 3), "frames": int(nonblank.sum())}
            out.append(rec)
            fp.write(json.dumps(rec, ensure_ascii=False) + "\n")
            fp.flush()
            if (i + 1) % 50 == 0:
                el = time.time() - t0
                spd = max(i + 1 - len(done), 1) / max(el, 1e-6)
                print(f"  {i+1}/{len(speech)}  경과 {el/60:.1f}분  "
                      f"남은 예상 {(len(speech)-i-1)/spd/60:.1f}분", flush=True)

    Path(out_path).write_text(
        json.dumps({"model": model, "pad": PAD, "segments": out},
                   ensure_ascii=False, indent=1), encoding="utf-8")
    partial.unlink(missing_ok=True)
    spoke = sum(1 for r in out if r["text"])
    print(f"OK: 덩어리 {len(out)}개 중 {spoke}개에서 소리를 찾았다 "
          f"-> {out_path}  ({(time.time()-t0)/60:.1f}분)")
    return out


if __name__ == "__main__":
    pos, opt = split_args(sys.argv[1:], {"--모델", "--model", "--device"})
    run(*pos[:3],
        model=opt.get("--모델") or opt.get("--model") or MODEL,
        device=opt.get("--device", "cpu"))
