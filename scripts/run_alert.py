"""
市場アラート監視 単発実行スクリプト
GitHub Actions の market_alert.yml から呼ばれる（15分毎）
Divergence Score が高い銘柄もスキャンして通知
"""
import os
import sys
import logging
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from src.alerts.monitor import check_market_alert, check_watchlist_alerts
from src.db.supabase_client import get_client
from src.news.sentiment import compute_divergence, format_divergence_message
from src.news.ticker_news import scan_ticker_news, format_ticker_news_message
from src.stock.earnings_calendar import check_earnings_alerts, format_earnings_message
from src.line.client import push_text

USER_ID = os.environ["LINE_USER_ID"]
DIVERGENCE_THRESHOLD = float(os.environ.get("DIVERGENCE_THRESHOLD", "2.0"))
SCAN_TICKERS = os.environ.get("SCAN_TICKERS", "").split(",")


def scan_divergence():
    """環境変数で指定した銘柄のDivergenceをスキャン"""
    for ticker in SCAN_TICKERS:
        ticker = ticker.strip()
        if not ticker:
            continue
        try:
            result = compute_divergence(ticker)
            if abs(result.divergence_score) >= DIVERGENCE_THRESHOLD:
                from src.line.client import push_text
                push_text(USER_ID, format_divergence_message(result))
                log.info(f"divergence alert sent: {ticker} score={result.divergence_score}")
        except Exception as e:
            log.warning(f"divergence scan {ticker}: {e}")


def main():
    log.info("アラートチェック開始")

    # 市場レベルアラート（VIX + 日経レジーム）
    check_market_alert(USER_ID)

    # Supabase から全ユーザーの watchlist を取得してアラートチェック
    try:
        client = get_client()
        rows = client.table("watchlist").select("user_id, ticker, alert_price, alert_pct").execute()
        # user_id でグループ化
        from itertools import groupby
        data = sorted(rows.data or [], key=lambda x: x["user_id"])
        for uid, items in groupby(data, key=lambda x: x["user_id"]):
            check_watchlist_alerts(uid, list(items))
    except Exception as e:
        log.warning(f"watchlist check failed: {e}")

    # Divergence スキャン
    scan_divergence()

    # 決算アラート（朝9:00 の初回のみ実行: 分が00〜14 の場合）
    from datetime import datetime, timezone, timedelta
    jst_now = datetime.now(timezone(timedelta(hours=9)))
    if jst_now.hour == 9 and jst_now.minute < 15:
        try:
            client = get_client()
            wl_rows  = client.table("watchlist").select("user_id, ticker").execute().data or []
            hld_rows = client.table("portfolio").select("user_id, ticker").execute().data or []
            from itertools import groupby
            users = set(r["user_id"] for r in wl_rows + hld_rows)
            for uid in users:
                wl  = [r["ticker"] for r in wl_rows  if r["user_id"] == uid]
                hld = [r["ticker"] for r in hld_rows if r["user_id"] == uid]
                alerts = check_earnings_alerts(wl, hld)
                msg = format_earnings_message(alerts)
                if msg:
                    push_text(uid, msg)
        except Exception as e:
            log.warning(f"earnings check: {e}")

    # 銘柄ニュースアラート（1時間に1回: 分が00〜14）
    if jst_now.minute < 15:
        try:
            client   = get_client()
            all_tickers = list({
                r["ticker"] for r in
                (client.table("watchlist").select("ticker").execute().data or []) +
                (client.table("portfolio").select("ticker").execute().data or [])
            })
            if all_tickers:
                news_items = scan_ticker_news(all_tickers, importance_threshold=0.7)
                msg = format_ticker_news_message(news_items)
                if msg:
                    push_text(USER_ID, msg)
        except Exception as e:
            log.warning(f"ticker_news scan: {e}")

    log.info("アラートチェック完了")


if __name__ == "__main__":
    main()
