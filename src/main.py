import argparse
import logging
import sys
from datetime import datetime, timezone, timedelta

from .config import GEMINI_API_KEY, DISCORD_WEBHOOK_URL, validate_config
from .collectors.mlb_collector import MLBCollector
from .collectors.kbo_collector import KBOCollector
from .analyzer.gemini_analyzer import GeminiSportsAnalyzer
from .notifier.discord_notifier import DiscordNotifier
from .storage.db_manager import DatabaseManager
from .evaluator.result_evaluator import ResultEvaluator

# Windows 콘솔 인코딩(cp949) 대응 utf-8 강제 설정
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))

def run_pipeline(sport: str = "all", dry_run: bool = False, target_date: str = None):
    """
    스포츠 데이터 수집 -> 어제 경기 5이닝/풀이닝 결과 정산 -> 오늘 분석 & 5이닝 예측 -> 디스코드 전송 & SQLite 영구 누적
    """
    logger.info("=" * 60)
    logger.info(f"🚀 스포츠 자동 분석 & 정산 파이프라인 시작 (종목: {sport}, Dry-run: {dry_run})")
    logger.info("=" * 60)

    # 1. 설정 검증
    validate_config(require_webhook=(not dry_run))

    db_manager = DatabaseManager()
    evaluator = ResultEvaluator(db_manager)
    analyzer = GeminiSportsAnalyzer(api_key=GEMINI_API_KEY)
    notifier = DiscordNotifier(webhook_url=DISCORD_WEBHOOK_URL) if not dry_run else None

    now_kst = datetime.now(KST)
    today_default_str = target_date or now_kst.strftime("%Y-%m-%d")

    # 어제 날짜 계산
    if target_date:
        try:
            cur_dt = datetime.strptime(target_date, "%Y-%m-%d")
            yesterday_str = (cur_dt - timedelta(days=1)).strftime("%Y-%m-%d")
        except Exception:
            yesterday_str = (now_kst - timedelta(days=1)).strftime("%Y-%m-%d")
    else:
        yesterday_str = (now_kst - timedelta(days=1)).strftime("%Y-%m-%d")

    recent_stats = db_manager.get_recent_stats(days=14)

    # ========================================================
    # 2. MLB 파이프라인
    # ========================================================
    if sport in ["all", "mlb"]:
        logger.info("\n" + "="*20 + " [1] MLB 처리 시작 " + "="*20)
        mlb_collector = MLBCollector()

        # [단계 A] 어제 경기 결과 수집 및 5이닝/풀이닝 적중 정산
        logger.info(f"어제({yesterday_str}) MLB 경기 결과 정산 진행...")
        mlb_actual_results = mlb_collector.fetch_results(target_date=yesterday_str)
        if mlb_actual_results:
            db_manager.save_game_results(yesterday_str, "MLB", mlb_actual_results)
            mlb_settle_summary = evaluator.evaluate_date(yesterday_str, "MLB", mlb_actual_results)
            if mlb_settle_summary:
                settle_md = evaluator.generate_settlement_report_markdown(mlb_settle_summary)
                if dry_run:
                    print("\n[DRY RUN - MLB 어제 정산 리포트]")
                    print(settle_md)
                else:
                    notifier.send_embed(
                        title=f"📈 [MLB] 어제 경기 예측 결과 정산 ({yesterday_str})",
                        description=settle_md,
                        color=0x2ECC71  # Emerald Green
                    )
        else:
            logger.info(f"어제({yesterday_str}) 완료된 MLB 경기 결과가 없습니다.")

        # [단계 B] 오늘 경기 데이터 수집 및 5이닝/풀이닝 분석
        mlb_games = mlb_collector.fetch_schedule(target_date=target_date)
        if mlb_games:
            mlb_report, mlb_preds = analyzer.analyze_games(
                league="MLB",
                games_data=mlb_games,
                recent_stats=recent_stats
            )
            # SQLite DB에 예측 데이터 영구 저장 (DBeaver에서 즉시 확인 가능)
            if mlb_preds:
                db_manager.save_predictions(today_default_str, "MLB", mlb_preds)
                logger.info(f"💾 MLB {len(mlb_preds)}개 경기 예측 데이터 SQLite 저장 완료")

            if dry_run:
                print("\n[DRY RUN - MLB 오늘 분석 리포트]")
                print(mlb_report)
            else:
                notifier.send_embed(
                    title=f"⚾ [MLB] 데일리 경기 분석 & 추천 픽 ({today_default_str})",
                    description=mlb_report,
                    color=0x005A9C  # MLB Blue
                )
        else:
            logger.info("오늘 분석할 MLB 경기가 없습니다.")
            if not dry_run:
                notifier.send_embed(
                    title=f"⚾ [MLB] 데일리 경기 브리핑 ({today_default_str})",
                    description=f"📊 **오늘({today_default_str})은 예정된 MLB 경기 일정이 없습니다.**",
                    color=0x95A5A6
                )

    # ========================================================
    # 3. KBO 파이프라인
    # ========================================================
    if sport in ["all", "kbo"]:
        logger.info("\n" + "="*20 + " [2] KBO 처리 시작 " + "="*20)
        kbo_collector = KBOCollector()

        # [단계 A] 어제 경기 결과 수집 및 5이닝/풀이닝 적중 정산
        logger.info(f"어제({yesterday_str}) KBO 경기 결과 정산 진행...")
        kbo_actual_results = kbo_collector.fetch_results(target_date=yesterday_str)
        if kbo_actual_results:
            db_manager.save_game_results(yesterday_str, "KBO", kbo_actual_results)
            kbo_settle_summary = evaluator.evaluate_date(yesterday_str, "KBO", kbo_actual_results)
            if kbo_settle_summary:
                kbo_settle_md = evaluator.generate_settlement_report_markdown(kbo_settle_summary)
                if dry_run:
                    print("\n[DRY RUN - KBO 어제 정산 리포트]")
                    print(kbo_settle_md)
                else:
                    notifier.send_embed(
                        title=f"📈 [KBO] 어제 경기 예측 결과 정산 ({yesterday_str})",
                        description=kbo_settle_md,
                        color=0x2ECC71  # Emerald Green
                    )
        else:
            logger.info(f"어제({yesterday_str}) 완료된 KBO 경기 결과가 없습니다.")

        # [단계 B] 오늘 경기 데이터 수집 및 5이닝/풀이닝 분석
        kbo_games = kbo_collector.fetch_schedule(target_date=target_date)
        if kbo_games:
            kbo_report, kbo_preds = analyzer.analyze_games(
                league="KBO",
                games_data=kbo_games,
                recent_stats=recent_stats
            )
            # SQLite DB에 예측 데이터 영구 저장 (DBeaver에서 즉시 확인 가능)
            if kbo_preds:
                db_manager.save_predictions(today_default_str, "KBO", kbo_preds)
                logger.info(f"💾 KBO {len(kbo_preds)}개 경기 예측 데이터 SQLite 저장 완료")

            if dry_run:
                print("\n[DRY RUN - KBO 오늘 분석 리포트]")
                print(kbo_report)
            else:
                notifier.send_embed(
                    title=f"⚾ [KBO] 데일리 경기 분석 & 추천 픽 ({today_default_str})",
                    description=kbo_report,
                    color=0xFF6B00  # KBO Orange
                )
        else:
            logger.info("오늘 분석할 KBO 경기가 없습니다.")
            if not dry_run:
                notifier.send_embed(
                    title=f"⚾ [KBO] 데일리 경기 브리핑 ({today_default_str})",
                    description=(
                        f"📊 **오늘({today_default_str})은 KBO 정규 리그 경기 일정이 없습니다.**\n\n"
                        "• **참고**: 매주 월요일은 KBO 공식 정기 휴식일이거나, 우천 취소 등으로 경기가 배정되지 않은 날입니다.\n"
                        "• 내일(화요일) 경기부터 정상 분석 브리핑이 제공됩니다!"
                    ),
                    color=0x95A5A6
                )

    logger.info("\n" + "=" * 60)
    logger.info("✅ 모든 스포츠 분석 & 정산 파이프라인 실행 완료 (SQLite 저장 완료)")
    logger.info("=" * 60)


def main():
    parser = argparse.ArgumentParser(description="스포츠 자동 분석 및 디스코드 데일리 브리핑 파이프라인")
    parser.add_argument(
        "--sport",
        choices=["all", "mlb", "kbo"],
        default="all",
        help="분석할 스포츠 종목 선택 (all, mlb, kbo - 기본값: all)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="디스코드 전송 없이 터미널에 분석 결과만 출력 (로컬 테스트용)"
    )
    parser.add_argument(
        "--date",
        type=str,
        default=None,
        help="분석 대상 날짜 지정 (YYYY-MM-DD 또는 YYYYMMDD, 미입력 시 오늘)"
    )

    args = parser.parse_args()
    run_pipeline(sport=args.sport, dry_run=args.dry_run, target_date=args.date)


if __name__ == "__main__":
    main()
