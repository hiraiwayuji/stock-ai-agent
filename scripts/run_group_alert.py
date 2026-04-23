"""
グループ重大アラート実行スクリプト
"""
import os
import sys
import logging
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from src.alerts.group_alert import check_group_alerts
from src.line.client import push_text
from src.db.supabase_client import get_client

def main():
    log.info("グループ重大アラートチェック開始")
    alerts = check_group_alerts()

    if not alerts:
        log.info("アラート対象グループなし")
        return

    client = get_client()
    for line_group_id, message, alert_types in alerts:
        try:
            push_text(line_group_id, message)
            log.info(f"送信完了: {line_group_id}")
            # alert_historyに記録
            for alert_type in alert_types:
                client.table("alert_history").insert({
                    "user_id": line_group_id,
                    "ticker": None,
                    "alert_type": alert_type,
                    "message": message[:200]
                }).execute()
        except Exception as e:
            log.warning(f"送信エラー: {line_group_id} - {e}")

    log.info("グループ重大アラートチェック完了")

if __name__ == "__main__":
    main()
