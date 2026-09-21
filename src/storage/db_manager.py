import os
import sqlite3
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

# 기본 DB 파일 경로: data/sports_analytics.db
DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
DEFAULT_DB_PATH = DATA_DIR / "sports_analytics.db"

class DatabaseManager:
    """
    DBeaver 26.2+ 완벽 호환 SQLite 데이터베이스 매니저
    - 풀이닝 및 5이닝(F5) 예측, 실제 경기 결과, 적중 정산 데이터 영구 보존
    """
    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.init_db()

    def get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self):
        """테이블 스키마 초기화 (DBeaver에서 테이블 및 컬럼 시각화 지원)"""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            # 1. 경기 예측 테이블 (풀이닝 + 5이닝)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS predictions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                match_date TEXT NOT NULL,
                league TEXT NOT NULL,
                game_id TEXT,
                away_team TEXT NOT NULL,
                home_team TEXT NOT NULL,
                away_pitcher TEXT,
                home_pitcher TEXT,
                
                -- 풀이닝 예측
                pred_winner TEXT,
                pred_away_score INTEGER,
                pred_home_score INTEGER,
                pred_ou_pick TEXT,       -- '오버' 또는 '언더'
                pred_ou_line REAL,       -- 예: 8.5
                
                -- 5이닝(F5) 특화 예측
                pred_f5_winner TEXT,     -- 원정팀명, 홈팀명, 또는 '무승부'
                pred_f5_away_score INTEGER,
                pred_f5_home_score INTEGER,
                pred_f5_ou_pick TEXT,    -- '오버' 또는 '언더'
                pred_f5_ou_line REAL,    -- 예: 4.5
                
                confidence_stars INTEGER DEFAULT 3,
                is_top_pick BOOLEAN DEFAULT 0,
                analysis_summary TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(match_date, league, away_team, home_team)
            );
            """)

            # 2. 실제 경기 결과 테이블 (풀이닝 + 5이닝)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS game_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                match_date TEXT NOT NULL,
                league TEXT NOT NULL,
                game_id TEXT,
                away_team TEXT NOT NULL,
                home_team TEXT NOT NULL,
                status TEXT,
                
                -- 풀이닝 실제 결과
                actual_away_score INTEGER,
                actual_home_score INTEGER,
                actual_winner TEXT,
                total_runs INTEGER,
                
                -- 5이닝(F5) 실제 결과
                f5_away_score INTEGER,
                f5_home_score INTEGER,
                f5_winner TEXT,          -- 원정팀명, 홈팀명, 또는 '무승부'
                f5_total_runs INTEGER,
                
                settled_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(match_date, league, away_team, home_team)
            );
            """)

            # 3. 적중 정산 및 평가 테이블
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS settlements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                prediction_id INTEGER UNIQUE,
                match_date TEXT NOT NULL,
                league TEXT NOT NULL,
                away_team TEXT NOT NULL,
                home_team TEXT NOT NULL,
                
                -- 풀이닝 판정 (1: 적중, 0: 미적중, NULL: 취소/미정)
                is_winner_hit INTEGER,
                is_ou_hit INTEGER,
                score_diff_error INTEGER,
                
                -- 5이닝 판정 (1: 적중, 0: 미적중, NULL: 취소/미정)
                is_f5_winner_hit INTEGER,
                is_f5_ou_hit INTEGER,
                f5_score_diff_error INTEGER,
                
                is_top_pick INTEGER,
                settled_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (prediction_id) REFERENCES predictions(id)
            );
            """)

            # 4. 일별 누적 통계 뷰 (DBeaver에서 바로 조회 가능한 View)
            cursor.execute("""
            CREATE VIEW IF NOT EXISTS v_daily_accuracy AS
            SELECT 
                match_date,
                league,
                COUNT(*) as total_games,
                SUM(is_winner_hit) as winner_hits,
                ROUND(AVG(is_winner_hit) * 100, 1) as winner_hit_rate,
                SUM(is_ou_hit) as ou_hits,
                ROUND(AVG(is_ou_hit) * 100, 1) as ou_hit_rate,
                SUM(is_f5_winner_hit) as f5_winner_hits,
                ROUND(AVG(is_f5_winner_hit) * 100, 1) as f5_winner_hit_rate,
                SUM(is_f5_ou_hit) as f5_ou_hits,
                ROUND(AVG(is_f5_ou_hit) * 100, 1) as f5_ou_hit_rate,
                SUM(CASE WHEN is_top_pick = 1 AND is_winner_hit = 1 THEN 1 ELSE 0 END) as top_pick_hits,
                SUM(CASE WHEN is_top_pick = 1 THEN 1 ELSE 0 END) as top_pick_total
            FROM settlements
            GROUP BY match_date, league;
            """)

            conn.commit()
            logger.info(f"SQLite 데이터베이스 초기화 완료: {self.db_path}")

    def save_predictions(self, match_date: str, league: str, preds: List[Dict[str, Any]]):
        """예측 데이터 저장 (INSERT OR REPLACE)"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            for p in preds:
                cursor.execute("""
                INSERT INTO predictions (
                    match_date, league, game_id, away_team, home_team, away_pitcher, home_pitcher,
                    pred_winner, pred_away_score, pred_home_score, pred_ou_pick, pred_ou_line,
                    pred_f5_winner, pred_f5_away_score, pred_f5_home_score, pred_f5_ou_pick, pred_f5_ou_line,
                    confidence_stars, is_top_pick, analysis_summary
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(match_date, league, away_team, home_team) DO UPDATE SET
                    pred_winner=excluded.pred_winner,
                    pred_away_score=excluded.pred_away_score,
                    pred_home_score=excluded.pred_home_score,
                    pred_ou_pick=excluded.pred_ou_pick,
                    pred_ou_line=excluded.pred_ou_line,
                    pred_f5_winner=excluded.pred_f5_winner,
                    pred_f5_away_score=excluded.pred_f5_away_score,
                    pred_f5_home_score=excluded.pred_f5_home_score,
                    pred_f5_ou_pick=excluded.pred_f5_ou_pick,
                    pred_f5_ou_line=excluded.pred_f5_ou_line,
                    confidence_stars=excluded.confidence_stars,
                    is_top_pick=excluded.is_top_pick,
                    analysis_summary=excluded.analysis_summary;
                """, (
                    match_date, league, str(p.get("game_id", "")),
                    p.get("away_team", ""), p.get("home_team", ""),
                    p.get("away_pitcher", ""), p.get("home_pitcher", ""),
                    p.get("pred_winner"), p.get("pred_away_score"), p.get("pred_home_score"),
                    p.get("pred_ou_pick"), p.get("pred_ou_line"),
                    p.get("pred_f5_winner"), p.get("pred_f5_away_score"), p.get("pred_f5_home_score"),
                    p.get("pred_f5_ou_pick"), p.get("pred_f5_ou_line"),
                    p.get("confidence_stars", 3), 1 if p.get("is_top_pick") else 0,
                    p.get("analysis_summary", "")
                ))
            conn.commit()

    def save_game_results(self, match_date: str, league: str, results: List[Dict[str, Any]]):
        """실제 경기 결과 저장 (INSERT OR REPLACE)"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            for r in results:
                cursor.execute("""
                INSERT INTO game_results (
                    match_date, league, game_id, away_team, home_team, status,
                    actual_away_score, actual_home_score, actual_winner, total_runs,
                    f5_away_score, f5_home_score, f5_winner, f5_total_runs
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(match_date, league, away_team, home_team) DO UPDATE SET
                    actual_away_score=excluded.actual_away_score,
                    actual_home_score=excluded.actual_home_score,
                    actual_winner=excluded.actual_winner,
                    total_runs=excluded.total_runs,
                    f5_away_score=excluded.f5_away_score,
                    f5_home_score=excluded.f5_home_score,
                    f5_winner=excluded.f5_winner,
                    f5_total_runs=excluded.f5_total_runs,
                    status=excluded.status;
                """, (
                    match_date, league, str(r.get("game_id", "")),
                    r.get("away_team", ""), r.get("home_team", ""), r.get("status", "Final"),
                    r.get("actual_away_score"), r.get("actual_home_score"),
                    r.get("actual_winner"), r.get("total_runs"),
                    r.get("f5_away_score"), r.get("f5_home_score"),
                    r.get("f5_winner"), r.get("f5_total_runs")
                ))
            conn.commit()

    def get_unsettled_predictions(self, match_date: str, league: str) -> List[Dict[str, Any]]:
        """정산되지 않은 과거 예측 데이터 조회"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            SELECT p.* 
            FROM predictions p
            LEFT JOIN settlements s ON p.id = s.prediction_id
            WHERE p.match_date = ? AND p.league = ? AND s.id IS NULL;
            """, (match_date, league))
            return [dict(row) for row in cursor.fetchall()]

    def save_settlement(self, settlement_data: Dict[str, Any]):
        """적중 결과 정산 데이터 저장"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            INSERT INTO settlements (
                prediction_id, match_date, league, away_team, home_team,
                is_winner_hit, is_ou_hit, score_diff_error,
                is_f5_winner_hit, is_f5_ou_hit, f5_score_diff_error,
                is_top_pick
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(prediction_id) DO UPDATE SET
                is_winner_hit=excluded.is_winner_hit,
                is_ou_hit=excluded.is_ou_hit,
                score_diff_error=excluded.score_diff_error,
                is_f5_winner_hit=excluded.is_f5_winner_hit,
                is_f5_ou_hit=excluded.is_f5_ou_hit,
                f5_score_diff_error=excluded.f5_score_diff_error,
                is_top_pick=excluded.is_top_pick;
            """, (
                settlement_data.get("prediction_id"),
                settlement_data.get("match_date"),
                settlement_data.get("league"),
                settlement_data.get("away_team"),
                settlement_data.get("home_team"),
                settlement_data.get("is_winner_hit"),
                settlement_data.get("is_ou_hit"),
                settlement_data.get("score_diff_error"),
                settlement_data.get("is_f5_winner_hit"),
                settlement_data.get("is_f5_ou_hit"),
                settlement_data.get("f5_score_diff_error"),
                1 if settlement_data.get("is_top_pick") else 0
            ))
            conn.commit()

    def get_recent_stats(self, days: int = 14) -> Dict[str, Any]:
        """최근 N일간 누적 적중률 통계 요약"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            SELECT 
                COUNT(*) as total,
                SUM(is_winner_hit) as winner_hits,
                ROUND(AVG(is_winner_hit) * 100, 1) as winner_rate,
                SUM(is_ou_hit) as ou_hits,
                ROUND(AVG(is_ou_hit) * 100, 1) as ou_rate,
                SUM(is_f5_winner_hit) as f5_winner_hits,
                ROUND(AVG(is_f5_winner_hit) * 100, 1) as f5_winner_rate,
                SUM(is_f5_ou_hit) as f5_ou_hits,
                ROUND(AVG(is_f5_ou_hit) * 100, 1) as f5_ou_rate
            FROM settlements
            WHERE match_date >= date('now', '-' || ? || ' days');
            """, (days,))
            row = cursor.fetchone()
            if row and row["total"]:
                return dict(row)
            return {
                "total": 0, "winner_hits": 0, "winner_rate": 0.0,
                "ou_hits": 0, "ou_rate": 0.0, "f5_winner_hits": 0,
                "f5_winner_rate": 0.0, "f5_ou_hits": 0, "f5_ou_rate": 0.0
            }

    def get_advanced_feedback(self, days: int = 14) -> Dict[str, Any]:
        """
        [고도화 Step 4] LLM 자가 교정을 위한 상세 진단 통계 (편향, 신뢰도 검증, 불펜 리스크)
        """
        base_stats = self.get_recent_stats(days=days)
        if not base_stats or base_stats.get("total", 0) == 0:
            return {
                "has_data": False,
                "summary_text": "아직 충분한 누적 정산 데이터가 없습니다. (초기 기준 적용)"
            }

        with self.get_connection() as conn:
            cursor = conn.cursor()

            # 1. 고신뢰도(별 4개 이상) 픽 적중률
            cursor.execute("""
            SELECT 
                COUNT(*) as high_conf_total,
                SUM(s.is_winner_hit) as high_conf_hits,
                ROUND(AVG(s.is_winner_hit) * 100, 1) as high_conf_rate
            FROM settlements s
            JOIN predictions p ON s.prediction_id = p.id
            WHERE p.confidence_stars >= 4;
            """)
            high_conf = dict(cursor.fetchone() or {})

            # 2. 불펜 변수 괴리: 5이닝은 맞췄으나 풀이닝에서 역전패한 경기 수
            cursor.execute("""
            SELECT COUNT(*) as bullpen_blown_count
            FROM settlements
            WHERE is_f5_winner_hit = 1 AND is_winner_hit = 0;
            """)
            blown = cursor.fetchone()[0] or 0

            # 3. 언더/오버 편향 분석 (실제 결과가 언더가 많았는지 오버가 많았는지)
            cursor.execute("""
            SELECT 
                SUM(CASE WHEN p.pred_ou_pick = '오버' AND s.is_ou_hit = 0 THEN 1 ELSE 0 END) as over_misses,
                SUM(CASE WHEN p.pred_ou_pick = '언더' AND s.is_ou_hit = 0 THEN 1 ELSE 0 END) as under_misses
            FROM settlements s
            JOIN predictions p ON s.prediction_id = p.id;
            """)
            ou_bias = dict(cursor.fetchone() or {})

            # 피드백 문구 조립
            insights = []
            insights.append(f"• 최근 누적 승패 적중률: {base_stats['winner_rate']}% ({base_stats['winner_hits']}/{base_stats['total']})")
            insights.append(f"• 5이닝(F5) 승패 적중률: {base_stats['f5_winner_rate']}% ({base_stats['f5_winner_hits']}/{base_stats['total']})")

            hc_total = high_conf.get("high_conf_total", 0)
            if hc_total > 0:
                insights.append(f"• 별 4개 이상 고신뢰도 픽 성공률: {high_conf.get('high_conf_rate', 0)}% ({high_conf.get('high_conf_hits', 0)}/{hc_total})")

            if blown > 0:
                insights.append(f"• ⚠️ 불펜 역전패 리스크 감지: 선발이 5회까지 리드했으나 불펜 방화로 풀이닝 승리를 놓친 사례 {blown}건 발생 (불펜 취약 팀은 풀이닝보다 5이닝 픽 추천 요망)")

            over_m = ou_bias.get("over_misses", 0) or 0
            under_m = ou_bias.get("under_misses", 0) or 0
            if over_m > under_m:
                insights.append(f"• ⚠️ 언더/오버 편향 경고: 오버 예측 실패({over_m}건)가 언더 실패({under_m}건)보다 많음. 총 득점 기준점을 더 보수적(언더 성향)으로 고려할 것")
            elif under_m > over_m:
                insights.append(f"• ⚠️ 언더/오버 편향 경고: 언더 예측 실패({under_m}건)가 오버 실패({over_m}건)보다 많음. 최근 타선 득점권 활약을 더 적극 반영할 것")

            return {
                "has_data": True,
                "base_stats": base_stats,
                "high_conf": high_conf,
                "blown_count": blown,
                "ou_bias": ou_bias,
                "summary_text": "\n".join(insights)
            }
