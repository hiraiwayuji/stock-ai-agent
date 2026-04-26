from __future__ import annotations

import argparse
import dataclasses
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Windows cp932 stdout を UTF-8 に切り替え（絵文字出力対応）
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from linebot.v3.messaging.exceptions import ApiException

from src.ai.commentator import comment
from src.db.supabase_client import get_client
from src.line.client import push_text
from scripts.stock_checker import DEFAULT_TICKERS, Quote, fetch_quote, format_quote_line


def detect_alerts(quotes: list[Quote], threshold: float) -> list[str]:
    """絶対変動率が threshold% 以上の銘柄のアラート文を返す。"""
    alerts: list[str] = []
    for q in quotes:
        if abs(q.change_pct) >= threshold:
            arrow = "📈" if q.change_pct > 0 else "📉"
            alerts.append(
                f"{arrow} {q.ticker}: {q.change_pct:+.2f}% "
                f"({q.price:,.2f} {q.currency})"
            )
    return alerts


def lookup_first_group() -> tuple[str | None, str | None]:
    """
    Supabase から line_group_id が設定されているグループを取得。
    seed の DEMO グループ (line_group_id が 'C' で始まらない) は除外する。
    新しく登録されたグループを優先するため created_at DESC 順。
    """
    client = get_client()
    res = (
        client.table("groups")
        .select("name, line_group_id, created_at")
        .not_.is_("line_group_id", "null")
        .order("created_at", desc=True)
        .limit(10)
        .execute()
    )
    rows = res.data or []
    # LINE group_id は 'C' で始まる33文字。seed の 'LINE_GROUP_DEMO' 等は除外
    for row in rows:
        gid = row.get("line_group_id") or ""
        if gid.startswith("C") and len(gid) == 33:
            return row.get("name"), gid
    return None, None


def build_message(alerts: list[str], quotes: list[Quote], commentary: str) -> str:
    """LINE 送信用メッセージを組み立てる。"""
    header = "🚨 株価アラート" if alerts else "📊 株価チェック（テスト送信）"
    alert_body = "\n".join(alerts) if alerts else "（閾値未満・force送信）"
    table_body = "\n".join(format_quote_line(q) for q in quotes)
    return (
        f"{header}\n\n"
        f"--- アラート検知リスト ---\n"
        f"{alert_body}\n\n"
        f"--- 詳細（表） ---\n"
        f"{table_body}\n\n"
        f"--- 敏腕トレーナー解説 ---\n"
        f"{commentary}"
    )


def get_api_status(exc: ApiException) -> int | None:
    """LINE SDK の例外から HTTP ステータスを取り出す。"""
    return getattr(exc, "status", None)


def main() -> int:
    parser = argparse.ArgumentParser(description="株価アラート検知 + 解説AI グループpush")
    parser.add_argument("tickers", nargs="*", default=DEFAULT_TICKERS)
    parser.add_argument("--to", dest="to_id", type=str, default=None)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--threshold", type=float, default=3.0)
    args = parser.parse_args()

    tickers = args.tickers or DEFAULT_TICKERS
    quotes: list[Quote] = [
        q for q in (fetch_quote(t) for t in tickers) if q is not None
    ]
    if not quotes:
        print("株価データを取得できませんでした。", file=sys.stderr)
        return 1

    alerts = detect_alerts(quotes, args.threshold)
    if not alerts and not args.force:
        print(f"✅ アラートなし（閾値 ±{args.threshold}% 未満）")
        return 0

    ai_quotes = [dataclasses.asdict(q) for q in quotes]
    if not os.environ.get("OPENAI_API_KEY"):
        print("❌ OPENAI_API_KEY 未設定", file=sys.stderr)
        return 2
    try:
        commentary = comment(ai_quotes)
    except Exception as e:
        print(f"❌ 解説生成失敗: {e}", file=sys.stderr)
        return 2

    line_body = build_message(alerts, quotes, commentary)

    target = args.to_id
    group_name = None
    if not target:
        group_name, target = lookup_first_group()
        if not target:
            print(
                "❌ 送信先グループが見つかりません。/register でグループ登録するか "
                "--to で指定してください",
                file=sys.stderr,
            )
            return 2

    if args.dry_run:
        print("--- DRY RUN ---")
        print(f"送信先: {target[:12]}... ({group_name or 'manual'})")
        print(line_body)
        return 0

    try:
        push_text(target, line_body)
        print(f"📤 送信成功: to={target[:12]}... ({group_name or 'manual'})")
        print(f"  アラート{len(alerts)}件, 銘柄{len(quotes)}件")
    except ApiException as e:
        status = get_api_status(e)
        err_map = {
            401: "アクセストークン無効",
            403: "Bot がグループ未招待 or 友だち未登録",
            400: "送信先ID不正",
            429: "レート制限",
        }
        msg = err_map.get(status, f"LINE API エラー (status={status})")
        print(f"❌ 送信失敗: {msg}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
