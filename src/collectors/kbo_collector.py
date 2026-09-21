import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional
import requests

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))

class KBOCollector:
    """
    국내 야구(KBO) 당일 경기 일정, 선발 투수(예고 투수), 팀 성적 실시간 수집기
    """
    DAUM_SCHEDULE_URL = "https://sports.daum.net/prx/hermes/api/game/schedule.json"

    def __init__(self, timeout: int = 15):
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Referer": "https://sports.daum.net/schedule/kbo"
        })

    def fetch_schedule(self, target_date: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        지정 날짜의 KBO 전체 경기 일정, 선발투수 정보 수집 (기본값: 오늘 KST)
        :param target_date: 'YYYY-MM-DD' 또는 'YYYYMMDD'
        """
        if not target_date:
            now_kst = datetime.now(KST)
            date_key = now_kst.strftime("%Y%m%d")
            display_date = now_kst.strftime("%Y-%m-%d")
        else:
            date_key = target_date.replace("-", "")
            display_date = f"{date_key[:4]}-{date_key[4:6]}-{date_key[6:8]}" if len(date_key) == 8 else target_date

        params = {
            "page": 1,
            "leagueCode": "kbo",
            "fromDate": date_key,
            "toDate": date_key
        }

        logger.info(f"KBO 경기 데이터 수집 중: {display_date}...")
        try:
            resp = self.session.get(self.DAUM_SCHEDULE_URL, params=params, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.error(f"KBO 스케줄 API 조회 실패: {e}")
            return []

        schedule_dict = data.get("schedule", {})
        games_raw = schedule_dict.get(date_key, [])

        if not games_raw:
            logger.info(f"{display_date}에 예정된 KBO 경기가 없습니다 (우천 취소 또는 경기 없는 날).")
            return []

        processed_games = []
        for g in games_raw:
            raw_time = g.get("startTime", "")
            if len(raw_time) == 4:
                formatted_time = f"{raw_time[:2]}:{raw_time[2:]}"
            else:
                formatted_time = raw_time or "시간 미정"

            status = g.get("gameStatus", "BEFORE")
            # 취소 경기 체크
            if status in ["CANCEL", "POSTPONED"]:
                status_desc = "취소/연기"
            elif status == "ING":
                status_desc = "경기 진행 중"
            elif status == "END":
                status_desc = "경기 종료"
            else:
                status_desc = "경기 시작 전"

            away_team = g.get("awayTeamName", "원정팀")
            home_team = g.get("homeTeamName", "홈팀")

            away_pitcher = g.get("awayStartPitcher") or "선발 예고 전"
            home_pitcher = g.get("homeStartPitcher") or "선발 예고 전"

            away_wlt = g.get("awayWlt")
            home_wlt = g.get("homeWlt")

            away_record_str = away_wlt if away_wlt else "KBO 정규시즌"
            home_record_str = home_wlt if home_wlt else "KBO 정규시즌"

            venue = g.get("fieldName") or "홈 구장"

            processed_games.append({
                "league": "KBO",
                "game_id": g.get("gameId"),
                "date": display_date,
                "start_time_kst": formatted_time,
                "status": status_desc,
                "venue": venue,
                "away_team": {
                    "name": away_team,
                    "record": away_record_str,
                    "pitcher": {
                        "name": away_pitcher
                    }
                },
                "home_team": {
                    "name": home_team,
                    "record": home_record_str,
                    "pitcher": {
                        "name": home_pitcher
                    }
                }
            })

        logger.info(f"KBO {len(processed_games)}개 경기 데이터 수집 완료")
        return processed_games

    def fetch_results(self, target_date: str) -> List[Dict[str, Any]]:
        """
        특정 날짜의 KBO 최종 경기 결과 및 5이닝(F5) 스코어 수집
        :param target_date: 'YYYY-MM-DD' 또는 'YYYYMMDD'
        """
        date_key = target_date.replace("-", "")
        display_date = f"{date_key[:4]}-{date_key[4:6]}-{date_key[6:8]}" if len(date_key) == 8 else target_date

        params = {
            "page": 1,
            "leagueCode": "kbo",
            "fromDate": date_key,
            "toDate": date_key
        }

        logger.info(f"KBO 경기 결과 수집 중: {display_date}...")
        try:
            resp = self.session.get(self.DAUM_SCHEDULE_URL, params=params, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.error(f"KBO 결과 목록 조회 실패: {e}")
            return []

        games_raw = data.get("schedule", {}).get(date_key, [])
        results = []

        for g in games_raw:
            status = g.get("gameStatus")
            if status != "END":
                continue  # 종료된 경기만 처리

            game_id = g.get("gameId")
            away_team = g.get("awayTeamName", "원정")
            home_team = g.get("homeTeamName", "홈")

            # 상세 점수판(5이닝 데이터 포함) 조회
            f5_away = 0
            f5_home = 0
            away_score = int(g.get("awayResult", 0) or 0)
            home_score = int(g.get("homeResult", 0) or 0)

            try:
                detail_url = f"https://sports.daum.net/prx/hermes/api/game/get.json?gameId={game_id}"
                detail_resp = self.session.get(detail_url, timeout=self.timeout)
                if detail_resp.status_code == 200:
                    detail_data = detail_resp.json()
                    hs = detail_data.get("homeScore", {}) or {}
                    as_ = detail_data.get("awayScore", {}) or {}

                    h_innings = [int(x.strip()) for x in hs.get("inning", "").split(",") if x.strip().isdigit()]
                    a_innings = [int(x.strip()) for x in as_.get("inning", "").split(",") if x.strip().isdigit()]

                    f5_home = sum(h_innings[:5])
                    f5_away = sum(a_innings[:5])
            except Exception as e:
                logger.warning(f"KBO {game_id} 5이닝 상세 스코어 조회 실패 ({e}), 풀스코어로 대체")

            actual_winner = away_team if away_score > home_score else (home_team if home_score > away_score else "무승부")
            f5_winner = away_team if f5_away > f5_home else (home_team if f5_home > f5_away else "무승부")

            results.append({
                "league": "KBO",
                "game_id": game_id,
                "date": display_date,
                "away_team": away_team,
                "home_team": home_team,
                "status": "END",
                "actual_away_score": away_score,
                "actual_home_score": home_score,
                "actual_winner": actual_winner,
                "total_runs": away_score + home_score,
                "f5_away_score": f5_away,
                "f5_home_score": f5_home,
                "f5_winner": f5_winner,
                "f5_total_runs": f5_away + f5_home
            })

        logger.info(f"KBO {len(results)}개 완료 경기 결과(5이닝 포함) 수집 완료")
        return results


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    collector = KBOCollector()
    games = collector.fetch_schedule()
    print(json.dumps(games, indent=2, ensure_ascii=False))
