import json
import logging
from typing import List, Dict, Any, Optional
from google import genai
from ..config import GEMINI_MODEL

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """너는 데이터와 통계 기반의 전문 스포츠 분석가이자 데일리 스포츠 브리핑 봇이다.
아래 제공되는 실제 당일 경기 및 선발투수 JSON 데이터를 엄밀하게 분석하여 디스코드에 공유할 고품질 데일리 프리뷰를 작성하라.

[엄격한 분석 및 생성 지침]
1. 절대적인 팩트 기반: 제공된 JSON 데이터에 기재된 선수명, 스탯(ERA, WHIP, W-L 등), 팀 성적만 인용하라. 제공되지 않은 가상의 선수를 지어내거나 허위 정보를 창작하지 말 것(환각 방지).
2. 선발 투수 매치업 분석: 선발투수 스탯(평균자책점, WHIP, 삼진/볼넷 비율 등)을 비교하여 선발 우위를 판별하라. (투수가 미정인 경우 불펜 데이 또는 팀 최근 승률 기반으로 평가할 것)
3. 예측 지표 도출:
   - 승리 예상 팀 (홈/원정 중 우세 팀 및 승리 확률 백분율)
   - 예상 스코어 및 총 득점 기준 언더/오버 추천 (기준점 예: 7.5, 8.5 등)
   - 신뢰도 (★ 1~5개)
   - 2~3줄의 핵심 분석 근거
4. 디스코드 출력 양식: 가독성 높게 마크다운 문법(굵은 글씨, 이모지, 불렛 포인트)을 적극 활용할 것.
"""

class GeminiSportsAnalyzer:
    """
    Google Gemini API를 활용한 스포츠 데이터 추론 및 리포트 생성기
    """
    def __init__(self, api_key: str, model_name: str = GEMINI_MODEL):
        if not api_key:
            raise ValueError("GEMINI_API_KEY가 제공되지 않았습니다.")
        self.api_key = api_key
        self.model_name = model_name
        self.client = genai.Client(api_key=self.api_key)

    def analyze_games(self, league: str, games_data: List[Dict[str, Any]]) -> str:
        """
        수집된 경기 JSON 데이터를 바탕으로 Gemini 분석 리포트 생성
        """
        if not games_data:
            return f"📊 **[{league}] 오늘 예정된 경기 데이터가 없습니다.**"

        # 입력 데이터 준비
        games_json_str = json.dumps(games_data, indent=2, ensure_ascii=False)

        user_prompt = f"""[분석 대상 리그: {league}]
오늘 분석할 경기 데이터 목록(JSON):
```json
{games_json_str}
```

위 데이터를 꼼꼼히 확인하고 다음 양식으로 디스코드 브리핑 리포트를 작성해줘:

# ⚾ [{league} 데일리 매치업 & 추천 픽] ({games_data[0].get('date', '오늘')})

각 경기마다:
### 📌 [경기시간 KST] 원정팀 vs 홈팀
- **선발 매치업**: 원정 선발 vs 홈 선발 (핵심 지표 비교)
- **예상 스코어**: 원정 X : 홈 Y
- **추천 픽**: 승리팀 예상 / [오버 또는 언더 (기준점)]
- **신뢰도**: ★★★☆☆
- **핵심 분석 요약**: (2~3줄 요약)

---
마지막에:
### 🏆 오늘의 최고 추천 픽 (TOP 2 Pick)
1. ...
2. ...
"""

        logger.info(f"{league} {len(games_data)}개 경기 Gemini 분석 요청 중 (모델: {self.model_name})...")
        
        try:
            # 1순위: interactions API
            interaction = self.client.interactions.create(
                model=self.model_name,
                input=f"{SYSTEM_PROMPT}\n\n{user_prompt}"
            )
            report = interaction.output_text or ""
            logger.info(f"{league} 분석 완료 (글자수: {len(report)})")
            return report.strip()
        except Exception as e:
            logger.warning(f"interactions API 호출 실패 ({e}), generate_content로 대체 시도...")
            try:
                # 2순위: models.generate_content API
                resp = self.client.models.generate_content(
                    model=self.model_name,
                    contents=f"{SYSTEM_PROMPT}\n\n{user_prompt}"
                )
                return (resp.text or "").strip()
            except Exception as e2:
                logger.error(f"Gemini API 호출 완전 실패: {e2}")
                raise RuntimeError(f"Gemini 분석 생성 실패: {e2}") from e2
