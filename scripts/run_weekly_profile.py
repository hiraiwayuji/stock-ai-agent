"""
週次プロファイルPushスクリプト
"""
import os
import sys
import logging
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from src.db.supabase_client import get_client
from src.ai.personal_profile import analyze_user_profile, save_profile_snapshot
from src.line.client import push_text
from src.ai.analyst import analyze


def _format_mmdd(dt: datetime) -> str:
    return f"{dt.month}/{dt.day}"


def main():
    log.info("週次プロファイルPush開始")
    client = get_client()
    
    # Supabase から全ユーザーの user_id を収集
    user_ids = set()
    for table in ["portfolio", "trade_history", "watchlist"]:
        try:
            res = client.table(table).select("user_id").execute()
            if res.data:
                for row in res.data:
                    user_ids.add(row["user_id"])
        except Exception as e:
            log.warning(f"Error fetching from {table}: {e}")
            
    if not user_ids:
        log.info("対象ユーザーなし")
        return
        
    JST = timezone(timedelta(hours=9))
    now = datetime.now(JST)
    for uid in user_ids:
        try:
            curr_p = analyze_user_profile(uid)
            prev_res = (
                client.table("user_insights")
                .select("payload, generated_at")
                .eq("user_id", uid)
                .eq("insight_type", "weekly_profile")
                .order("generated_at", desc=True)
                .limit(1)
                .execute()
            )
             
            if not prev_res.data:
                msg = f"📈 あなたの初回プロファイルが作成されました\n\n/profile で現状の分析結果を確認できます。\n来週からここに1週間の成長記録が届きます！"
                push_text(uid, msg)
                save_profile_snapshot(curr_p)
                log.info(f"初回送信完了: {uid}")
                continue
                 
            prev_row = prev_res.data[0]
            prev_p = prev_row["payload"]
            prev_generated_at = datetime.fromisoformat(prev_row["generated_at"])
            date_str = f"{_format_mmdd(prev_generated_at)} - {_format_mmdd(now)}"
             
            wr_diff = curr_p.win_rate - prev_p.get("win_rate", 0)
            pnl_diff = curr_p.avg_pnl - prev_p.get("avg_pnl", 0)
             
            lines = [
                f"📈 今週のあなたの成長ログ ({date_str})",
                f"比較基準: 前回スナップショット {prev_generated_at.strftime('%Y-%m-%d %H:%M')}",
                "",
                "▼ 基本指標の変化",
                f"勝率: {prev_p.get('win_rate', 0):.1f}% → {curr_p.win_rate:.1f}% ({wr_diff:+.1f}pt)",
                f"平均損益: ¥{prev_p.get('avg_pnl', 0):+,.0f} → ¥{curr_p.avg_pnl:+,.0f} (¥{pnl_diff:+,.0f})",
                f"取引数累計: {prev_p.get('total_trades', 0)} → {curr_p.total_trades}"
            ]
            
            context = "\n".join(lines)
            advice = analyze(context, "この1週間のユーザーの投資成績の変化について、AI秘書として励ましと簡潔なアドバイスを1〜2文で出力してください。")
            
            hold_diff = curr_p.avg_hold_days - prev_p.get("avg_hold_days", 0)
            
            lines.extend([
                "",
                "▼ 今週の気付き",
                f"・勝率が {curr_p.win_rate:.1f}% に{'上昇' if wr_diff >= 0 else '低下'}しました",
                f"・平均保有日数が {curr_p.avg_hold_days:.1f}日 になりました (変化: {hold_diff:+.1f}日)",
                "",
                "🤖 AI秘書からのひと言",
                advice
            ])
            
            push_text(uid, "\n".join(lines)[:5000])
            save_profile_snapshot(curr_p)
            log.info(f"週次送信完了: {uid}")
            
        except Exception as e:
            log.warning(f"Error processing user {uid}: {e}")

    log.info("週次プロファイルPush完了")

if __name__ == "__main__":
    main()
