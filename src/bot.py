import os
import sys
import logging
import asyncio
from datetime import datetime, timezone, timedelta
import discord
from discord.ext import commands

from .config import GEMINI_API_KEY, DISCORD_BOT_TOKEN, DISCORD_WEBHOOK_URL
from .main import run_pipeline
from .storage.db_manager import DatabaseManager
from .evaluator.result_evaluator import ResultEvaluator
from .collectors.mlb_collector import MLBCollector
from .collectors.kbo_collector import KBOCollector

# Windows 콘솔 인코딩 대응
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))

# 디스코드 봇 클라이언트 초기화 (메시지 수신 권한 활성화)
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

db_manager = DatabaseManager()
evaluator = ResultEvaluator(db_manager)


@bot.event
async def on_ready():
    logger.info("=" * 50)
    logger.info(f"🤖 디스코드 실시간 명령 봇 로그인 완료: {bot.user} (ID: {bot.user.id})")
    logger.info("명령어 대기 중: !도움말, !분석, !mlb, !kbo, !정산, !통계")
    logger.info("=" * 50)
    await bot.change_presence(activity=None)


@bot.command(name="도움말", aliases=["help"])
async def cmd_help(ctx):
    """사용 가능한 명령어 안내"""
    embed = discord.Embed(
        title="⚾ 스포츠 자동 분석 & 정산 봇 명령어 안내",
        description="채널에 아래 명령어를 입력하시면 즉시 실시간 분석 및 통계를 받아보실 수 있습니다.",
        color=0x3498DB
    )
    embed.add_field(name="`!분석` 또는 `!all`", value="당일 MLB + KBO 전체 경기 분석 & 5이닝 추천 픽 발송", inline=False)
    embed.add_field(name="`!mlb`", value="당일 MLB 미국 야구 분석 및 5이닝 픽 즉시 발송", inline=False)
    embed.add_field(name="`!kbo`", value="당일 KBO 한국 야구 분석 및 선발 매치업 즉시 발송", inline=False)
    embed.add_field(name="`!정산`", value="어제 추천 픽의 최종 결과 및 세부 적중률 성적표 발송", inline=False)
    embed.add_field(name="`!통계`", value="SQLite(`sports_analytics.db`)에 누적된 최근 14일간 종합 성적표 확인", inline=False)
    embed.set_footer(text="Sports Analytics Bot with Gemini Flash")
    await ctx.send(embed=embed)


@bot.command(name="분석", aliases=["all"])
async def cmd_analyze_all(ctx):
    """전체(MLB + KBO) 분석 및 발송"""
    msg = await ctx.send("⏳ **[MLB + KBO]** 실시간 데이터 수집 및 Gemini 분석을 시작합니다. 잠시만 기다려 주세요...")
    try:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, run_pipeline, "all", False, None)
        await msg.edit(content="✅ **[MLB + KBO]** 당일 분석 브리핑 및 어제 정산 카드가 채널에 전송되었습니다!")
    except Exception as e:
        logger.error(f"!분석 실행 오류: {e}")
        await msg.edit(content=f"❌ 분석 실행 중 오류가 발생했습니다: `{e}`")


@bot.command(name="mlb")
async def cmd_analyze_mlb(ctx):
    """MLB 경기만 분석 및 발송"""
    msg = await ctx.send("⏳ **[MLB]** 실시간 데이터 수집 및 선발투수 분석을 시작합니다...")
    try:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, run_pipeline, "mlb", False, None)
        await msg.edit(content="✅ **[MLB]** 분석 카드가 채널에 전송되었습니다!")
    except Exception as e:
        logger.error(f"!mlb 실행 오류: {e}")
        await msg.edit(content=f"❌ MLB 분석 중 오류 발생: `{e}`")


@bot.command(name="kbo")
async def cmd_analyze_kbo(ctx):
    """KBO 경기만 분석 및 발송"""
    msg = await ctx.send("⏳ **[KBO]** 실시간 선발 예고 및 경기 데이터 분석을 시작합니다...")
    try:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, run_pipeline, "kbo", False, None)
        await msg.edit(content="✅ **[KBO]** 분석 카드가 채널에 전송되었습니다!")
    except Exception as e:
        logger.error(f"!kbo 실행 오류: {e}")
        await msg.edit(content=f"❌ KBO 분석 중 오류 발생: `{e}`")


@bot.command(name="정산")
async def cmd_settle(ctx):
    """어제 경기 결과 정산만 실행"""
    now_kst = datetime.now(KST)
    yesterday_str = (now_kst - timedelta(days=1)).strftime("%Y-%m-%d")
    msg = await ctx.send(f"⏳ 어제({yesterday_str}) 경기 결과 정산 및 적중률을 계산하고 있습니다...")

    try:
        mlb_collector = MLBCollector()
        kbo_collector = KBOCollector()

        # MLB 정산
        mlb_res = mlb_collector.fetch_results(yesterday_str)
        if mlb_res:
            db_manager.save_game_results(yesterday_str, "MLB", mlb_res)
            mlb_summary = evaluator.evaluate_date(yesterday_str, "MLB", mlb_res)
            if mlb_summary:
                md = evaluator.generate_settlement_report_markdown(mlb_summary)
                color = evaluator.get_settlement_color(mlb_summary.get("winner_rate", 50.0))
                embed = discord.Embed(title=f"📈 [MLB] {yesterday_str} 적중 정산", description=md, color=color)
                await ctx.send(embed=embed)

        # KBO 정산
        kbo_res = kbo_collector.fetch_results(yesterday_str)
        if kbo_res:
            db_manager.save_game_results(yesterday_str, "KBO", kbo_res)
            kbo_summary = evaluator.evaluate_date(yesterday_str, "KBO", kbo_res)
            if kbo_summary:
                kbo_md = evaluator.generate_settlement_report_markdown(kbo_summary)
                color = evaluator.get_settlement_color(kbo_summary.get("winner_rate", 50.0))
                embed = discord.Embed(title=f"📈 [KBO] {yesterday_str} 적중 정산", description=kbo_md, color=color)
                await ctx.send(embed=embed)

        await msg.edit(content=f"✅ 어제({yesterday_str}) 경기 정산 리포트 조회가 완료되었습니다.")
    except Exception as e:
        logger.error(f"!정산 실행 오류: {e}")
        await msg.edit(content=f"❌ 정산 중 오류 발생: `{e}`")


@bot.command(name="통계")
async def cmd_stats(ctx):
    """SQLite에 누적된 최근 14일간 종합 분석 통계 조회"""
    feedback = db_manager.get_advanced_feedback(days=14)
    if not feedback.get("has_data"):
        await ctx.send("📊 아직 SQLite 데이터베이스에 누적된 정산 데이터가 없습니다. 경기가 진행된 후 자동으로 통계가 누적됩니다.")
        return

    base = feedback["base_stats"]
    high_conf = feedback.get("high_conf", {})
    blown = feedback.get("blown_count", 0)

    embed = discord.Embed(
        title="📊 [최근 14일 모델 누적 성적표 & AI 진단]",
        description=feedback.get("summary_text", ""),
        color=0x9B59B6
    )
    embed.add_field(name="총 정산 경기 수", value=f"**{base['total']}경기**", inline=True)
    embed.add_field(name="풀이닝 승패 적중률", value=f"**{base['winner_rate']}%** ({base['winner_hits']}승)", inline=True)
    embed.add_field(name="⚡ 5이닝 승패 적중률", value=f"**{base['f5_winner_rate']}%** ({base['f5_winner_hits']}승)", inline=True)
    embed.add_field(name="풀이닝 언/오버 적중률", value=f"**{base['ou_rate']}%** ({base['ou_hits']}회)", inline=True)
    embed.add_field(name="⚡ 5이닝 언/오버 적중률", value=f"**{base['f5_ou_rate']}%** ({base['f5_ou_hits']}회)", inline=True)
    
    hc_rate = high_conf.get("high_conf_rate", 0)
    hc_hits = high_conf.get("high_conf_hits", 0)
    hc_total = high_conf.get("high_conf_total", 0)
    embed.add_field(name="🏆 고신뢰도(★4~5) 승률", value=f"**{hc_rate}%** ({hc_hits}/{hc_total})", inline=True)

    if blown > 0:
        embed.add_field(name="⚠️ 불펜 방화 역전패", value=f"{blown}건 발생 (5이닝 선발 우위 추천 유효)", inline=False)

    embed.set_footer(text="DBeaver에서 sports_analytics.db로 직접 상세 SQL 조회가 가능합니다.")
    await ctx.send(embed=embed)


def start_bot():
    if not DISCORD_BOT_TOKEN:
        print("\n" + "=" * 70)
        print("[안내] 디스코드 실시간 명령 봇을 띄우려면 DISCORD_BOT_TOKEN이 필요합니다.")
        print("1. https://discord.com/developers/applications 접속 후 'New Application' 생성")
        print("2. 'Bot' 탭에서 'Reset Token' 클릭 후 토큰 복사")
        print("3. 같은 Bot 탭 아래 'Privileged Gateway Intents'에서 'Message Content Intent' 체크")
        print("4. .env 파일에 DISCORD_BOT_TOKEN=복사한_토큰 입력")
        print("=" * 70 + "\n")
        return

    bot.run(DISCORD_BOT_TOKEN)


if __name__ == "__main__":
    start_bot()
