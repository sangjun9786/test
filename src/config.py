import os
from pathlib import Path
from dotenv import load_dotenv

# .env 파일 로드 (프로젝트 루트 기준)
BASE_DIR = Path(__file__).resolve().parent.parent
env_path = BASE_DIR / ".env"
if env_path.exists():
    load_dotenv(dotenv_path=env_path)
else:
    load_dotenv()

# 환경변수 로드
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "").strip()

# Gemini 지원 모델 목록 (우선순위 순서대로 시도)
DEFAULT_GEMINI_MODELS = [
    "gemini-3.8-flash",
    "gemini-2.5-flash",
    "gemini-2.0-flash"
]
GEMINI_MODEL = DEFAULT_GEMINI_MODELS[0]

def validate_config(require_webhook: bool = True):
    """
    필수 설정값 유효성 검사
    """
    missing = []
    if not GEMINI_API_KEY:
        missing.append("GEMINI_API_KEY (Google Gemini API 키)")
    if require_webhook and not DISCORD_WEBHOOK_URL:
        missing.append("DISCORD_WEBHOOK_URL (디스코드 채널 웹훅 URL)")

    if missing:
        msg = (
            "[설정 오류] 다음 환경변수가 설정되지 않았습니다:\n"
            + "\n".join(f"  - {item}" for item in missing)
            + "\n\n로컬 테스트 시 .env 파일에 값을 입력하거나,\n"
            + "GitHub Actions 배포 시 Repository Secrets에 등록해 주세요."
        )
        raise ValueError(msg)
