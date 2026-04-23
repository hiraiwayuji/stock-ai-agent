"""
週次目標進捗レポート
毎週金曜17:00 JST に今月・今年の進捗 + AI一言コメントをLINE送信
"""
import os, sys, logging
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from src.stock.goal_tracker import calc_goal_progress, format_goal_message
from src.line.flex_builder import build_goal_flex
from src.line.client import push_text, push_flex
from src.ai.analyst import analyze

JST = timezone(timedelta(hours=9))
USER_ID = os.environ["LINE_USER_ID"]


def main():
    today = datetime.now(JST)
    year, month = today.year, today.month
    log.info(f"週次目標レポート開始 {year}-{month:02d}")

    reports = []

    # 月次目標
    mp = calc_goal_progress(USER_ID, "monthly", year, month)
    if mp:
        push_flex(USER_ID, f"{year}年{month}月 目標進捗", build_goal_flex(mp))
        reports.append(format_goal_message(mp))
        log.info(f"月次: {mp.achievement_pct:.1f}%")

    # 年間目標
    yp = calc_goal_progress(USER_ID, "yearly", year)
    if yp:
        push_flex(USER_ID, f"{year}年間 目標進捗", build_goal_flex(yp))
        reports.append(format_goal_message(yp))
        log.info(f"年間: {yp.achievement_pct:.1f}%")

    if not reports:
        push_text(USER_ID, "目標が未設定です。\n/goal set monthly <金額> で設定してください。")
        return

    # AI 一言コメント
    context = "\n\n".join(reports)
    comment = analyze(context, "この週次の投資目標進捗に対して、来週の作戦と一言激励をください（100字以内）")
    push_text(USER_ID, f"🤖 AI一言:\n{comment}")
    log.info("送信完了")


if __name__ == "__main__":
    main()
