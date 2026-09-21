import logging
import time
from typing import Optional, List
import requests

logger = logging.getLogger(__name__)

class DiscordNotifier:
    """
    디스코드 웹훅(Discord Webhook)을 통한 리치 임베드 및 마크다운 메시지 발송 모듈
    """
    def __init__(self, webhook_url: str, timeout: int = 15):
        if not webhook_url:
            raise ValueError("DISCORD_WEBHOOK_URL이 제공되지 않았습니다.")
        self.webhook_url = webhook_url
        self.timeout = timeout

    def _split_text(self, text: str, max_chunk_size: int = 1900) -> List[str]:
        """
        메시지가 디스코드 글자 수 제한을 초과할 경우 줄바꿈 단위로 안전하게 분할
        """
        if len(text) <= max_chunk_size:
            return [text]

        chunks = []
        lines = text.split("\n")
        current_chunk = []
        current_length = 0

        for line in lines:
            line_len = len(line) + 1  # 줄바꿈 포함
            if current_length + line_len > max_chunk_size:
                if current_chunk:
                    chunks.append("\n".join(current_chunk))
                    current_chunk = []
                    current_length = 0
            current_chunk.append(line)
            current_length += line_len

        if current_chunk:
            chunks.append("\n".join(current_chunk))

        return chunks

    def send_message(self, text: str) -> bool:
        """
        일반 텍스트(마크다운) 메시지 전송 (자동 분할 지원)
        """
        chunks = self._split_text(text, max_chunk_size=1900)
        success = True

        for i, chunk in enumerate(chunks):
            payload = {
                "content": chunk,
            }
            if not self._post_webhook(payload):
                success = False
            if i < len(chunks) - 1:
                time.sleep(0.8)  # 연속 발송 시 디스코드 Rate Limit 방지

        return success

    def send_embed(
        self,
        title: str,
        description: str,
        color: int = 0x3498DB,
        footer_text: Optional[str] = "Sports Auto Briefing with Gemini",
    ) -> bool:
        """
        카드 형태의 리치 임베드(Embed) 전송
        - MLB 테마 색상: 0x005A9C (남색)
        - KBO 테마 색상: 0xFF6B00 (주황색)
        """
        # 임베드 설명란 최대 3900자로 분할
        desc_chunks = self._split_text(description, max_chunk_size=3900)
        success = True

        for i, chunk in enumerate(desc_chunks):
            sub_title = title if i == 0 else f"{title} (계속 {i+1})"
            payload = {
                "embeds": [
                    {
                        "title": sub_title,
                        "description": chunk,
                        "color": color,
                        "footer": {
                            "text": footer_text
                        },
                        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                    }
                ]
            }
            if not self._post_webhook(payload):
                success = False
            if i < len(desc_chunks) - 1:
                time.sleep(0.8)

        return success

    def _post_webhook(self, payload: dict) -> bool:
        """
        실제 웹훅 POST 요청 처리 및 재시도 로직
        """
        max_retries = 3
        for attempt in range(1, max_retries + 1):
            try:
                resp = requests.post(
                    self.webhook_url,
                    json=payload,
                    timeout=self.timeout
                )
                if resp.status_code in [200, 204]:
                    logger.info("디스코드 메시지 전송 성공")
                    return True
                elif resp.status_code == 429:
                    # Rate Limited
                    retry_after = resp.json().get("retry_after", 2.0)
                    logger.warning(f"디스코드 Rate Limit 도달, {retry_after}초 후 재시도...")
                    time.sleep(float(retry_after) + 0.5)
                else:
                    logger.error(f"디스코드 전송 실패 [HTTP {resp.status_code}]: {resp.text}")
                    return False
            except Exception as e:
                logger.error(f"디스코드 요청 중 오류 발생 (시도 {attempt}/{max_retries}): {e}")
                time.sleep(1)

        return False
