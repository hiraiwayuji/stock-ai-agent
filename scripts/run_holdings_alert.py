"""
保有銘柄 含み損益アラート — 各ユーザーの portfolio を走査し、
閾値以上の含み損益が出ている銘柄をその本人の個人LINEに通知する。

使い方:
    python scripts/run_holdings_alert.py
    python scripts/run_holdings_alert.py --threshold 5.0
    python scripts/run_holdings_alert.py --user Uxxx --force
    python scripts/run_holdings_alert.py --dry-run
    python scripts/run_holdings_alert.py --to Uxxx --force
"""
from __future__ import annotations

import argparse
import dataclasses
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Windows cp932 stdout を UTF-8 に切り替え
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

from scripts.stock_checker import fetch_quote
from src.ai.commentator import comment
from src.db.supabase_client import get_client
from src.line.client import push_text
from linebot.v3.messaging.exceptions import ApiException


def get_all_portfolios() -> list[dict]:
    """portfolio テーブル全行取得"""
    client = get_client()
    res = client.table("portfolio").select("user_id, ticker, qty, avg_cost").execute()
    return res.data or []


def group_by_user(rows: list[dict]) -> dict[str, list[dict]]:
    """user_id ごとに保有リストを束ねる"""
    out: dict[str, list[dict]] = {}
    for r in rows:
        uid = r.get("user_id")
        if not uid:
            continue
        out.setdefault(uid, []).append(r)
    return out


def detect_holdings_alerts(positions: list[dict], threshold: float) -> list[dict]:
    """
    各ポジションの現在価格を取得し、|含み損益率| >= threshold のものを返す。
    返り値: list of {ticker, qty, avg_cost, current, invested, market_value, unrealized, pct}
    """
    triggered = []
    for p in positions:
        ticker = p.get("ticker")
        qty = float(p.get("qty") or 0)
        avg_cost = float(p.get("avg_cost") or 0)
        if not ticker or qty <= 0 or avg_cost <= 0:
            continue
        q = fetch_quote(ticker)
        if q is None:
            print(f"[WARN] {ticker} 価格取得失敗", file=sys.stderr)
            continue
        current = q.price
        invested = qty * avg_cost
        market_value = qty * current
        unrealized = market_value - invested
        pct = unrealized / invested * 100 if invested else 0.0
        if abs(pct) >= threshold:
            triggered.append({
                "ticker": ticker,
                "qty": qty,
                "avg_cost": avg_cost,
                "current": current,
                "currency": q.currency,
                "invested": invested,
                "market_value": market_value,
                "unrealized": unrealized,
                "pct": pct,
                "_quote": q,
            })
    return triggered


def build_message(triggered: list[dict], commentary: str) -> str:
    """メッセージ組み立て"""
    lines = ["📊 保有銘柄アラート", ""]
    for t in triggered:
        arrow = "📈" if t["pct"] > 0 else "📉"
        lines.append(
            f"{arrow} {t['ticker']}: {t['pct']:+.2f}% "
            f"(取得 {t['avg_cost']:.2f} → 現在 {t['current']:.2f} {t['currency']})"
        )
        lines.append(
            f"   評価額 {t['market_value']:,.0f} / 含み{'益' if t['unrealized'] >= 0 else '損'} {t['unrealized']:+,.0f}"
        )
    lines.append("")
    lines.append("--- 🎤 トレーナーから ---")
    lines.append(commentary)
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="保有銘柄 含み損益アラート → 個人LINE push")
    parser.add_argument("--user", dest="user_id", type=str, default=None, help="対象ユーザーID（省略時は全ユーザー）")
    parser.add_argument("--to", dest="to_id", type=str, default=None, help="送信先上書き（テスト用）")
    parser.add_argument("--threshold", type=float, default=3.0, help="アラート閾値 %% (default 3.0)")
    parser.add_argument("--force", action="store_true", help="閾値未満でも強制送信")
    parser.add_argument("--dry-run", action="store_true", help="送信せず stdout のみ")
    args = parser.parse_args()

    if not os.environ.get("OPENAI_API_KEY"):
        print("❌ OPENAI_API_KEY 未設定", file=sys.stderr)
        return 2

    # 対象ユーザーの portfolio 取得
    if args.user_id:
        client = get_client()
        res = client.table("portfolio").select("user_id, ticker, qty, avg_cost").eq("user_id", args.user_id).execute()
        rows = res.data or []
    else:
        rows = get_all_portfolios()

    if not rows:
        print("✅ portfolio が空。処理対象なし。")
        return 0

    grouped = group_by_user(rows)
    print(f"対象ユーザー数: {len(grouped)}")

    sent_count = 0
    for user_id, positions in grouped.items():
        print(f"\n--- user={user_id[:10]}... 保有{len(positions)}件 ---")

        triggered = detect_holdings_alerts(positions, args.threshold)
        is_triggered = bool(triggered) or args.force

        if not is_triggered:
            print(f"  ✅ アラートなし（閾値 ±{args.threshold}% 未満）")
            continue

        if not triggered:
            # --force でも triggered が空なら skip（解説するネタがない）
            # この場合は qty/avg_cost ベースで全件並べる
            print(f"  ℹ️ 閾値未満だが --force のため全件解説")
            triggered = detect_holdings_alerts(positions, threshold=0.0)
            if not triggered:
                print(f"  ⚠️ 価格取得失敗で送信スキップ")
                continue

        # 解説生成（commentator は Quote リストを期待）
        ai_quotes = [dataclasses.asdict(t["_quote"]) for t in triggered]
        try:
            commentary = comment(ai_quotes)
        except Exception as e:
            print(f"  ❌ 解説生成失敗: {e}", file=sys.stderr)
            commentary = "（解説生成に失敗しました）"

        body = build_message(triggered, commentary)
        target = args.to_id or user_id

        if args.dry_run:
            print(f"  --- DRY RUN to={target[:10]}... ---")
            print("  " + body.replace("\n", "\n  "))
            continue

        try:
            push_text(target, body)
            print(f"  📤 送信成功 to={target[:10]}... アラート{len(triggered)}件")
            sent_count += 1
        except ApiException as e:
            status = getattr(e, "status", None)
            err_map = {
                401: "アクセストークン無効",
                403: "Bot を友だち未登録",
                400: "送信先ID不正",
                429: "レート制限",
            }
            msg = err_map.get(status, f"LINE API エラー (status={status})")
            print(f"  ❌ 送信失敗: {msg}", file=sys.stderr)
        except Exception as e:
            print(f"  ❌ 送信失敗（想定外）: {e}", file=sys.stderr)

    print(f"\n完了: {sent_count}人に送信")
    return 0


if __name__ == "__main__":
    sys.exit(main())
