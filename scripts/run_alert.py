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

    log.info("アラートチェック完了")


if __name__ == "__main__":
    main()
