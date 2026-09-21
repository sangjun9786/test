import logging
from typing import List, Dict, Any, Optional
from ..storage.db_manager import DatabaseManager

logger = logging.getLogger(__name__)

class ResultEvaluator:
    """
    과거 예측과 실제 경기 결과(풀이닝 + 5이닝)를 비교/정산하는 평가 엔진
    """
    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager

    def evaluate_date(self, match_date: str, league: str, actual_results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        특정 날짜의 예측 목록과 실제 결과를 매칭하여 적중 여부 판정 및 DB 저장
        """
        unsettled = self.db.get_unsettled_predictions(match_date, league)
        if not unsettled:
            logger.info(f"[{league}] {match_date} 정산 대상 예측 데이터가 없습니다.")
            return {}

        # 결과 딕셔너리 키 매핑 (away_team, home_team)
        results_map = {}
        for r in actual_results:
            key = (r["away_team"].strip().lower(), r["home_team"].strip().lower())
            results_map[key] = r

        settled_list = []
        winner_hits = 0
        ou_hits = 0
        f5_winner_hits = 0
        f5_ou_hits = 0
        top_pick_hits = 0
        top_pick_total = 0

        for pred in unsettled:
            p_away = pred["away_team"].strip().lower()
            p_home = pred["home_team"].strip().lower()

            # 매칭 검색 (팀명 포함 관계 매칭 지원)
            actual = None
            for (r_away, r_home), res in results_map.items():
                if (p_away in r_away or r_away in p_away) and (p_home in r_home or r_home in p_home):
                    actual = res
                    break

            if not actual:
                continue

            # 1. 풀이닝 승패 판정
            pred_winner = (pred.get("pred_winner") or "").strip()
            act_winner = (actual.get("actual_winner") or "").strip()
            is_winner_hit = 1 if (pred_winner and (pred_winner in act_winner or act_winner in pred_winner)) else 0

            # 2. 풀이닝 언오버 판정
            pred_ou_pick = (pred.get("pred_ou_pick") or "").strip()
            pred_ou_line = pred.get("pred_ou_line")
            actual_total = actual.get("total_runs", 0)

            is_ou_hit = None
            if pred_ou_pick and pred_ou_line is not None:
                if pred_ou_pick == "오버":
                    is_ou_hit = 1 if actual_total > pred_ou_line else 0
                elif pred_ou_pick == "언더":
                    is_ou_hit = 1 if actual_total < pred_ou_line else 0

            # 점수 오차
            pred_away_s = pred.get("pred_away_score") or 0
            pred_home_s = pred.get("pred_home_score") or 0
            act_away_s = actual.get("actual_away_score") or 0
            act_home_s = actual.get("actual_home_score") or 0
            score_diff_error = abs(pred_away_s - act_away_s) + abs(pred_home_s - act_home_s)

            # 3. 5이닝(F5) 승패 판정
            pred_f5_w = (pred.get("pred_f5_winner") or "").strip()
            act_f5_w = (actual.get("f5_winner") or "").strip()
            is_f5_winner_hit = 1 if (pred_f5_w and (pred_f5_w in act_f5_w or act_f5_w in pred_f5_w)) else 0

            # 4. 5이닝(F5) 언오버 판정
            pred_f5_ou_pick = (pred.get("pred_f5_ou_pick") or "").strip()
            pred_f5_ou_line = pred.get("pred_f5_ou_line")
            act_f5_total = actual.get("f5_total_runs", 0)

            is_f5_ou_hit = None
            if pred_f5_ou_pick and pred_f5_ou_line is not None:
                if pred_f5_ou_pick == "오버":
                    is_f5_ou_hit = 1 if act_f5_total > pred_f5_ou_line else 0
                elif pred_f5_ou_pick == "언더":
                    is_f5_ou_hit = 1 if act_f5_total < pred_f5_ou_line else 0

            f5_away_s = pred.get("pred_f5_away_score") or 0
            f5_home_s = pred.get("pred_f5_home_score") or 0
            act_f5_away_s = actual.get("f5_away_score") or 0
            act_f5_home_s = actual.get("f5_home_score") or 0
            f5_score_diff_error = abs(f5_away_s - act_f5_away_s) + abs(f5_home_s - act_f5_home_s)

            is_top_pick = bool(pred.get("is_top_pick"))

            # 정산 데이터 저장
            settle_row = {
                "prediction_id": pred["id"],
                "match_date": match_date,
                "league": league,
                "away_team": pred["away_team"],
                "home_team": pred["home_team"],
                "is_winner_hit": is_winner_hit,
                "is_ou_hit": is_ou_hit if is_ou_hit is not None else 0,
                "score_diff_error": score_diff_error,
                "is_f5_winner_hit": is_f5_winner_hit,
                "is_f5_ou_hit": is_f5_ou_hit if is_f5_ou_hit is not None else 0,
                "f5_score_diff_error": f5_score_diff_error,
                "is_top_pick": is_top_pick
            }
            self.db.save_settlement(settle_row)

            # 통계 집계
            if is_winner_hit: winner_hits += 1
            if is_ou_hit == 1: ou_hits += 1
            if is_f5_winner_hit: f5_winner_hits += 1
            if is_f5_ou_hit == 1: f5_ou_hits += 1
            if is_top_pick:
                top_pick_total += 1
                if is_winner_hit: top_pick_hits += 1

            settled_list.append({
                "pred": pred,
                "actual": actual,
                "settle": settle_row
            })

        total = len(settled_list)
        if total == 0:
            return {}

        return {
            "match_date": match_date,
            "league": league,
            "total_games": total,
            "winner_hits": winner_hits,
            "winner_rate": round(winner_hits / total * 100, 1),
            "ou_hits": ou_hits,
            "ou_rate": round(ou_hits / total * 100, 1),
            "f5_winner_hits": f5_winner_hits,
            "f5_winner_rate": round(f5_winner_hits / total * 100, 1),
            "f5_ou_hits": f5_ou_hits,
            "f5_ou_rate": round(f5_ou_hits / total * 100, 1),
            "top_pick_hits": top_pick_hits,
            "top_pick_total": top_pick_total,
            "details": settled_list
        }

    def generate_settlement_report_markdown(self, summary: Dict[str, Any]) -> str:
        """디스코드 발송용 정산 리포트 마크다운 생성"""
        if not summary or not summary.get("total_games"):
            return ""

        date = summary["match_date"]
        league = summary["league"]
        total = summary["total_games"]

        w_hits = summary["winner_hits"]
        w_rate = summary["winner_rate"]
        ou_hits = summary["ou_hits"]
        ou_rate = summary["ou_rate"]

        f5_w_hits = summary["f5_winner_hits"]
        f5_w_rate = summary["f5_winner_rate"]
        f5_ou_hits = summary["f5_ou_hits"]
        f5_ou_rate = summary["f5_ou_rate"]

        top_h = summary["top_pick_hits"]
        top_t = summary["top_pick_total"]

        lines = [
            f"# 📈 [{league} 어제 예측 결과 정산] ({date})",
            f"어제 추천해 드린 총 **{total}경기**의 최종 결과 및 적중률입니다.\n",
            "### 🎯 주요 적중 성적 요약",
            f"- **풀이닝 승패 적중률**: `{w_hits}/{total}` (**{w_rate}%**)",
            f"- **풀이닝 언/오버 적중률**: `{ou_hits}/{total}` (**{ou_rate}%**)",
            f"- **⚡ 5이닝(F5) 승패 적중률**: `{f5_w_hits}/{total}` (**{f5_w_rate}%**)",
            f"- **⚡ 5이닝(F5) 언/오버 적중률**: `{f5_ou_hits}/{total}` (**{f5_ou_rate}%**)",
        ]

        if top_t > 0:
            lines.append(f"- **🏆 TOP 추천 픽 적중**: `{top_h}/{top_t}` (**{round(top_h/top_t*100, 1)}%**)")

        lines.append("\n---")
        lines.append("### 🔍 경기별 상세 결과")

        for item in summary.get("details", []):
            pred = item["pred"]
            actual = item["actual"]
            settle = item["settle"]

            match_name = f"{pred['away_team']} vs {pred['home_team']}"
            score_str = f"최종 {actual['actual_away_score']} : {actual['actual_home_score']} (승리: {actual['actual_winner']})"
            f5_score_str = f"5회말 {actual['f5_away_score']} : {actual['f5_home_score']} (5회 승: {actual['f5_winner']})"

            w_icon = "🎯 적중" if settle["is_winner_hit"] else "❌ 미적중"
            ou_icon = "🎯 적중" if settle["is_ou_hit"] else "❌ 미적중"
            f5_w_icon = "🎯 적중" if settle["is_f5_winner_hit"] else "❌ 미적중"
            f5_ou_icon = "🎯 적중" if settle["is_f5_ou_hit"] else "❌ 미적중"

            lines.append(f"**📌 {match_name}**")
            lines.append(f"  • {score_str}")
            lines.append(f"  • 승패 예측: `{pred.get('pred_winner')}` ➔ **{w_icon}**")
            lines.append(f"  • 언오버: `{pred.get('pred_ou_pick')} ({pred.get('pred_ou_line')})` ➔ **{ou_icon}**")
            lines.append(f"  • 5이닝 승패: `{pred.get('pred_f5_winner')}` ➔ **{f5_w_icon}** | 5이닝 언오버: `{pred.get('pred_f5_ou_pick')}` ➔ **{f5_ou_icon}**")
            lines.append(f"  • {f5_score_str}\n")

        lines.append("💡 *모든 결과 데이터는 SQLite(`sports_analytics.db`)에 영구 저장되어 DBeaver에서 상세 조회가 가능합니다.*")
        return "\n".join(lines)
