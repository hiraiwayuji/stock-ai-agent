"""
週次ウォッチリスト最適化スクリプト
GitHub Actions の weekly_optimize.yml から実行
"""
import os
import sys
import logging
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from src.stock.watchlist_optimizer import optimize_watchlist, audit_watchlist, format_optimize_message
from src.stock.fetcher import get_indices
from src.db.supabase_client import get_watchlist
from src.ai.analyst import analyze
from src.line.client import push_text

USER_ID   = os.environ["LINE_USER_ID"]
UNIVERSE  = os.environ.get("SCREEN_UNIVERSE", "").split(",")
TOP_N     = int(os.environ.get("OPTIMIZE_TOP_N", "5"))


def main():
    log.info("週次ウォッチリスト最適化開始")

    # VIX 取得
    vix = None
    try:
        indices = get_indices()
        vix = indices.get("VIX")
        log.info(f"VIX: {vix}")
    except Exception:
        pass

    # 上位銘柄スコアリング
    top_stocks = optimize_watchlist(UNIVERSE or None, top_n=TOP_N, vix=vix)
    optimize_msg = format_optimize_message(top_stocks)

    # 既存ウォッチリストの監査
    try:
        current_wl = [item["ticker"] for item in get_watchlist(USER_ID)]
        if current_wl:
            audited    = audit_watchlist(current_wl)
            weak       = [s for s in audited if s.recommendation == "除外推奨"]
            audit_note = ""
            if weak:
                audit_note = "\n\n⚠️ 除外推奨銘柄: " + ", ".join(s.ticker for s in weak)
        else:
            audit_note = ""
    except Exception as e:
        log.warning(f"audit failed: {e}")
        audit_note = ""

    # AI による総評
    ai_summary = analyze(
        optimize_msg,
        "このウォッチリスト最適化結果に対して、今週の投資戦略の総評と注意点を教えてください"
    )

    message = (
        f"📅 週次ウォッチリスト最適化レポート\n\n"
        f"{optimize_msg}"
        f"{audit_note}\n\n"
        f"🤖 AI総評:\n{ai_summary}"
    )
    push_text(USER_ID, message)
    log.info("送信完了")


if __name__ == "__main__":
    main()
