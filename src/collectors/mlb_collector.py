import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional
import requests

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))

class MLBCollector:
    """
    공식 MLB Stats API (무료, 인증키 불필요)를 통한 당일 경기 및 선발투수 스플릿 수집기
    """
    BASE_URL = "https://statsapi.mlb.com/api/v1"

    def __init__(self, timeout: int = 15):
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) SportsAutoAnalyst/1.0"
        })

    def fetch_pitcher_stats(self, person_id: int) -> Dict[str, Any]:
        """
        선발 투수 시즌 지표(ERA, WHIP, W-L, K/9, BB/9 등) 조회
        """
        if not person_id:
            return {}

        url = f"{self.BASE_URL}/people/{person_id}/stats?stats=season&group=pitching"
        try:
            resp = self.session.get(url, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
            stats_list = data.get("stats", [])
            if not stats_list:
                return {}
            splits = stats_list[0].get("splits", [])
            if not splits:
                return {}

            stat = splits[0].get("stat", {})
            return {
                "era": stat.get("era", "N/A"),
                "whip": stat.get("whip", "N/A"),
                "wins": stat.get("wins", 0),
                "losses": stat.get("losses", 0),
                "inningsPitched": stat.get("inningsPitched", "0.0"),
                "k9": stat.get("strikeoutsPer9Inn", "N/A"),
                "bb9": stat.get("walksPer9Inn", "N/A"),
                "avgAgainst": stat.get("avg", "N/A"),
                "hr9": stat.get("homeRunsPer9", "N/A"),
            }
        except Exception as e:
            logger.warning(f"선발투수(ID: {person_id}) 스탯 조회 실패: {e}")
            return {}

    def fetch_schedule(self, target_date: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        지정 날짜의 MLB 전체 경기 일정, 선발투수 정보 수집 (날짜 기본값: 오늘 KST 기준)
        :param target_date: 'YYYY-MM-DD' 형식 (없으면 오늘 KST)
        """
        if not target_date:
            target_date = datetime.now(KST).strftime("%Y-%m-%d")

        url = f"{self.BASE_URL}/schedule"
        params = {
            "sportId": 1,
            "date": target_date,
            "hydrate": "probablePitcher,team,linescore,venue"
        }

        logger.info(f"MLB 경기 데이터 수집 중: {target_date}...")
        try:
            resp = self.session.get(url, params=params, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.error(f"MLB 스케줄 조회 오류: {e}")
            return []

        dates = data.get("dates", [])
        if not dates:
            logger.info(f"{target_date}에 예정된 MLB 경기가 없습니다.")
            return []

        games_raw = dates[0].get("games", [])
        processed_games = []

        for g in games_raw:
            status = g.get("status", {}).get("detailedState", "Unknown")
            game_time_utc_str = g.get("gameDate")

            # UTC 시간을 한국 시간(KST)으로 변환
            kst_time_str = "시간 미정"
            if game_time_utc_str:
                try:
                    utc_dt = datetime.strptime(game_time_utc_str, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                    kst_dt = utc_dt.astimezone(KST)
                    kst_time_str = kst_dt.strftime("%H:%M")
                except Exception:
                    kst_time_str = game_time_utc_str

            teams = g.get("teams", {})
            away = teams.get("away", {})
            home = teams.get("home", {})

            away_team_name = away.get("team", {}).get("name", "Away")
            home_team_name = home.get("team", {}).get("name", "Home")

            away_record = away.get("leagueRecord", {})
            home_record = home.get("leagueRecord", {})

            away_pitcher_raw = away.get("probablePitcher", {})
            home_pitcher_raw = home.get("probablePitcher", {})

            away_pitcher_id = away_pitcher_raw.get("id")
            home_pitcher_id = home_pitcher_raw.get("id")

            # 선발 투수 스탯 수집
            away_pitcher_stats = self.fetch_pitcher_stats(away_pitcher_id) if away_pitcher_id else {}
            home_pitcher_stats = self.fetch_pitcher_stats(home_pitcher_id) if home_pitcher_id else {}

            venue_name = g.get("venue", {}).get("name", "구장 정보 없음")

            processed_games.append({
                "league": "MLB",
                "game_id": g.get("gamePk"),
                "date": target_date,
                "start_time_kst": kst_time_str,
                "status": status,
                "venue": venue_name,
                "away_team": {
                    "name": away_team_name,
                    "record": f"{away_record.get('wins', 0)}승 {away_record.get('losses', 0)}패 (승률 {away_record.get('pct', '.000')})",
                    "pitcher": {
                        "name": away_pitcher_raw.get("fullName", "미정"),
                        **away_pitcher_stats
                    }
                },
                "home_team": {
                    "name": home_team_name,
                    "record": f"{home_record.get('wins', 0)}승 {home_record.get('losses', 0)}패 (승률 {home_record.get('pct', '.000')})",
                    "pitcher": {
                        "name": home_pitcher_raw.get("fullName", "미정"),
                        **home_pitcher_stats
                    }
                }
            })

        logger.info(f"MLB {len(processed_games)}개 경기 데이터 수집 완료")
        return processed_games


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    collector = MLBCollector()
    games = collector.fetch_schedule()
    print(json.dumps(games[:1], indent=2, ensure_ascii=False))
