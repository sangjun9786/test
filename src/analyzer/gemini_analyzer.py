import json
import logging
from typing import List, Dict, Any, Optional
from google import genai
from ..config import GEMINI_MODEL, DEFAULT_GEMINI_MODELS

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """너는 데이터와 통계 기반의 전문 스포츠 분석가이자 데일리 스포츠 브리핑 봇이다.
아래 제공되는 실제 당일 경기 및 선발투수 JSON 데이터를 엄밀하게 분석하여 디스코드에 공유할 고품질 데일리 프리뷰를 작성하라.

[엄격한 분석 및 생성 지침]
1. 절대적인 팩트 기반: 제공된 JSON 데이터에 기재된 선수명, 스탯(ERA, WHIP, W-L, 피홈런, 홈/원정 스플릿, 최근 5경기 게임로그 등)만 인용하라. 제공되지 않은 가상의 선수를 지어내거나 허위 정보를 창작하지 말 것(환각 방지).
2. 선발 투수 최근 5경기 흐름 & 홈/원정 스플릿 심층 분석:
   - 📊 최근 5경기 흐름(Game Logs): 선발투수의 최근 전체 5경기(`recent_5_overall`) 및 최근 조건별(`recent_5_split`: 원정 선발은 원정 5경기, 홈 선발은 홈 5경기) 등판 성적을 분석하라.
   - 💣 피홈런(HR) & 실점 추이: 최근 등판에서 피홈런이 잦아졌는지, 실점이 급증했는지, 이닝 소화력이 5이닝 미만으로 떨어졌는지를 면밀히 파악하라.
   - 🏟️ 홈/원정 편차(Home/Away Splits): 구장 상성과 홈/원정 등판 시의 ERA 및 피홈런 편차를 5이닝 및 풀이닝 승패/언오버 판단의 핵심 근거로 삼으라.
3. 선발투수 최근 5경기 세부 성적 마크다운 표(Table) 작성:
   - 단순 스탯 나열을 지양하고, 각 선발투수의 **최근 전체 5경기**와 **최근 조건별(홈/원정) 5경기**를 컴팩트한 마크다운 표로 시각화하라. (스탯이 없는 미정 투수는 '데이터 없음'으로 간략히 표기)
4. 예측 지표 도출:
   - 5이닝(F5) 승리 예상 및 언더/오버 (선발투수 초반 5이닝 매치업 집중)
   - 풀이닝 종합 승리 예상 팀 및 총 득점 기준 언더/오버 추천 (기준점 예: 7.5, 8.5 등)
   - 신뢰도 (★ 1~5개)
   - 2~3줄의 핵심 분석 근거 (최근 5경기 피홈런 및 구위 흐름 포함)
5. 디스코드 출력 양식: 가독성 높게 마크다운 문법(표, 굵은 글씨, 이모지, 불렛 포인트)을 적극 활용할 것.
"""

class GeminiSportsAnalyzer:
    """
    Google Gemini API를 활용한 스포츠 데이터 추론 및 리포트 생성기
    """
    def __init__(self, api_key: str, candidate_models: Optional[List[str]] = None):
        if not api_key:
            raise ValueError("GEMINI_API_KEY가 제공되지 않았습니다.")
        self.api_key = api_key
        self.candidate_models = candidate_models or DEFAULT_GEMINI_MODELS
        self.client = genai.Client(api_key=self.api_key)

    def analyze_games(
        self,
        league: str,
        games_data: List[Dict[str, Any]],
        recent_stats: Optional[Dict[str, Any]] = None
    ) -> tuple[str, List[Dict[str, Any]]]:
        """
        수집된 경기 JSON 데이터를 바탕으로 Gemini 분석 리포트(마크다운) 및 DB 저장용 구조화 데이터 생성
        :return: (discord_markdown_report, structured_predictions_list)
        """
        if not games_data:
            return f"📊 **[{league}] 오늘 예정된 경기 데이터가 없습니다.**", []

        games_json_str = json.dumps(games_data, indent=2, ensure_ascii=False)

        # 과거 통계 및 자가교정 피드백 문구 구성 (고도화 Step 4)
        feedback_text = ""
        if recent_stats and recent_stats.get("has_data"):
            summary_insights = recent_stats.get("summary_text", "")
            feedback_text = f"""
[최근 모델 실전 적중률 및 자가교정(Self-Correction) 피드백]
{summary_insights}

[자가교정 분석 지침]
1. ⚠️ 불펜 리스크 반영: 선발 투수의 우위는 확실하나 뒷문(불펜)이 불안정한 팀의 경우, 풀이닝 승리보다 '5이닝(F5) 승리'를 1순위 추천 픽으로 적극 채택하라.
2. ⚠️ 언더/오버 편향 보정: 과거 오버/언더 오차 경향에 따라 오늘 기준점(Total Line) 설정을 보수적으로 재조정하라.
3. ⚠️ 고신뢰도(★ 4~5개) 엄격화: 선발 지표(ERA, WHIP, 피안타율, K/9 등)에서 압도적인 차이가 있고 타선 지원이 뒷받침될 때만 신뢰도 별 4개 이상을 부여하라.
"""

        user_prompt = f"""[분석 대상 리그: {league}]
{feedback_text}
오늘 분석할 경기 데이터 목록(JSON):
```json
{games_json_str}
```

위 데이터를 분석하여 다음 양식으로 작성해줘. 특히 **선발투수의 최근 전체 5경기 및 홈/원정 5경기 세부 성적 표(Table)**, **5이닝(F5) 선발 매치업**과 **풀이닝 종합 분석**을 명확히 구분하여 예측할 것:

# ⚾ [{league} 데일리 매치업 & 추천 픽] ({games_data[0].get('date', '오늘')})

각 경기마다:
### 📌 [경기시간 KST] 원정팀 vs 홈팀 (구장)
- **선발 매치업 요약**:
  • ✈️ 원정 선발: [투수명] (시즌 X승 Y패 ERA A.BB, 피홈런 N개 | 🏟️ 원정 등판 ERA C.DD, 피홈런 M개)
  • 🏠 홈 선발: [투수명] (시즌 X승 Y패 ERA A.BB, 피홈런 N개 | 🏟️ 홈 등판 ERA C.DD, 피홈런 M개)

📊 **[원정 선발: 투수명] 최근 등판 성적표**
• 최근 전체 5경기:
| 일자 | 상대 | 구장 | IP | ER | HR | K/BB |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| 09-14 | CIN | 원정 | 7.0 | 0 | 0 | 9/2 |
(최근 전체 5경기 표 작성)
• 최근 원정 5경기:
| 일자 | 상대 | IP | ER | HR | K/BB |
| :---: | :---: | :---: | :---: | :---: | :---: |
| 09-14 | CIN | 7.0 | 0 | 0 | 9/2 |
(최근 원정 5경기 표 작성. 데이터가 5경기 미만이면 있는 만큼 작성)

📊 **[홈 선발: 투수명] 최근 등판 성적표**
• 최근 전체 5경기:
| 일자 | 상대 | 구장 | IP | ER | HR | K/BB |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: |
(최근 전체 5경기 표 작성)
• 최근 홈 5경기:
| 일자 | 상대 | IP | ER | HR | K/BB |
| :---: | :---: | :---: | :---: | :---: | :---: |
(최근 홈 5경기 표 작성. 데이터가 5경기 미만이면 있는 만큼 작성)
*(선발 투수 데이터가 없는 미정/신인 선수는 표 대신 '최근 등판 데이터 없음'으로 간략히 표기)*

- **⚡ 5이닝(F5) 예측**: 
  • 5이닝 승리 예상: [원정팀 / 홈팀 / 5이닝 무승부] (예상 스코어 X:Y)
  • 5이닝 언/오버: [오버 또는 언더 (기준점 4.5 등)]
- **🏁 풀이닝 종합 예측**:
  • 승리팀 예상: [원정팀 또는 홈팀] (예상 최종 스코어 X:Y)
  • 풀이닝 언/오버: [오버 또는 언더 (기준점 8.5 등)]
- **신뢰도**: ★★★★☆
- **핵심 분석 요약**: (최근 5경기 피홈런/실점 추세, 홈/원정 기복, 5이닝 승부처 2~3줄 요약)

---
마지막에:
### 🏆 오늘의 최고 추천 픽 (TOP 2 Pick)
1. ...
2. ...

---
[중요: 시스템 저장용 JSON]
본문 맨 마지막에 아래 규격의 JSON 블록을 반드시 포함할 것 (코드블록 이름: ```json:predictions):
```json:predictions
[
  {{
    "away_team": "원정팀명",
    "home_team": "홈팀명",
    "away_pitcher": "원정선발",
    "home_pitcher": "홈선발",
    "pred_winner": "풀이닝 승리팀",
    "pred_away_score": 5,
    "pred_home_score": 3,
    "pred_ou_pick": "언더",
    "pred_ou_line": 8.5,
    "pred_f5_winner": "5이닝 승리팀 또는 무승부",
    "pred_f5_away_score": 2,
    "pred_f5_home_score": 1,
    "pred_f5_ou_pick": "언더",
    "pred_f5_ou_line": 4.5,
    "confidence_stars": 4,
    "is_top_pick": true,
    "analysis_summary": "핵심 분석 한 줄"
  }}
]
```
"""
        combined_prompt = f"{SYSTEM_PROMPT}\n\n{user_prompt}"

        raw_report = ""
        last_err = None
        for model in self.candidate_models:
            logger.info(f"{league} 분석 시도 중 (모델: {model})...")
            
            # 1. interactions API 시도
            try:
                interaction = self.client.interactions.create(
                    model=model,
                    input=combined_prompt
                )
                if interaction and interaction.output_text:
                    raw_report = interaction.output_text.strip()
                    logger.info(f"Gemini interactions API ({model}) 분석 완료")
                    break
            except Exception as e:
                err_str = str(e)
                logger.warning(f"interactions API ({model}) 실패: {e}")
                last_err = e
                # 429(할당량 초과)나 404(모델 없음)는 같은 모델의 generate_content를 또 호출할 필요 없이 즉시 다음 모델로
                if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str or "404" in err_str or "NOT_FOUND" in err_str:
                    continue

            # 2. generate_content fallback 시도
            try:
                resp = self.client.models.generate_content(
                    model=model,
                    contents=combined_prompt
                )
                if resp and resp.text:
                    raw_report = resp.text.strip()
                    logger.info(f"Gemini generate_content ({model}) 분석 완료")
                    break
            except Exception as e:
                logger.warning(f"generate_content ({model}) 실패: {e}")
                last_err = e

        if not raw_report:
            raise RuntimeError(f"Gemini 모든 모델 호출 실패: {last_err}")

        # JSON 블록 파싱 및 분리
        structured_preds = []
        discord_markdown = raw_report

        if "```json:predictions" in raw_report:
            parts = raw_report.split("```json:predictions")
            discord_markdown = parts[0].strip()
            json_part = parts[1].split("```")[0].strip()
            try:
                structured_preds = json.loads(json_part)
            except Exception as e:
                logger.warning(f"예측 JSON 파싱 오류: {e}")
        elif "```json" in raw_report:
            # fallback
            parts = raw_report.split("```json")
            discord_markdown = parts[0].strip()
            json_part = parts[-1].split("```")[0].strip()
            try:
                data = json.loads(json_part)
                if isinstance(data, list):
                    structured_preds = data
            except Exception:
                pass

        return discord_markdown, structured_preds
