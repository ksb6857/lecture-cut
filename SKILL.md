---
name: lecture-cut
description: 강의 녹화 mp4 를 파형(VAD) 기준으로 자동 컷 편집해 캡컷(CapCut) 드래프트로 만든다. 늘어지는 쉼 정리, 재발화(말하다 다시 말한 것) 삭제, 의미 단위 자막 분할, 무음 드래프트 검증, 검수 보고서까지. 원격연수·온라인 강의·토킹헤드 영상에 쓴다. Use when the user asks to cut-edit a lecture recording, trim dead air or retakes from a talking-head video, or build a CapCut draft from an mp4. 트리거 — 컷 편집, 컷편집, 러프컷, 자동 편집, 무음 컷, 강의 영상 편집, 캡컷 드래프트, lecture-cut, autocut.
---

# lecture-cut — 강의 영상 러프컷 공장

90분짜리 강의 녹화를 받아 **캡컷 드래프트**로 내놓는다. 사람은 캡컷을 열어
마무리만 한다. 컷 경계는 파형에서 뽑고, 말의 내용 판단은 전사본으로 한다.

이 파일이 있는 폴더가 `<SKILL>` 이다. 아래 명령의 `<SKILL>` 을 실제 절대경로로
바꿔 실행한다. 산출물은 사용자의 **작업 폴더** `work/` 에 쌓는다(스킬 폴더가
아니라 그 강의 프로젝트 폴더). 아래에서는 그 폴더를 `<작업>` 이라 쓴다.

## 하는 일 / 안 하는 일

한다: 발화 검출, 전사, 두 번째 모델로 교차검증, 재발화 후보 탐지, 컷 계획,
캡컷 드래프트 생성, 소리 검증, 검수 보고서, 사용자가 손본 편집본에서 컷 기준 역산.

규격 프로필을 주면 납품 규격 점검도 한다(해상도·길이·파일명·라우드니스,
허용 구간 밖의 자막, 금지 표현, 슬레이트 잔존). 기계가 못 보는 항목은 못 본다고
목록으로 남긴다.

안 한다: 강조 상자·스티커·확대 같은 효과, 오프닝/클로징 조립, 오디오 라우드니스
보정, 핵심 자막 문구 작성. 이건 플랫폼마다 달라서 각 프로젝트 폴더가 맡는다.

## 실행 전 점검

```bash
ffmpeg -version                                    # PATH 에 있어야 한다
python -c "import pycapcut, numpy, torch"          # requirements.txt
python -c "import transformers, soundfile"         # 3.5단계 교차검증용
python <SKILL>/src/check_gpu.py                    # GPU 는 없어도 된다(느릴 뿐)
```

없는 것이 있으면 `pip install -r <SKILL>/requirements.txt` 로 채운다.
ffmpeg 이 없으면 윈도우는 `winget install --id Gyan.FFmpeg -e`.

캡컷 드래프트 폴더는 자동으로 찾는다. 다른 드라이브에 설치했으면 환경변수
`CAPCUT_DRAFT_ROOT` 에 경로를 지정한다.

## 절대 어기면 안 되는 것

전부 실제로 사고가 났던 항목이다. 자세한 사고 경위는
[docs/안전규칙.md](docs/안전규칙.md).

1. **캡컷이 실행 중이면 드래프트를 건드리지 않는다.** 도구가 스스로 멈춘다.
   막고 돌리면 사용자가 편집하던 프로젝트가 통째로 날아간다.
2. **사람이 편집한 드래프트를 덮어쓰지 않는다.** 만들기 전에 트랙 수와 수정
   시각으로 사람 손이 닿았는지 본다. 닿았으면 다른 이름을 쓴다.
3. **캡컷 스키마 값을 추측해 넣지 않는다.** 캡컷이 직접 만든 정상 드래프트에서
   확인하고 넣는다(`verify_draft_audio.py --compare <정상드래프트>`).
4. **드래프트는 소리가 나는 걸 확인한 뒤에 넘긴다.** 빌드가 소리 검사를 자동으로
   돌리고 실패하면 멈춘다. 이 검사를 우회하거나 지우지 마라.
5. **드래프트를 폴더 이름으로 찾지 않는다.** 캡컷은 이름이 겹치면 뒤에 `(1)` 을
   붙여 폴더를 바꿔치는데 내부 절대경로는 따라오지 않는다.
   `draft_doctor.py 진단` 으로 끊긴 경로가 0인지 붙이기 전후로 본다.
6. **원본 mp4 는 로컬 고정 경로에 둔다.** 드래프트에 절대경로가 박히므로
   다운로드 폴더나 클라우드 동기화 폴더에 두면 나중에 통째로 끊긴다.
7. **한 강의에 작업 드래프트는 하나만 둔다.** 판(버전)은 캡컷 목록이 아니라
   `draft_snapshot.py` 로 목록 밖에 남긴다.

사용자에게 터미널 명령을 복사해 시키지 마라. 전부 이 스킬을 쓰는 쪽이 직접
실행하고, 사용자에게는 결과만 보고한다.

## 파이프라인

체크리스트를 그대로 복사해 진행하면서 채운다.

```
[ ] 0 파트 병합   merge_parts         → 원본이 한 벌이면 건너뛴다
[ ] 1 발화 검출   analyze_audio       → <이름>_speech.json
[ ] 2 전사        transcribe          → <이름>_words.json
[ ] 3 재발화      transcribe_per_segment + find_hidden/repeat_retakes
[ ]   슬레이트    find_slates         → 파트별 촬영일 때만
[ ] 3.5 교차검증  crosscheck_ctc + compare_transcripts + fill_missing_words
[ ] 4 내용 판단   청크 분석(LLM)      → <이름>_results/result_NN.json
[ ] 5 병합        merge_analysis      → <이름>_analysis.json, _retakes.json
[ ] 6 컷 계획     cut_planner         → <이름>_keep_ranges.json
[ ] 7 드래프트    build_capcut_draft  → 캡컷 드래프트 + SRT (소리 검증 자동)
[ ] 8 검증        verify_cuts         → 말 잘림 0건 확인
[ ] 9 보고서      make_report         → <이름>_보고서.md
[ ] 10 규격 점검  check_guidelines    → 프로필이 있을 때만
```

`<이름>` 은 강의 하나를 가리키는 짧은 영문 이름을 쓴다(`ep03` 처럼). 한글
파일명은 torch 가 모델을 못 읽는 문제를 부르니 피한다.

## 0. 파트를 나눠 찍었으면 먼저 잇는다

원본이 한 벌이면 이 단계를 건너뛴다. 파트마다 끊어 찍어 여러 벌이면 뒤 단계가
전부 원본 하나를 전제하므로 여기서 한 벌로 만든다.

```bash
python <SKILL>/src/merge_parts.py <촬영원본폴더> "C:\video\<이름>.mp4" --json <작업>/work/<이름>_parts.json
```

파일 이름이 `차시_파트번호_파트명_테이크[_OK]` 형식이면 파트마다 쓸 테이크를
고른다. `_OK` 가 붙은 것이 최우선이고, 없으면 테이크 번호가 큰 것을 쓴다.
**촬영 순서가 아니라 파트번호 순서로** 잇는다. 규격이 전부 같으면 무재인코딩이라
90분 분량도 몇 초에 끝난다.

테이크마다 앞에 육성 슬레이트("성명, 몇 차시, 테이크 1")를 넣어 찍었으면,
전사(2단계)를 마친 뒤 찾아서 지운다.

```bash
python <SKILL>/src/find_slates.py <작업>/work/<이름>_words.json <작업>/work/<이름>_parts.json <작업>/work/<이름>_slates.json
```

결과를 6단계 `cut_planner` 에 `<이름>_retakes.json` 과 함께 넘기면 된다.
**슬레이트를 못 찾은 파트는 지우지 않고 알려만 준다.** 슬레이트를 빼먹고 찍은
파트에서 앞부분을 통째로 지우면 강의 첫 문장이 사라진다.

## 단계별 명령

### 1. 발화 검출 (파형)

```bash
python <SKILL>/src/analyze_audio.py "<원본.mp4>" <작업>/work/<이름>_speech.json
```

컷 경계의 기준은 이 파일이다. STT 단어 타임스탬프로 자르면 안 된다. 실측에서
단어 경계가 앞뒤로 0.3초씩 헐렁했고, STT 가 무음이라 본 1초 이상 구간의 21.9%에
실제로는 소리가 있었다.

### 2. 전사

```bash
ffmpeg -v error -i "<원본.mp4>" -vn -ac 1 -ar 16000 -c:a pcm_s16le -y <작업>/work/<이름>.wav
python <SKILL>/src/transcribe.py <작업>/work/<이름>.wav <작업>/work/<이름>_speech.json <작업>/work/<이름>_words.json large-v3 cuda <작업>/glossary/<이름>.txt
```

**용어집은 강의마다 새로 쓴다.** 마지막 인자가 그 파일이다. 다른 강의 용어집을
그대로 두면 위스퍼가 짧은 무음 구간에서 그 문장을 통째로 뱉는다. 강의에 맞는
용어집을 주면 전문용어 오전사가 크게 준다(실측 9종 중 7종).

마지막에서 두 번째 인자가 `cuda` 면 GPU, `cpu` 면 CPU 다. 90분 강의가 GPU 5~10분,
CPU 1~2시간 걸린다. 오래 걸리니 백그라운드로 돌린다.
브루(Vrew) 파일이 있으면 1·2단계 대신 `extract_vrew.py` 를 써도 되지만,
컷 경계는 여전히 1단계 결과를 쓴다.

### 3. 재발화 찾기

말하다 막혀서 다시 말한 대목이다. **전사본만 봐서는 안 보인다** — Whisper 는
같은 문장이 연달아 나오면 반복 억제 필터가 하나를 지운다. 그래서 덩어리별로
따로 전사한다.

```bash
python <SKILL>/src/transcribe_per_segment.py <작업>/work/<이름>.wav <작업>/work/<이름>_speech.json <작업>/work/<이름>_persegment.json large-v3 cuda --용어집 <작업>/glossary/<이름>.txt
python <SKILL>/src/find_hidden_retakes.py <작업>/work/<이름>.wav <작업>/work/<이름>_speech.json <작업>/work/<이름>_words.json <작업>/work/<이름>_hidden.json
python <SKILL>/src/find_repeat_retakes.py <작업>/work/<이름>_words.json <작업>/work/<이름>_auto.json --review <작업>/work/<이름>_review.json
```

`find_repeat_retakes` 는 결과를 두 등급으로 나눈다. `auto` 는 컷 계획에 그대로
먹이고, `review` 는 보고서에만 적는다. 중간에 끊겨도 `.partial.jsonl` 에 남아
같은 명령으로 이어서 한다.

**닮았다고 다 재발화가 아니다.** 유사도 0.64 로 후보에 오른 두 문장이 실제로는
서로 다른 항목이었던 사례가 있다. 어느 테이크를 지울지는 후보 목록을 읽고
직접 판단한다. 원칙은 완성도 높은 테이크 하나만 남기고 그 앞의 실패 테이크를
지우는 것. 판정은 시각을 손으로 옮겨 적지 말고 **덩어리 번호로 적어** 스크립트가
시각을 가져가게 한다.

### 3.5. 교차검증 — 위스퍼가 지어낸 말과 흘린 말을 찾는다

위스퍼 한 벌로는 **없던 말을 지어낸 것**과 **있던 말을 통째로 흘린 것**을
못 본다. 둘 다 높은 confidence 로 나와서 임계값으로 못 거른다. 언어모델이 없는
CTC 모델을 하나 더 돌려 맞춘다. **CPU 로 110분 강의가 4분이다. GPU 는 필요 없다.**

```bash
python <SKILL>/src/crosscheck_ctc.py <작업>/work/<이름>.wav <작업>/work/<이름>_speech.json <작업>/work/<이름>_ctc.json
python <SKILL>/src/compare_transcripts.py <작업>/work/<이름>_words.json <작업>/work/<이름>_speech.json <작업>/work/<이름>_persegment.json <작업>/work/<이름>_ctc.json <작업>/work/<이름>_교차검증.md --접두 <작업>/work/<이름>
python <SKILL>/src/fill_missing_words.py <작업>/work/<이름>_words.json <작업>/work/<이름>_missing.json <작업>/work/<이름>_words_full.json
```

**메운 뒤에는 4단계부터 `_words_full.json` 을 words.json 자리에 쓴다.**
통짜 전사가 흘린 말이 전사에 없으면 재발화 판정이 그 구간을 못 본다. 같은
문장을 세 번 말했는데 전사에 두 번만 있어 러프컷에 중복이 남은 사고가 났다.

`_hallucination.json` 은 6단계 `cut_planner` 에 다른 삭제 지시와 함께 넘긴다.

자세한 것과 실측값은 [docs/교차검증.md](docs/교차검증.md).


### 4. 내용 판단 (LLM 청크 분석)

```bash
python <SKILL>/src/make_llm_transcript.py <작업>/work/<이름>_words_full.json <작업>/work/<이름>_chunks
```

3.5단계를 돌렸으면 `_words_full.json` 을 쓴다. 안 돌렸으면 `_words.json` 이다.

청크마다 서브에이전트를 병렬로 띄워 삭제 지시와 자막 교정을 받는다. 지시문과
JSON 형식은 [docs/청크분석.md](docs/청크분석.md) 에 있다. 결과는
`<작업>/work/<이름>_results/result_NN.json` 으로 저장한다.

### 5~6. 병합과 컷 계획

```bash
python <SKILL>/src/merge_analysis.py <작업>/work/<이름>_results <작업>/work/<이름>_analysis.json <작업>/work/<이름>_retakes.json
python <SKILL>/src/cut_planner.py <작업>/work/<이름>_speech.json <작업>/work/<이름>_words.json <작업>/work/<이름>_keep_ranges.json <작업>/work/<이름>_retakes.json <작업>/work/<이름>_hallucination.json
```

쉼을 얼마나 남길지는 `src/cut_planner.py` 의 `PARAMS` 가 정본이다. 기본값과
그 근거는 [docs/컷-파라미터.md](docs/컷-파라미터.md). **문서에 적힌 숫자를
믿지 말고 코드를 읽어라.**

### 7. 드래프트 생성

```bash
python <SKILL>/src/build_capcut_draft.py <작업>/work/<이름>_words.json <작업>/work/<이름>_keep_ranges.json <작업>/work/<이름>_analysis.json "<원본.mp4>" <드래프트이름> <작업>/work/<이름>_speech.json
```

**나레이션 전체 자막을 금지하는 납품 규격이면 `--no-captions` 를 붙인다.**
SRT 파일은 그대로 만들되 드래프트에는 자막을 깔지 않는다. 깔아 두면 편집자가
일일이 지워야 하고 한둘 남으면 검수에 걸린다. SRT 는 검수와 자막 문구 작성에
계속 쓰인다.

끝에서 `verify_draft_audio.py` 가 자동으로 돈다. 소리가 안 나는 드래프트면
거기서 빌드가 멈춘다. `draft_content.json` 만 읽으면 무음 드래프트도 멀쩡해
보이므로(volume 1.0, has_audio True) 이 검사 없이는 캡컷에서 열어보기 전까지
아무도 모른다.

### 8~9. 검증과 보고서

```bash
python <SKILL>/src/verify_cuts.py <작업>/work/<이름>_speech.json <작업>/work/<이름>_keep_ranges.json
python <SKILL>/src/make_report.py <작업>/work/<이름>_words.json <작업>/work/<이름>_keep_ranges.json <작업>/work/<이름>_analysis.json <작업>/work/<이름>_보고서.md "<제목>"
python <SKILL>/src/draft_doctor.py 진단
```

`verify_cuts` 의 "발화 중간 절단" 은 **0건이어야 한다.** 0이 아니면 컷 계획을
고친다. 단계마다 **한 일의 개수**를 확인해라. 0이면 뭔가 잘못된 것이다.

### 10. 납품 규격 점검 (프로필이 있을 때)

플랫폼 납품 규격을 프로필 JSON 으로 적어 두었으면 기계가 볼 수 있는 항목을
확인한다. 해상도·길이·파일명·라우드니스, 허용 구간 밖의 자막, 전사본에 남은
금지 표현과 슬레이트.

```bash
python <SKILL>/src/check_guidelines.py --프로필 <규격프로필.json> --드래프트 <드래프트이름> --전사 <작업>/work/<이름>_words.json --보고서 <작업>/work/<이름>_점검.md
```

최종 mp4 를 내보낸 뒤에는 영상 파일을 위치 인자로 준다.

```bash
python <SKILL>/src/check_guidelines.py <최종1.mp4> <최종2.mp4> --프로필 <규격프로필.json> --보고서 <작업>/work/<이름>_제출점검.md
```

프로필 만드는 법은 [docs/규격점검.md](docs/규격점검.md). **기계가 못 보는
항목은 프로필의 `직접확인` 에 적어 두면 보고서 끝에 체크박스로 실린다.**
그 목록을 사용자에게 그대로 넘긴다. 건너뜀이 많으면 통과 건수를 믿지 마라.

## 끝내기

검수 보고서를 사용자에게 넘기고 세 가지를 함께 알린다: 완성 드래프트 이름,
원본 대비 줄어든 길이, 사람이 직접 들어봐야 할 구간(medium 판정과 review 등급).

드래프트를 만든 뒤 판을 하나 저장해 둔다.

```bash
python <SKILL>/src/draft_snapshot.py 저장 <드래프트이름> 러프컷완료
```

## 사용자가 손본 뒤

사용자가 캡컷에서 더 자른 곳을 걷어 올려 다음 강의의 기준으로 삼는다.

```bash
python <SKILL>/src/diff_user_cuts.py <드래프트> <작업>/work/<이름>_keep_ranges.json <작업>/work/<이름>_words.json --json <작업>/work/<이름>_정답지.json
python <SKILL>/src/learn_from_edit.py <사람이_손본_드래프트> <자동편집_드래프트> <작업>/work/<이름>_speech.json <작업>/work/<이름>_words.json
```

**검출 규칙이나 파라미터를 바꿨으면 반드시 `--eval <정답지>` 로 재현율·정밀도를
다시 재고 나서 커밋한다.** 쉼이 길다는 말이 나와도 파라미터부터 만지지 마라.
상한값과 체감은 다르다. 편집본에서 실제로 들리는 쉼을 문장 중간과 문장 끝으로
갈라 먼저 재라.

사용자가 얹은 오디오·자막 트랙이 있는데 컷을 다시 하면
`port_tracks.py` 로 옮긴다. 그냥 복사하면 타임라인이 밀려 엉뚱한 자리에 놓인다.

## 문제가 생기면

| 증상 | 도구 |
|---|---|
| 캡컷에서 전 클립이 "오디오가 분리됨", 소리 없음 | `repair_sound_separated.py` |
| 미디어 연결 창이 뜬다 / 소재가 끊겼다 | `draft_doctor.py 수리 <드래프트>` |
| 소재를 다른 폴더로 옮겨야 한다 | `relocate_media.py` (드래프트 경로까지 같이 고친다) |
| 트랙 순서가 어긋난다 | `normalize_draft.py` |
| 재녹음 오디오와 원본 소리가 겹쳐 들린다 | `mute_under_audio.py` |
| 삭제 지시가 서로 겹친다 | `resolve_delete_conflicts.py` |
| 되돌리고 싶다 | `draft_snapshot.py 목록` 후 `복원` |

## 더 읽을 것

- [docs/안전규칙.md](docs/안전규칙.md) — 캡컷 드래프트를 깨뜨린 사고들과 대응
- [docs/컷-파라미터.md](docs/컷-파라미터.md) — 쉼 길이 기준값과 근거
- [docs/청크분석.md](docs/청크분석.md) — 4단계 LLM 지시문과 JSON 형식
- [docs/규격점검.md](docs/규격점검.md) — 납품 규격 프로필 만드는 법
- [docs/교차검증.md](docs/교차검증.md) — 3.5단계 두 번째 모델과 실측값
- [docs/GPU-SETUP.md](docs/GPU-SETUP.md) — GPU 설치·점검·문제 해결
