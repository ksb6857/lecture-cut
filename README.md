# lecture-cut

강의 녹화 mp4 를 받아 **캡컷(CapCut) 드래프트**로 만들어 주는 Claude Code
스킬이다. 늘어지는 쉼을 정리하고, 말하다 다시 말한 대목을 지우고, 자막을 의미
단위로 끊는다. 마무리는 캡컷에서 사람이 한다.

90분 원격연수 녹화 다섯 편을 만들면서 굳힌 수치와 사고 대응이 그대로 들어 있다.

```
원본 mp4 ─▶ 발화 검출(VAD) ─▶ 전사 ─▶ 재발화 판정 ─▶ 컷 계획
                                                        │
                              캡컷 드래프트 + SRT ◀──────┤
                              검수 보고서       ◀──────┘
```

## 이걸 쓰면

- 90분 녹화가 25~30분으로 줄어든 드래프트가 나온다
- 컷은 진짜 무음에서만 한다. 드래프트를 만들기 전에 검산 게이트(`final_check`)가
  소리 위 컷, 쉼 규칙, 지운 말의 잔여, 되풀이를 재고 기준을 넘으면 멈춘다
- 소리 없는 드래프트를 넘기는 사고가 빌드 단계에서 막힌다
- 사람이 들어봐야 할 구간이 검수 보고서에 타임코드로 정리된다
- 요청하면 효과도 얹는다. 교안(pptx)에 나타내기 애니메이션을 넣고, 이미 찍은 영상에는
  교안 단계와 작은 글씨 확대를 굽고, 강조 상자와 장면 전환을 드래프트에 넣는다
- 보여 주기 전에 렌더한 미리보기를 스스로 검사한다(길이, 이음매 튐, 효과 경계 확인 그림)
- 전사는 ElevenLabs Scribe(유료, 키가 있을 때)를 먼저 쓰고, 없으면 로컬 위스퍼로 한다. 한 강의로 재 보니
  Scribe 가 낱말 시각(시작 오차 90%: 0.51초 → 0.09초)과 용어 표기에서 앞섰다. Scribe 가 지운 되풀이는
  다시 전사해 메운다(`fill_uncovered`). 두 전사를 같은 녹음으로 비교하는 도구도 있다
- 규격보다 길면 뺄 후보를 역할별로 골라 무엇·왜·빼면과 누적 길이를 표로 보여 준다. 사람이 영상을 보며
  고르고 싶으면 후보를 드래프트에 노란 글자로 표시한다(`apply_notes`)

스티커·BGM, 오프닝·클로징 조립, 오디오 라우드니스 보정은 들어 있지 않다.
플랫폼마다 달라서 각자 프로젝트 폴더에서 한다.

## 설치

필요한 것: Windows 또는 macOS, Python 3.10 이상, ffmpeg, 캡컷(국제판),
Claude Code.

```bash
git clone https://github.com/ksb6857/lecture-cut.git
cd lecture-cut
pip install -r requirements.txt
```

ffmpeg 이 없으면 윈도우는 `winget install --id Gyan.FFmpeg -e`,
맥은 `brew install ffmpeg`.

### 스킬로 등록

Claude Code 가 이 폴더를 스킬로 읽게 한다. 개인용으로 쓰려면
`~/.claude/skills/lecture-cut` 로 링크한다.

윈도우 — 정션(junction)은 관리자 권한이 필요 없다. 학교 컴퓨터에서도 된다.

```powershell
New-Item -ItemType Junction -Path "$env:USERPROFILE\.claude\skills\lecture-cut" -Target "C:\projects\lecture-cut"
```

맥·리눅스:

```bash
ln -s "$PWD" ~/.claude/skills/lecture-cut
```

링크가 안 되면 아예 `~/.claude/skills/lecture-cut` 에서 clone 해도 된다.
폴더째 복사하면 `git pull` 로 갱신이 안 된다.

특정 프로젝트에서만 쓸 거면 `<프로젝트>/.claude/skills/lecture-cut` 에 링크한다.

### 확인

Claude Code 를 켜고 물어본다. "lecture-cut 스킬 있어?" 라고 하면 스킬 목록에
잡혔는지 답한다. 그다음:

```
C:\video\ep03.mp4 컷 편집해줘
```

Claude 가 [SKILL.md](SKILL.md) 를 읽고 파이프라인을 순서대로 돌린다.
**명령어를 직접 칠 필요는 없다.**

## GPU

전사가 제일 오래 걸린다. NVIDIA GPU 가 있으면 90분 강의 기준 CPU 1~2시간이
5~10분으로 줄어든다. 설치와 점검은 [docs/GPU-SETUP.md](docs/GPU-SETUP.md),
확인은 `python src/check_gpu.py`.

GPU 가 없어도 돌아간다. 느릴 뿐 결과는 같다.

## 캡컷 버전

국제판 CapCut(8.x~10.x대)은 드래프트가 평문 JSON 이라 이 도구가 읽고 쓴다.
**중국판 剪映 6.0 이상은 드래프트가 암호화라 쓸 수 없다.** 캡컷이 자동
업데이트로 암호화 판으로 넘어가면 이 도구가 멈추므로, 작업 중인 강의가 있으면
캡컷 업데이트를 미루는 편이 안전하다.

드래프트 폴더는 자동으로 찾는다. 다른 드라이브에 설치했으면 환경변수로 지정한다.

```
CAPCUT_DRAFT_ROOT=D:\CapCut\User Data\Projects\com.lveditor.draft
```

## 여러 사람이 같이 쓸 때

**드래프트는 각자 자기 PC 에서 만든다.** 원본 mp4 경로가 절대경로로 박혀
다른 PC 로 복사해도 열리지 않는다.

주고받는 것은 `work/` 의 계획 JSON 이다. 작아서 깃으로 오간다. 받은 쪽에서
7단계만 다시 돌리면 같은 드래프트가 나온다.

무거운 전사는 GPU 있는 PC 에서 돌리고 결과 JSON 만 넘겨도 된다.

## 문서

| 문서 | 내용 |
|---|---|
| [SKILL.md](SKILL.md) | 파이프라인 전체 절차. Claude 가 읽는 문서 |
| [docs/안전규칙.md](docs/안전규칙.md) | 캡컷 드래프트를 깨뜨린 사고들과 대응 |
| [docs/컷-파라미터.md](docs/컷-파라미터.md) | 쉼 길이 기준값과 근거 |
| [docs/컷-마무리.md](docs/컷-마무리.md) | 무음에서만 나누기, 들리는 대본, 검산 게이트 |
| [docs/효과.md](docs/효과.md) | 교안 애니메이션, 강조 상자, 장면 전환, 작은 글씨 확대 |
| [docs/교차검증.md](docs/교차검증.md) | 전사를 두 번째 모델로 검증 |
| [docs/청크분석.md](docs/청크분석.md) | LLM 지시문과 JSON 형식 |
| [docs/노하우-지도.md](docs/노하우-지도.md) | 공통·플랫폼·강의 노하우를 어디에 두나 |
| [docs/피드백-원장.md](docs/피드백-원장.md) | 받은 지적과 그걸 막는 도구 |
| [docs/GPU-SETUP.md](docs/GPU-SETUP.md) | GPU 설치·점검·문제 해결 |

값을 바꾸기 전에 `src/cut_planner.py` 의 주석부터 읽어라. 1차부터 5차까지
왜 그 값이 됐는지가 실측 수치와 함께 남아 있다.

## 만든 것 위에

- [pycapcut](https://github.com/GuanYixuan/pyCapCut) — 캡컷 드래프트 생성
- [silero-vad](https://github.com/snakers4/silero-vad) — 발화 검출
- [faster-whisper](https://github.com/SYSTRAN/faster-whisper) — 전사

## 라이선스

MIT. [LICENSE](LICENSE) 참조.
