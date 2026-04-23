"""
朝イチブリーフィング — Step10 強化版
AI 総合投資デイリーレポートを生成して LINE に複数メッセージで送信
GitHub Actions の morning_briefing.yml から呼ばれる
"""
import os
import sys
import logging
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from src.ai.daily_report import build_daily_report, format_daily_report_messages
from src.line.client import push_text

USER_ID  = os.environ["LINE_USER_ID"]
UNIVERSE = [t.strip() for t in os.environ.get("SCREEN_UNIVERSE", "").split(",") if t.strip()]


def main():
    log.info("朝イチデイリーレポート生成開始")

    report = build_daily_report(USER_ID, scan_universe=UNIVERSE or None)
    messages = format_daily_report_messages(report)

    for i, msg in enumerate(messages, 1):
        push_text(USER_ID, msg)
        log.info(f"メッセージ {i}/{len(messages)} 送信完了")

    log.info("朝イチデイリーレポート完了")


if __name__ == "__main__":
    main()
