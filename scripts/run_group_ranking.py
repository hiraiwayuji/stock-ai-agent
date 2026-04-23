"""
月次ランキングの LINE グループ Push スクリプト
"""
import os
import sys
import logging
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

JST = timezone(timedelta(hours=9))


def _prev_month_range(now: datetime | None = None) -> tuple[datetime, datetime, str]:
    """前月の [since, until) 半開区間と表示ラベルを返す。月初1日に呼ぶ前提。"""
    now = now or datetime.now(JST)
    this_month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    last_day_prev = this_month_start - timedelta(seconds=1)
    prev_start = last_day_prev.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    label = f"{prev_start.year}年{prev_start.month}月"
    return prev_start, this_month_start, label

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from src.db.supabase_client import get_client
from src.db.groups import ranking
from src.line.client import push_text

def main():
    log.info("月次ランキングPush開始")
    client = get_client()

    since, until, label = _prev_month_range()
    log.info(f"集計期間: {label} [{since.isoformat()} .. {until.isoformat()})")

    # 全groups取得
    res = client.table("groups").select("*").execute()
    groups = [g for g in (res.data or []) if g.get("line_group_id") is not None]

    for g in groups:
        group_id = g["id"]
        line_group_id = g["line_group_id"]
        group_name = g["name"]

        rows = ranking(group_id, since=since, until=until)
        if not rows:
            log.info(f"スキップ: {group_name} (対象データなし)")
            continue

        medals = ["🥇", "🥈", "🥉"]
        lines = [f"🏆 {group_name} {label}ランキング"]
        for i, r in enumerate(rows[:10]):
            m = medals[i] if i < 3 else f"{i+1}."
            lines.append(
                f"{m} {r['user_id'][:6]}  ¥{r['pnl']:+,.0f}  "
                f"{r['trades']}回 / 勝率{r['winrate']:.0f}%"
            )
        
        message = "\n".join(lines)
        try:
            push_text(line_group_id, message)
            log.info(f"送信完了: {group_name}")
        except Exception as e:
            log.error(f"送信エラー: {group_name} - {e}")
            
    log.info("月次ランキングPush完了")

if __name__ == "__main__":
    main()
