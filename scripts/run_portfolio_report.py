"""
日次ポートフォリオレポート
毎日15:30 JST（東京市場クローズ後）に実行
全ユーザーの損益サマリー + AI改善提案をLINE送信
"""
import os
import sys
import logging
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from src.stock.portfolio_analyzer import analyze_portfolio, format_portfolio_message
from src.ai.analyst import analyze
from src.line.client import push_text
from src.db.supabase_client import get_client


def get_all_user_ids() -> list[str]:
    """ポートフォリオを持つ全ユーザーIDを取得"""
    client = get_client()
    rows = client.table("portfolio").select("user_id").execute().data or []
    return list({r["user_id"] for r in rows})


def report_for_user(user_id: str) -> None:
    summary = analyze_portfolio(user_id)
    if not summary.positions:
        return

    port_text = format_portfolio_message(summary)

    # 損益が大きく動いた日（±2%以上）はAI提案も送付
    if abs(summary.daily_pnl) >= abs(summary.total_value) * 0.02:
        advice = analyze(
            port_text,
            "本日の相場変動を踏まえ、このポートフォリオのリスク管理と明日以降の戦略を提案してください"
        )
        message = f"{port_text}\n\n🤖 AI戦略提案:\n{advice}"
    else:
        message = port_text

    push_text(user_id, f"📊 本日のポートフォリオレポート\n\n{message}")
    log.info(f"report sent: user={user_id} pnl={summary.daily_pnl:+,.0f}")


def main():
    log.info("日次ポートフォリオレポート開始")
    user_ids = get_all_user_ids()
    if not user_ids:
        # 環境変数にフォールバック（単一ユーザー運用）
        uid = os.environ.get("LINE_USER_ID")
        if uid:
            user_ids = [uid]

    for uid in user_ids:
        try:
            report_for_user(uid)
        except Exception as e:
            log.error(f"report failed for {uid}: {e}")

    log.info("日次ポートフォリオレポート完了")


if __name__ == "__main__":
    main()
