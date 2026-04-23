"""
Stock AI Agent — エントリーポイント
- 朝イチニュース配信 (APScheduler)
- 市場アラート監視ループ
- LINE Webhookはseparate FastAPI server (src/line/webhook.py) で受信
"""
import os
import logging
from dotenv import load_dotenv
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from src.news.fetcher import fetch_today_headlines, format_headlines_for_ai
from src.stock.fetcher import get_indices
from src.stock.technicals import compute_indicators, get_latest_signals
from src.ai.analyst import analyze
from src.line.client import push_text
from src.alerts.monitor import check_market_alert
from src.db.supabase_client import get_client

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

USER_ID = os.environ["LINE_USER_ID"]
MORNING_HOUR = int(os.environ.get("MORNING_NEWS_HOUR", 8))
MORNING_MIN = int(os.environ.get("MORNING_NEWS_MINUTE", 0))
ALERT_INTERVAL = int(os.environ.get("ALERT_INTERVAL_MINUTES", 5))


def job_morning_briefing():
    """朝イチブリーフィング: ニュース+指数+AI分析をLINE送信"""
    log.info("朝イチブリーフィング開始")

    headlines = fetch_today_headlines()
    headline_text = format_headlines_for_ai(headlines)

    indices = get_indices()
    indices_text = "\n".join([f"{k}: {v:.2f}" if v else f"{k}: N/A" for k, v in indices.items()])

    context = f"【主要指数】\n{indices_text}\n\n【本日のニュース】\n{headline_text}"
    analysis = analyze(context)

    message = f"📊 おはようございます！本日の相場ブリーフィングです。\n\n{analysis}\n\n---\n{indices_text}"
    push_text(USER_ID, message)
    log.info("朝イチブリーフィング送信完了")


def job_market_alert():
    """定期アラートチェック"""
    check_market_alert(USER_ID)


if __name__ == "__main__":
    scheduler = BlockingScheduler(timezone="Asia/Tokyo")

    scheduler.add_job(
        job_morning_briefing,
        CronTrigger(hour=MORNING_HOUR, minute=MORNING_MIN, timezone="Asia/Tokyo"),
        id="morning_briefing",
    )
    scheduler.add_job(
        job_market_alert,
        "interval",
        minutes=ALERT_INTERVAL,
        id="market_alert",
    )

    log.info(f"スケジューラ起動 — 朝配信: {MORNING_HOUR:02d}:{MORNING_MIN:02d}, アラート間隔: {ALERT_INTERVAL}分")
    scheduler.start()
