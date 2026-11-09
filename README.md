# whiteboard-shorts

블로그 글 주소나 원문을 넣으면, **화이트보드 그림 스타일의 9:16 세로 숏폼 영상(MP4)** 을 자동으로 만들어 주는 프로그램입니다.

```
블로그 글 → 요약 → 장면별 대본 → 장면별 그림 → 한국어 음성 → 자막 → 손으로 그리는 듯한 영상 → final.mp4
```

- 결과: 1080×1920 MP4, 30~60초 (기본 목표 45초), 장면 6개 안팎
- 그림: 흰 배경에 검은 선으로 그린 화이트보드 그림. 모든 장면에 같은 캐릭터와 그림체
- 영상: 그림이 손으로 그리듯 차례로 나타나고, 아래에 자막. 마지막 장면에 "AI 생성 음성" 표기
- AI: OpenAI API만 사용 (글 생성, 그림 생성, 음성 생성). 영상 합성은 내 컴퓨터의 FFmpeg로 처리

## 처리 단계

| 단계 | 하는 일 | 도구 | API 비용 |
|---|---|---|---|
| S1 추출 | 블로그 주소에서 본문을 가져오거나, 원문 파일을 읽음 | requests, BeautifulSoup | 없음 |
| S2 요약 | 핵심 메시지·핵심 포인트·원문 숫자 정리 | OpenAI `gpt-6.1-sol` | 있음 |
| S3 대본 | 도입·설명·결론 구조의 장면별 대본 (음성용 문장과 자막용 문장을 따로) | OpenAI `gpt-6.1-sol` | 있음 |
| S4 그림 묘사 | 장면별 그림 설명 + 공통 그림체 문장 | OpenAI `gpt-6.1-sol` | 있음 |
| S5 그림 | 장면별 화이트보드 그림 | OpenAI `gpt-image-2.5-flare` | 있음 |
| S6 음성 | 장면별 한국어 음성, 실제 길이 측정 | OpenAI `gpt-4o-mini-tts` | 있음 |
| S7 자막 | 음성 길이에 맞춘 자막(SRT)과 자막 그림 | Pillow | 없음 |
| S8 장면 영상 | 그림이 손으로 그리듯 나타나는 장면 영상 | whiteboard-animator, FFmpeg | 없음 |
| S9 합성 | 장면 영상 + 음성 + 자막 → final.mp4 | FFmpeg | 없음 |

각 단계는 결과를 파일로 저장합니다. 같은 명령을 다시 실행하면 이미 만든 결과를 그대로 쓰고 **API를 다시 부르지 않습니다.**

## 준비물

| 준비물 | 설명 |
|---|---|
| macOS | 자막에 macOS 기본 글꼴(Apple SD 산돌고딕 Neo)을 씁니다. 다른 운영체제에서는 `config.toml`의 `font_path`를 한국어 글꼴로 바꿔야 합니다 |
| Python 3.12 | `brew install python@3.12` |
| FFmpeg | `brew install ffmpeg` (`ffmpeg`, `ffprobe` 명령이 필요합니다) |
| OpenAI API 키 | 위 표의 세 모델을 쓸 수 있는 키. 비용이 발생합니다 (아래 "비용과 시간") |

## 설치

터미널에서 순서대로 입력합니다.

```bash
git clone https://github.com/ianchaoslab/whiteboard-shorts.git
cd whiteboard-shorts
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

설치되는 패키지가 많아 몇 분 걸릴 수 있습니다. 이후 터미널을 새로 열 때마다 `source .venv/bin/activate`를 먼저 입력합니다.

## API 키 설정 (.env)

```bash
cp .env.example .env
```

`.env` 파일을 텍스트 편집기로 열어 `OPENAI_API_KEY=` 뒤에 키를 붙여 넣고 저장합니다.

```
OPENAI_API_KEY=여기에-내-키
```

- 프로그램은 실행할 때 `.env`에서 키를 읽습니다. 코드에는 키를 적지 않습니다.
- `.env`는 `.gitignore`에 들어 있어 Git에 올라가지 않습니다. **절대 공유하지 마세요.**
- 연결 확인 (아주 짧은 호출 1번, 약 $0.001): `python run.py check`

## 실행 방법

### 1) 예시 글로 바로 시험

```bash
python run.py --text-file examples/sample_post.txt --yes
```

약 2~3분 뒤 `outputs/custom-sample_post_날짜시각/final.mp4`가 만들어집니다.
`examples/sample_post.txt`는 이 저장소를 위해 새로 쓴 짧은 글입니다.

### 2) 원문 파일로 만들기 (`--text-file`)

아래 형식의 텍스트 파일(UTF-8)을 만들어 넣습니다.

```
제목: 글 제목
주소: (출처를 적거나 비워 둠)
본문:
본문 내용을 여기에 붙여 넣습니다.
여러 줄이어도 됩니다.
```

```bash
python run.py --text-file 내글.txt --yes
```

### 3) 블로그 주소로 만들기 (`--url`)

```bash
python run.py --url https://blog.naver.com/블로그아이디/글번호 --yes
```

- **자동 수집을 허락받은 블로그만** 주소로 가져옵니다. 허락 목록은 `config.toml`의 `[sources] allowed_blog_ids`입니다.
- 목록에 없는 블로그는 접속하지 않고 "원문을 붙여넣어 주세요"라고 안내합니다. 이때는 `--text-file`을 쓰세요.
- 같은 글은 한 번만 접속하고, 가져온 글은 `samples/web/`에 저장해 다시 씁니다 (Git 제외).

### 자주 쓰는 옵션

| 옵션 | 하는 일 |
|---|---|
| `--yes` | 그림을 새로 만들기 전에 묻는 비용 확인 질문을 건너뜀 (자동 실행용) |
| `--dry-run` | API를 부르지 않고 단계별 계획과 예상 비용만 보여줌 |
| `--step s5` | 한 단계만 실행 (`s1` ~ `s9`) |
| `--force` | 결과가 있어도 그 단계를 다시 만듦 (API를 다시 부름) |
| `--new` | 새 결과 폴더에서 처음부터 |
| `--scenes 1,3` | S5·S6·S8에서 일부 장면만 |
| `--voice marin` | 음성 목소리 바꾸기 (비교용, 기본은 `config.toml`) |
| `--effect wipe` | 이번 실행만 드로잉 효과 바꾸기 (결과는 `final_wipe.mp4`로 따로 저장) |

### 결과 폴더

```
outputs/<이름>_<날짜시각>/
├── final.mp4          완성 영상
├── scenes.json        장면별 대본(음성용·자막용), 그림 프롬프트, 길이
├── summary.json       요약
├── subtitles.srt      자막
├── images/            장면별 그림 (원본과 1080×1920 맞춤본)
├── audio/<목소리>/     장면별 음성
├── clips_whiteboard/  장면별 영상
└── run_log.json       단계별 성공/실패, 걸린 시간, API 호출별 토큰·비용
```

## 데모 페이지 (웹 화면)

```bash
source .venv/bin/activate
streamlit run demo/app.py
```

브라우저에서 `http://localhost:8501`이 열립니다. 끝낼 때는 터미널에서 `Ctrl + C`.

한 화면에서 **블로그 글 주소 입력 → [영상 만들기] → 결과**만 합니다.

1. 블로그 글 주소를 넣고 Enter → 글 제목이 짧게 표시됩니다.
2. **[영상 만들기]** → 진행 표시줄로 단계와 걸린 시간을 보여줍니다 (2~3분).
3. 완성되면 영상 재생, **MP4 다운로드** 버튼, **대본 보기**(접혀 있음, 누르면 펼쳐짐), 실제 비용 한 줄.

- 허락받은 블로그(`config.toml`의 `[sources] allowed_blog_ids`) 주소만 쓸 수 있습니다. 다른 주소는 "허락된 블로그 주소만 사용할 수 있습니다"라고 표시됩니다.
- 원문 텍스트로 만들기는 화면에 없습니다. 명령어 `python run.py --text-file 파일.txt --yes`를 쓰세요.
- 한 번에 하나만 생성합니다. 페이지를 닫아도 생성은 계속됩니다. 결과는 `outputs/`에 남습니다.
- 이 컴퓨터에서만 접속됩니다 (`.streamlit/config.toml`: 주소 127.0.0.1, 사용 통계 전송 끔).

## 주요 설정 (`config.toml`)

| 항목 | 기본값 | 설명 |
|---|---|---|
| `[project] prompt_version` | `v2` | 프롬프트 폴더 (`prompts/v2/`) |
| `[project] style_preset` | `whiteboard_v2` | 그림체 문장 (`presets/whiteboard_v2.toml`) |
| `[project] cta_mode` | `outro` | 원문의 홍보 내용 처리: `outro`(결론에서 소개) / `none`(빼기) / `full` |
| `[script] target_duration_sec` | `45` | 목표 영상 길이(초) |
| `[script] scene_count` | `6` | 기본 장면 수 (허용 5~7개) |
| `[script] narration_chars_target` | `270` | 대본 글자 수 목표 (cedar 목소리 말하기 속도 실측 기준) |
| `[models] text` / `image` / `tts` | `gpt-6.1-sol` / `gpt-image-2.5-flare` / `gpt-4o-mini-tts` | 사용할 모델 |
| `[models] image_quality` | `medium` | 그림 품질 (`low` / `medium` / `high`, 높을수록 비쌈) |
| `[models] tts_voice` | `cedar` | 음성 목소리 |
| `[models] tts_instructions` | 친근하고 차분한 한국어 설명 톤 | 말투 지시 |
| `[video] draw_effect` | `whiteboard` | 드로잉 효과: `whiteboard`(손으로 그리기) / `wipe`(위→아래 드러나기) |
| `[whiteboard] min_hold_sec` | `2.0` | 다 그린 뒤 완성 그림을 보여주는 최소 시간 |
| `[layout]` | | 화면 배치 (그림 위치·크기, 자막 위치·글꼴·크기) |
| `[sources] allowed_blog_ids` | `copper567`, `allnewk724` | 주소로 자동 수집해도 되는 블로그 (허락받은 블로그만 추가) |
| `[prices]` | 2026-11-09 공식 가격 | 비용 계산용 단가. 가격이 바뀌면 고쳐야 합니다 |

## 비용과 시간 (실측)

MacBook(Apple Silicon)에서 블로그 글 20건(본문 약 1,500~2,300자)을 기본 설정으로 만든 결과입니다. 20건 모두 성공했습니다.

| 항목 | 1건 평균 | 범위 |
|---|---|---|
| 비용 | **약 $0.126** | $0.114 ~ $0.141 |
| 걸린 시간 | **약 2분 50초** (169초) | 2분 28초 ~ 3분 46초 |
| 영상 길이 | 45.8초 | 43.0 ~ 50.3초 |

- 비용 구성(1건): 글 3단계 약 $0.04~0.05 + 그림 6장 약 $0.068 (장당 약 $0.011) + 음성 약 $0.011
- 글·그림 비용은 API 응답의 실제 사용량으로 계산합니다. 음성은 응답에 사용량이 없어 추정값입니다 (1초 = 20토큰 가정).
- 가장 오래 걸리는 단계는 그림 생성(S5)과 장면 영상 만들기(S8)입니다.

## 한계점

- **사용 중인 TTS 모델(`gpt-4o-mini-tts`)은 2027-01-06 종료 예정입니다.** 이후에는 다른 음성 모델로 바꿔야 합니다. 음성 부분은 `pipeline/tts_engines.py`에 모여 있어 그 파일만 고치면 됩니다.
- **블로그 주소 자동 수집은 허락받은 블로그로만 제한**됩니다. 네이버 블로그는 이용 규칙(robots.txt)에서 AI 목적의 자동 수집을 금지하고 있습니다. 허락을 받은 블로그는 `config.toml`에 추가하면 됩니다. 그 밖의 글은 원문을 붙여넣어야 합니다.
- 블로그의 새 글 목록을 프로그램이 스스로 찾지 않습니다 (글 목록·RSS도 자동 접속 금지). 글 주소는 사람이 넣어야 합니다.
- 드로잉 순서: 종이 위의 작은 그림이 종이 테두리보다 먼저 나타나거나, 캐릭터의 얼굴(눈·입)이 몸보다 나중에 그려지는 경우가 있습니다.
- 그림이 단순해서 장면끼리 비슷해 보일 때가 있습니다 ("책상에서 책을 보는 사람" 장면이 반복되는 경우).
- 쉼표 없이 긴 문장은 자막에서 끝말이 다음 자막으로 넘어갈 수 있습니다.
- AI 생성 결과는 실행할 때마다 조금씩 달라집니다. 대본은 원문에 없는 사실을 만들지 않도록 지시하고 숫자를 원문과 대조하지만, 공개 전에 사람이 확인하는 것을 권합니다.
- macOS 기준으로 만들었습니다 (자막 글꼴 경로).

## 외부 라이브러리

- [whiteboard-animator](https://github.com/masihsultani/whiteboard-animator) 0.1.1 (MIT License, Copyright (c) 2026 Masih Sultani): 선화를 그리는 순서와 시간 계산에 사용합니다. 여기에 포함된 CRAFT 글자 감지 모델은 [CRAFT-pytorch](https://github.com/clovaai/CRAFT-pytorch) (MIT License, NAVER Corp.)에서 왔습니다.
- 라이선스 원문: [NOTICE.md](NOTICE.md)
- 그 밖의 라이브러리와 버전: [requirements.txt](requirements.txt)

## 폴더 구조

```
run.py                    실행 시작점 (명령어)
config.toml               모든 설정
pipeline/                 S1~S9 단계별 코드
  draw_whiteboard.py      손으로 그리는 효과 (whiteboard-animator 사용)
  tts_engines.py          음성 엔진 (모델 교체는 여기서)
prompts/v2/               AI에게 주는 지시문 (요약·대본·그림 묘사)
presets/whiteboard_v2.toml  공통 그림체 문장
demo/                     데모 페이지 (Streamlit)
examples/sample_post.txt  예시 글
```
