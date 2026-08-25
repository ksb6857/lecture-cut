# 데스크톱(NVIDIA GPU)에서 돌리기

전사는 이 파이프라인에서 가장 오래 걸리는 단계다. GPU 가 있으면
**90분 강의 기준 CPU 1~2시간 → GPU 5~10분** 으로 줄어든다.
CPU 코어 수는 거의 영향이 없다. GPU 유무가 전부다.

## 1. 설치

```bash
git clone https://github.com/ksb6857/lecture-cut.git
cd lecture-cut
pip install -r requirements.txt
pip install faster-whisper
```

GPU 를 쓰려면 CUDA 라이브러리를 얹는다. CTranslate2 4.5+ 는
**CUDA 12 + cuDNN 9** 를 요구한다. pip 로 넣는 것이 가장 간단하다.

```bash
pip install nvidia-cublas-cu12 nvidia-cudnn-cu12
```

torch 는 VAD 에만 쓰이고 CPU 판으로도 충분하다. 굳이 CUDA 판을 원하면:

```bash
pip install torch --index-url https://download.pytorch.org/whl/cu124
```

## 2. 점검

```bash
python src/check_gpu.py
```

`[--]` 로 표시된 항목이 있으면 그 줄의 안내대로 처리한다.
대부분 위의 `nvidia-cublas-cu12 nvidia-cudnn-cu12` 한 줄로 끝난다.

## 3. 실행

원본 mp4 만 있으면 된다.

```bash
python src/analyze_audio.py "<원본.mp4>" work/<이름>_speech.json
```

```bash
python src/transcribe_per_segment.py "<원본.wav>" work/<이름>_speech.json work/<이름>_persegment.json large-v3 cuda
```

마지막 인자 `cuda` 가 GPU 를 쓰라는 뜻이다. 빼면 CPU 로 돈다.

`transcribe.py`(본 전사)도 같은 자리에 `cuda` 를 받는다:

```bash
python src/transcribe.py "<원본.mp4>" work/<이름>_speech.json work/<이름>_words_clean.json large-v3 cuda
```

## 4. 결과 주고받기

무거운 건 GPU 있는 PC 에서 돌리고, 캡컷 드래프트 생성은 편집할 PC 에서 한다.
중간 산출물(JSON)은 작아서 깃으로 오간다. 이 스킬 저장소가 아니라 **그 강의
프로젝트 저장소**에 넣는다(스킬 저장소는 `work/` 를 무시한다).

```bash
cd <작업>
git add work/ && git commit -m "ep03 전사" && git push
```

편집할 PC 에서 `git pull` 한 뒤 드래프트를 만든다.

**주의**: 캡컷 드래프트에는 원본 mp4 의 절대경로가 박힌다.
드래프트는 반드시 **편집할 PC 에서** 생성하고, 그 PC 에 원본이 같은 경로로
있어야 한다.

## 문제가 생기면

- `Library cudnn_ops64_9.dll is not found` → `pip install nvidia-cudnn-cu12`
- `CUDA driver version is insufficient` → NVIDIA 드라이버 업데이트
- VRAM 부족(large-v3 는 4GB 이상 필요) → 모델을 `medium` 으로 낮춘다
- 그래도 안 되면 마지막 인자를 `cpu` 로 바꿔 돌린다(느릴 뿐 결과는 같다)
