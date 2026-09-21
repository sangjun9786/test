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

    def fetch_pitcher_stats(self, person_id: int, is_home: Optional[bool] = None) -> Dict[str, Any]:
        """
        선발 투수 시즌 지표(ERA, WHIP, W-L, K/9, BB/9, 피홈런, HR/9) 및 홈/원정 스플릿 지표 조회
        :param person_id: 선수 고유 ID
        :param is_home: 홈 등판 여부 (True면 홈 스플릿, False면 원정 스플릿 추출)
        """
        if not person_id:
            return {}

        url = f"{self.BASE_URL}/people/{person_id}/stats?stats=season,homeAndAway&group=pitching"
        try:
            resp = self.session.get(url, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
            stats_list = data.get("stats", [])
            if not stats_list:
                return {}

            season_stat = {}
            split_stat = {}

            for s in stats_list:
                display_name = s.get("type", {}).get("displayName")
                splits = s.get("splits", [])
                if not splits:
                    continue

                if display_name == "season":
                    season_stat = splits[0].get("stat", {})
                elif display_name == "homeAndAway" and is_home is not None:
                    for sp in splits:
                        if sp.get("isHome") == is_home:
                            split_stat = sp.get("stat", {})
                            break

            result: Dict[str, Any] = {
                "era": season_stat.get("era", "N/A"),
                "whip": season_stat.get("whip", "N/A"),
                "wins": season_stat.get("wins", 0),
                "losses": season_stat.get("losses", 0),
                "inningsPitched": season_stat.get("inningsPitched", "0.0"),
                "k9": season_stat.get("strikeoutsPer9Inn", "N/A"),
                "bb9": season_stat.get("walksPer9Inn", "N/A"),
                "avgAgainst": season_stat.get("avg", "N/A"),
                "homeRuns": season_stat.get("homeRuns", 0),
                "hr9": season_stat.get("homeRunsPer9", "N/A"),
            }

            if split_stat:
                split_name = "홈(Home)" if is_home else "원정(Away)"
                result["split_stats"] = {
                    "split_type": split_name,
                    "era": split_stat.get("era", "N/A"),
                    "whip": split_stat.get("whip", "N/A"),
                    "wins": split_stat.get("wins", 0),
                    "losses": split_stat.get("losses", 0),
                    "inningsPitched": split_stat.get("inningsPitched", "0.0"),
                    "avgAgainst": split_stat.get("avg", "N/A"),
                    "homeRuns": split_stat.get("homeRuns", 0),
                    "hr9": split_stat.get("homeRunsPer9", "N/A"),
                    "k9": split_stat.get("strikeoutsPer9Inn", "N/A"),
                    "bb9": split_stat.get("walksPer9Inn", "N/A")
                }

            return result
        except Exception as e:
            logger.warning(f"선발투수(ID: {person_id}) 스탯 조회 실패: {e}")
            return {}

    def fetch_pitcher_game_logs(self, person_id: int, is_home: bool) -> Dict[str, Any]:
        """
        선발 투수 최근 전체 5경기 및 최근 조건별(홈 선발이면 홈 5경기, 원정 선발이면 원정 5경기) 등판 기록 조회
        """
        if not person_id:
            return {}

        url = f"{self.BASE_URL}/people/{person_id}/stats?stats=gameLog&group=pitching"
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

            def format_log(s):
                st = s.get("stat", {})
                opp = s.get("opponent", {}).get("name", "상대팀")
                venue_type = "홈" if s.get("isHome") else "원정"
                return {
                    "date": s.get("date", ""),
                    "opponent": opp,
                    "venue_type": venue_type,
                    "innings": st.get("inningsPitched", "0.0"),
                    "hits": st.get("hits", 0),
                    "runs": st.get("runs", 0),
                    "er": st.get("earnedRuns", 0),
                    "hr": st.get("homeRuns", 0),
                    "so": st.get("strikeOuts", 0),
                    "bb": st.get("baseOnBalls", 0),
                    "era": st.get("era", "0.00"),
                    "is_win": s.get("isWin", False)
                }

            # 최근 전체 5경기 (가장 최근 순)
            recent_5_overall = [format_log(s) for s in splits[-5:][::-1]]

            # 조건별 5경기 (홈 선발은 홈 경기만, 원정 선발은 원정 경기만)
            cond_splits = [s for s in splits if s.get("isHome") == is_home]
            split_label = "홈" if is_home else "원정"
            recent_5_split = [format_log(s) for s in cond_splits[-5:][::-1]]

            return {
                "recent_5_overall": recent_5_overall,
                "recent_5_split": recent_5_split,
                "split_condition": f"최근 {split_label} 5경기"
            }
        except Exception as e:
            logger.debug(f"선발투수(ID: {person_id}) 게임로그 조회 실패: {e}")
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

            # 선발 투수 스탯 및 최근 5경기/조건별 5경기 수집
            away_pitcher_stats = self.fetch_pitcher_stats(away_pitcher_id, is_home=False) if away_pitcher_id else {}
            if away_pitcher_id:
                away_pitcher_stats.update(self.fetch_pitcher_game_logs(away_pitcher_id, is_home=False))

            home_pitcher_stats = self.fetch_pitcher_stats(home_pitcher_id, is_home=True) if home_pitcher_id else {}
            if home_pitcher_id:
                home_pitcher_stats.update(self.fetch_pitcher_game_logs(home_pitcher_id, is_home=True))

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

    def fetch_results(self, target_date: str) -> List[Dict[str, Any]]:
        """
        특정 날짜의 MLB 최종 경기 결과 및 5이닝(F5) 스코어 수집
        :param target_date: 'YYYY-MM-DD'
        """
        url = f"{self.BASE_URL}/schedule"
        params = {
            "sportId": 1,
            "date": target_date,
            "hydrate": "linescore,team"
        }

        logger.info(f"MLB 경기 결과 수집 중: {target_date}...")
        try:
            resp = self.session.get(url, params=params, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.error(f"MLB 결과 조회 오류: {e}")
            return []

        dates = data.get("dates", [])
        if not dates:
            return []

        results = []
        for g in dates[0].get("games", []):
            status = g.get("status", {}).get("detailedState", "")
            if status not in ["Final", "Completed Early", "Game Over"]:
                continue  # 아직 끝나지 않은 경기는 제외

            teams = g.get("teams", {})
            away_team = teams.get("away", {}).get("team", {}).get("name", "Away")
            home_team = teams.get("home", {}).get("team", {}).get("name", "Home")

            away_score = teams.get("away", {}).get("score", 0)
            home_score = teams.get("home", {}).get("score", 0)

            actual_winner = away_team if away_score > home_score else (home_team if home_score > away_score else "무승부")
            total_runs = away_score + home_score

            # 5이닝(F5) 점수 계산
            linescore = g.get("linescore", {})
            innings = linescore.get("innings", [])
            f5_innings = innings[:5]

            f5_away = sum(i.get("away", {}).get("runs", 0) for i in f5_innings)
            f5_home = sum(i.get("home", {}).get("runs", 0) for i in f5_innings)
            f5_winner = away_team if f5_away > f5_home else (home_team if f5_home > f5_away else "무승부")
            f5_total = f5_away + f5_home

            results.append({
                "league": "MLB",
                "game_id": g.get("gamePk"),
                "date": target_date,
                "away_team": away_team,
                "home_team": home_team,
                "status": status,
                "actual_away_score": away_score,
                "actual_home_score": home_score,
                "actual_winner": actual_winner,
                "total_runs": total_runs,
                "f5_away_score": f5_away,
                "f5_home_score": f5_home,
                "f5_winner": f5_winner,
                "f5_total_runs": f5_total
            })

        logger.info(f"MLB {len(results)}개 완료 경기 결과(5이닝 포함) 수집 완료")
        return results


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    collector = MLBCollector()
    games = collector.fetch_schedule()
    print(json.dumps(games[:1], indent=2, ensure_ascii=False))
