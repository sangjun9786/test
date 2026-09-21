import json
import logging
import re
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional
import requests

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))

def parse_innings_str(ip_str: str) -> float:
    """'24 2/3' 또는 '47.2' 또는 '1 1/3' 등의 이닝 문자열을 float 값으로 파싱"""
    try:
        ip_str = str(ip_str).strip()
        if not ip_str or ip_str == '-':
            return 0.0
        if ' ' in ip_str and '/' in ip_str:
            whole, frac = ip_str.split(' ')
            n, d = frac.split('/')
            return float(whole) + float(n) / float(d)
        elif '/' in ip_str:
            n, d = ip_str.split('/')
            return float(n) / float(d)
        elif '.' in ip_str:
            parts = ip_str.split('.')
            whole = float(parts[0])
            dec = parts[1]
            if dec == '1':
                return whole + (1.0 / 3.0)
            elif dec == '2':
                return whole + (2.0 / 3.0)
            return whole + float(f"0.{dec}")
        return float(ip_str)
    except Exception:
        return 0.0


class KBOCollector:
    """
    국내 야구(KBO) 당일 경기 일정, 선발 투수(예고 투수), 시즌 피홈런 및 홈/원정 스플릿 실시간 수집기
    """
    DAUM_SCHEDULE_URL = "https://sports.daum.net/prx/hermes/api/game/schedule.json"
    NAVER_SCHEDULE_URL = "https://api-gw.sports.naver.com/schedule/games"
    NAVER_PREVIEW_URL = "https://api-gw.sports.naver.com/schedule/games/{game_id}/preview"

    def __init__(self, timeout: int = 15):
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Referer": "https://sports.daum.net/schedule/kbo"
        })

    def fetch_kbo_official_split(self, player_id: str, is_home: bool) -> Dict[str, Any]:
        """
        KBO 공식 기록실(koreabaseball.com) 등판 일지에서 홈 또는 방문(원정) 스플릿 지표 집계
        :param player_id: KBO 선수 번호 (예: 54729)
        :param is_home: 홈 등판 여부 (True면 홈, False면 방문/원정)
        """
        if not player_id:
            return {}

        url = f"https://www.koreabaseball.com/Record/Player/PitcherDetail/Basic.aspx?playerId={player_id}"
        try:
            resp = self.session.get(url, timeout=self.timeout)
            resp.encoding = 'utf-8'
            tables = re.findall(r'<table[^>]*>(.*?)</table>', resp.text, re.DOTALL)
            if len(tables) < 3:
                return {}

            t2 = tables[2]  # 등판 일지 테이블
            rows = re.findall(r'<tr[^>]*>(.*?)</tr>', t2, re.DOTALL)

            target_gubun = '홈' if is_home else '방문'
            total_er = 0
            total_ip = 0.0
            total_h = 0
            total_hr = 0
            total_so = 0
            total_bb = 0
            games_count = 0

            for r in rows:
                cols = [re.sub(r'<[^>]+>', '', c).strip() for c in re.findall(r'<td[^>]*>(.*?)</td>', r, re.DOTALL)]
                if len(cols) >= 14:
                    gubun = cols[1]  # '홈' 또는 '방문'
                    if gubun == target_gubun:
                        games_count += 1
                        ip_val = parse_innings_str(cols[6])
                        total_ip += ip_val
                        total_h += int(cols[7]) if cols[7].isdigit() else 0
                        total_hr += int(cols[8]) if cols[8].isdigit() else 0
                        total_bb += int(cols[9]) if cols[9].isdigit() else 0
                        total_so += int(cols[11]) if cols[11].isdigit() else 0
                        total_er += int(cols[13]) if cols[13].isdigit() else 0

            if games_count == 0 or total_ip == 0.0:
                return {}

            era = round((total_er * 9.0) / total_ip, 2)
            hr9 = round((total_hr * 9.0) / total_ip, 2)
            whip = round((total_h + total_bb) / total_ip, 2)

            return {
                "split_type": "홈(Home)" if is_home else "원정(Away)",
                "games": games_count,
                "era": f"{era:.2f}",
                "whip": f"{whip:.2f}",
                "inningsPitched": f"{total_ip:.1f}",
                "homeRuns": total_hr,
                "hr9": f"{hr9:.2f}",
                "hits": total_h,
                "strikeouts": total_so,
                "walks": total_bb
            }
        except Exception as e:
            logger.debug(f"KBO 공식 기록실 스플릿 조회 실패 ({player_id}): {e}")
            return {}

    def fetch_schedule_via_naver(self, display_date: str) -> List[Dict[str, Any]]:
        """
        네이버 스포츠 API를 통해 KBO 상세 일정, 선발투수 시즌 지표(피홈런 포함) 및 홈/원정 스플릿 수집
        """
        params = {
            "fields": "basic,superKey,status,homePitcher,awayPitcher",
            "fromDate": display_date,
            "toDate": display_date,
            "upperCategoryId": "kbaseball",
            "category": "kbo"
        }

        try:
            resp = self.session.get(self.NAVER_SCHEDULE_URL, params=params, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
            games = [g for g in data.get("result", {}).get("games", []) if g.get("categoryId") == "kbo"]
            if not games:
                return []

            processed_games = []
            for g in games:
                game_id = g.get("gameId")
                game_time = g.get("gameDateTime", "")
                formatted_time = game_time[11:16] if len(game_time) >= 16 else "시간 미정"
                status_code = g.get("statusCode", "")
                status_info = g.get("statusInfo", "")

                if g.get("cancel") or "취소" in status_info:
                    status_desc = "취소/연기"
                elif status_code == "RESULT" or "종료" in status_info:
                    status_desc = "경기 종료"
                elif status_code in ["STARTED", "ROUND"]:
                    status_desc = "경기 진행 중"
                else:
                    status_desc = "경기 시작 전"

                away_team_name = g.get("awayTeamName") or "원정팀"
                home_team_name = g.get("homeTeamName") or "홈팀"
                stadium = g.get("stadium") or "홈 구장"

                # 네이버 프리뷰 API 상세 조회 (선발 투수 및 세부 스탯)
                away_pitcher_data: Dict[str, Any] = {"name": g.get("awayPitcherName") or "미정"}
                home_pitcher_data: Dict[str, Any] = {"name": g.get("homePitcherName") or "미정"}
                away_record_str = "KBO 정규시즌"
                home_record_str = "KBO 정규시즌"

                try:
                    prev_resp = self.session.get(self.NAVER_PREVIEW_URL.format(game_id=game_id), timeout=self.timeout)
                    if prev_resp.status_code == 200:
                        prev_json = prev_resp.json()
                        prev_data = prev_json.get("result", {}).get("previewData", {})

                        # 팀 성적
                        aw_stand = prev_data.get("awayStandings", {})
                        hm_stand = prev_data.get("homeStandings", {})
                        if aw_stand:
                            away_record_str = f"{aw_stand.get('w', 0)}승 {aw_stand.get('l', 0)}패 {aw_stand.get('d', 0)}무 (승률 {aw_stand.get('wra', '.000')})"
                        if hm_stand:
                            home_record_str = f"{hm_stand.get('w', 0)}승 {hm_stand.get('l', 0)}패 {hm_stand.get('d', 0)}무 (승률 {hm_stand.get('wra', '.000')})"

                        # 원정 선발투수
                        aw_starter = prev_data.get("awayStarter", {})
                        if aw_starter:
                            aw_pinfo = aw_starter.get("playerInfo", {})
                            aw_season = aw_starter.get("currentSeasonStats", {})
                            aw_pcode = aw_pinfo.get("pCode", "")

                            away_pitcher_data = {
                                "name": aw_pinfo.get("name", away_pitcher_data["name"]),
                                "p_code": aw_pcode,
                                "era": aw_season.get("era", "N/A"),
                                "whip": aw_season.get("whip", "N/A"),
                                "wins": aw_season.get("w", 0),
                                "losses": aw_season.get("l", 0),
                                "inningsPitched": aw_season.get("inn", "0.0"),
                                "homeRuns": aw_season.get("hr", 0),
                                "strikeouts": aw_season.get("kk", 0),
                                "walks": aw_season.get("bb", 0),
                                "hits": aw_season.get("hit", 0)
                            }
                            # 상대팀 맞대결
                            aw_opp = aw_starter.get("currentSeasonStatsOnOpponents", {})
                            if aw_opp and aw_opp.get("inn"):
                                away_pitcher_data["vs_opponent"] = {
                                    "era": aw_opp.get("era", "N/A"),
                                    "innings": aw_opp.get("inn", "0.0"),
                                    "er": aw_opp.get("er", 0)
                                }
                            # 원정 등판 스플릿 (KBO 공식 기록실 연동)
                            if aw_pcode:
                                split = self.fetch_kbo_official_split(aw_pcode, is_home=False)
                                if split:
                                    away_pitcher_data["split_stats"] = split

                        # 홈 선발투수
                        hm_starter = prev_data.get("homeStarter", {})
                        if hm_starter:
                            hm_pinfo = hm_starter.get("playerInfo", {})
                            hm_season = hm_starter.get("currentSeasonStats", {})
                            hm_pcode = hm_pinfo.get("pCode", "")

                            home_pitcher_data = {
                                "name": hm_pinfo.get("name", home_pitcher_data["name"]),
                                "p_code": hm_pcode,
                                "era": hm_season.get("era", "N/A"),
                                "whip": hm_season.get("whip", "N/A"),
                                "wins": hm_season.get("w", 0),
                                "losses": hm_season.get("l", 0),
                                "inningsPitched": hm_season.get("inn", "0.0"),
                                "homeRuns": hm_season.get("hr", 0),
                                "strikeouts": hm_season.get("kk", 0),
                                "walks": hm_season.get("bb", 0),
                                "hits": hm_season.get("hit", 0)
                            }
                            # 상대팀 맞대결
                            hm_opp = hm_starter.get("currentSeasonStatsOnOpponents", {})
                            if hm_opp and hm_opp.get("inn"):
                                home_pitcher_data["vs_opponent"] = {
                                    "era": hm_opp.get("era", "N/A"),
                                    "innings": hm_opp.get("inn", "0.0"),
                                    "er": hm_opp.get("er", 0)
                                }
                            # 홈 등판 스플릿 (KBO 공식 기록실 연동)
                            if hm_pcode:
                                split = self.fetch_kbo_official_split(hm_pcode, is_home=True)
                                if split:
                                    home_pitcher_data["split_stats"] = split
                except Exception as ex:
                    logger.debug(f"네이버 프리뷰 조회 중 예외 ({game_id}): {ex}")

                processed_games.append({
                    "league": "KBO",
                    "game_id": game_id,
                    "date": display_date,
                    "start_time_kst": formatted_time,
                    "status": status_desc,
                    "venue": stadium,
                    "away_team": {
                        "name": away_team_name,
                        "record": away_record_str,
                        "pitcher": away_pitcher_data
                    },
                    "home_team": {
                        "name": home_team_name,
                        "record": home_record_str,
                        "pitcher": home_pitcher_data
                    }
                })

            return processed_games
        except Exception as e:
            logger.warning(f"네이버 KBO 스케줄 조회 실패 ({e}), Daum API로 폴백합니다.")
            return []

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

        logger.info(f"KBO 경기 데이터 수집 중: {display_date}...")

        # 1차: 네이버 스포츠 프리뷰 및 KBO 공식 기록실 연동 수집
        games = self.fetch_schedule_via_naver(display_date)
        if games:
            logger.info(f"KBO {len(games)}개 경기 데이터 수집 완료 (네이버+공식기록실 고도화)")
            return games

        # 2차 폴백: Daum Hermes API
        params = {
            "page": 1,
            "leagueCode": "kbo",
            "fromDate": date_key,
            "toDate": date_key
        }

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
            formatted_time = f"{raw_time[:2]}:{raw_time[2:]}" if len(raw_time) == 4 else (raw_time or "시간 미정")

            status = g.get("gameStatus", "BEFORE")
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
                    "record": away_wlt if away_wlt else "KBO 정규시즌",
                    "pitcher": {"name": away_pitcher}
                },
                "home_team": {
                    "name": home_team,
                    "record": home_wlt if home_wlt else "KBO 정규시즌",
                    "pitcher": {"name": home_pitcher}
                }
            })

        logger.info(f"KBO {len(processed_games)}개 경기 데이터 수집 완료 (Daum 폴백)")
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
    games = collector.fetch_schedule("2026-09-20")
    print(json.dumps(games[:1], indent=2, ensure_ascii=False))
