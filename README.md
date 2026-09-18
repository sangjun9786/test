# ⚾ 스포츠 자동 분석 & 디스코드 데일리 브리핑 (MLB & KBO)

매일 지정된 시간에 공식 무료 스포츠 API(MLB Stats API, KBO 데이터)를 통해 당일 매치업과 선발 투수 지표를 실시간 수집하고, **Google Gemini 3.8 Flash**를 활용해 객관적인 승패 및 언더/오버 리포트를 생성하여 **디스코드 채널로 자동 발송**하는 무과금(서버 비용 0원) 자동화 파이프라인입니다.

---

## 🌟 주요 특징 및 아키텍처

```
[GitHub Actions Cron 트리거] 
       ↓ (06:30 KST - MLB / 15:30 KST - KBO)
[데이터 수집 (Data Ingestion)]
   - MLB: 공식 무료 Stats API (선발 ERA, WHIP, W-L, 탈삼진/볼넷 비율)
   - KBO: 당일 매치업, 선발(예고) 투수, 시즌 전적(승-패-무)
       ↓
[LLM 통계 분석 (Gemini 3.8 Flash)]
   - 엄격한 팩트 기반 추론 (할루시네이션 방지 프롬프트 적용)
   - 선발 매치업 우열 비교, 예상 스코어, 승리팀 예측, 언/오버 기준점, 신뢰도(★)
       ↓
[디스코드 리치 임베드 발송 (Discord Webhook)]
   - 리그별 컬러 카드(MLB Blue, KBO Orange)로 가독성 높게 즉시 전송
```

- **완전 무료(0원)**: 24시간 켜두는 서버 없이 GitHub Actions의 무료 가상머신에서 지정 시간에만 실행되고 종료됩니다.
- **키 발급 최소화**: MLB는 공식 오픈 API를 사용하여 스포츠 데이터용 유료 구독이 필요 없습니다.

---

## 🔑 1. 사전 준비 (2가지 키 발급)

### (1) 디스코드 웹훅 URL 생성 (약 1분 소요)
1. 알림을 받고 싶은 디스코드 서버의 채널 이름 옆 **톱니바퀴 아이콘(채널 편집)** 클릭
2. 좌측 메뉴에서 **[연동(Integrations)]** → **[웹훅(Webhooks)]** 클릭
3. **[새 웹훅 만들기]** 버튼 클릭
4. 웹훅 이름(예: `스포츠 브리핑 봇`) 설정 후 **[웹훅 URL 복사]** 클릭
   - 형태: `https://discord.com/api/webhooks/123456789/...`

### (2) Google Gemini API 키 발급 (무료, 약 1분 소요)
1. [Google AI Studio](https://aistudio.google.com/) 접속 및 구글 계정 로그인
2. **[Get API key]** 클릭 후 새 API 키 생성
3. 생성된 키(`AIzaSy...`) 복사

---

## 💻 2. 로컬(내 컴퓨터)에서 테스트 실행하기

### 1) 의존성 패키지 설치
```bash
# Windows
py -m pip install -r requirements.txt

# Mac/Linux
pip install -r requirements.txt
```

### 2) 환경변수 설정
프로젝트 루트의 `.env.example`을 복사하여 `.env` 파일을 만듭니다:
```ini
GEMINI_API_KEY=발급받은_Gemini_API_키
DISCORD_WEBHOOK_URL=복사한_디스코드_웹훅_URL
```

### 3) 로컬 실행 명령어
```bash
# 1. 터미널 출력만 확인 (디스코드로 전송하지 않음 - 추천)
py -m src.main --dry-run

# 2. MLB 경기만 분석하여 디스코드로 실제 전송
py -m src.main --sport mlb

# 3. KBO 경기만 분석하여 디스코드로 실제 전송
py -m src.main --sport kbo

# 4. 전체(MLB + KBO) 모두 분석 및 전송
py -m src.main --sport all
```

---

## 🚀 3. GitHub에 올리고 자동화 배포하기 (A to Z)

### Step 1: 깃허브(GitHub) 새 저장소 생성
1. [GitHub](https://github.com/) 로그인 후 우측 상단 `+` 버튼 → **[New repository]** 클릭
2. Repository name 입력 (예: `sports-auto-analyst`)
3. Public 또는 Private 선택 후 **[Create repository]** 클릭

### Step 2: 로컬 코드를 GitHub에 푸시(Push)
내 컴퓨터 터미널(`c:\workspace\SStest`)에서 아래 명령어를 순서대로 실행합니다:

```bash
git init
git add .
git commit -m "feat: initial commit for sports auto briefing bot"
git branch -M main

# 본인의 깃허브 저장소 주소로 연결
git remote add origin https://github.com/당신의깃허브계정/sports-auto-analyst.git

# 깃허브로 업로드
git push -u origin main
```

### Step 3: GitHub Secrets(보안 키) 등록
1. 생성된 GitHub 저장소 페이지의 상단 메뉴에서 **[Settings]** 클릭
2. 좌측 메뉴에서 **[Secrets and variables]** → **[Actions]** 클릭
3. **[New repository secret]** 녹색 버튼을 누르고 아래 2개를 각각 등록합니다:

| Name (이름) | Secret (값) | 설명 |
|---|---|---|
| `GEMINI_API_KEY` | `AIzaSy...` | 구글 Gemini API 키 |
| `DISCORD_WEBHOOK_URL` | `https://discord.com/api/webhooks/...` | 디스코드 웹훅 URL |

### Step 4: 동작 테스트 (수동 즉시 실행)
1. GitHub 저장소 상단의 **[Actions]** 탭 클릭
2. 좌측 워크플로우 목록에서 **[Daily Sports Analysis Briefing]** 클릭
3. 우측에 나타나는 **[Run workflow]** 버튼 클릭 → `all` 선택 후 실행
4. 잠시 후 디스코드 채널로 실시간 분석 브리핑 카드가 도착하는 것을 확인합니다!

---

## ⏰ 4. 자동 발송 시간표 (KST 기준)

기본 설정된 발송 시간은 다음과 같으며, `.github/workflows/daily_report.yml`에서 원하시는 시간으로 언제든 변경하실 수 있습니다.

| 대상 종목 | 실행 시각 (KST) | Cron (UTC) | 설명 |
|---|---|---|---|
| **MLB** | 매일 오전 06:30 | `30 21 * * *` | 오전 7시~11시 경기 전 선발 매치업 리포트 |
| **KBO** | 매일 오후 15:30 | `30 6 * * *` | 18:30 야간 경기 시작 3시간 전 선발 예고 브리핑 |

> **Cron 시간 변경 팁**:
> GitHub Actions는 UTC 시간을 사용합니다. `KST 시간 - 9시간 = UTC 시간`으로 계산하여 설정하시면 됩니다.
> 예: 오후 5시(17:00 KST)에 실행하고 싶다면 → `17 - 9 = 08` → `0 8 * * *`

---

## 📁 프로젝트 파일 구성

```
├── .github/
│   └── workflows/
│       └── daily_report.yml       # 매일 지정 시각 자동 실행 GitHub Actions 정의
├── src/
│   ├── config.py                  # 환경변수 검증 및 설정 로드
│   ├── collectors/
│   │   ├── mlb_collector.py       # MLB Stats 공식 API (선발 지표 실시간 수집)
│   │   └── kbo_collector.py       # KBO 경기 일정 및 선발투수 실시간 수집
│   ├── analyzer/
│   │   └── gemini_analyzer.py     # Gemini 3.8 Flash 팩트 기반 추론 및 포맷팅
│   ├── notifier/
│   │   └── discord_notifier.py    # 디스코드 웹훅 리치 임베드 전송 (자동 분할)
│   └── main.py                    # 파이프라인 통합 실행기 (CLI 지원)
├── requirements.txt               # 의존 라이브러리 목록
├── .env.example                   # 로컬 환경변수 템플릿
└── .gitignore                     # Git 업로드 제외 파일 목록
```
