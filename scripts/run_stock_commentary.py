import argparse
import dataclasses
import os
import sys

# src パッケージを見つけるためにプロジェクトルートをパスに追加
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from scripts.stock_checker import (
    DEFAULT_TICKERS,
    Quote as StockQuote,
    fetch_quote,
    print_table,
)
from src.ai.commentator import comment, Quote as AIQuote
from src.line.client import push_text
from linebot.v3.messaging.exceptions import ApiException


def main() -> int:
    parser = argparse.ArgumentParser(description="株価取得＋AI解説スクリプト")
    parser.add_argument(
        "tickers",
        nargs="*",
        default=DEFAULT_TICKERS,
        help="ティッカー (例: NVDA IONQ ^GSPC)",
    )
    parser.add_argument("--no-table", action="store_true", help="テーブル表示を抑制し、解説文だけ出す")
    parser.add_argument("--model", type=str, default=None, help="OpenAIモデル上書き")
    parser.add_argument("--line", action="store_true", help="解説をLINEに送信")
    parser.add_argument("--to", dest="to_id", type=str, help="送信先ID上書き（.env LINE_USER_ID から）")
    args = parser.parse_args()

    if not os.environ.get("OPENAI_API_KEY"):
        print("OPENAI_API_KEY が設定されていません。環境変数または .env を確認してください。", file=sys.stderr)
        return 2

    tickers = args.tickers or DEFAULT_TICKERS
    quotes: list[StockQuote] = []
    
    for ticker in tickers:
        q = fetch_quote(ticker)
        if q is not None:
            quotes.append(q)

    if not quotes:
        print(
            "株価データを取得できませんでした。yfinance の依存関係、ネットワーク、"
            "キャッシュディレクトリ権限を確認してください。",
            file=sys.stderr,
        )
        return 1

    if not args.no_table:
        print_table(quotes)

    # dataclass を dict (AIQuote) に変換
    ai_quotes: list[AIQuote] = [dataclasses.asdict(q) for q in quotes]  # type: ignore

    try:
        comment_text = comment(ai_quotes, model=args.model)
    except Exception as exc:
        print(f"OpenAI API エラー: {exc}", file=sys.stderr)
        return 2

    if not args.no_table:
        print("---")
    print(comment_text)

    if args.line:
        target = args.to_id or os.environ.get("LINE_USER_ID")
        if not target:
            print(
                "❌ エラー: --line 指定時は .env の LINE_USER_ID または --to が必要です",
                file=sys.stderr,
            )
            return 2

        from scripts.stock_checker import format_quote_line
        table_lines = [format_quote_line(q) for q in quotes]
        table_str = "\n".join(table_lines)
        line_body = f"📈 株価チェック\n\n{table_str}\n\n---\n{comment_text}"

        try:
            push_text(target, line_body)
            print(f"📤 LINE送信成功: to={target[:10]}...")
        except ApiException as e:
            status = getattr(e, "status", None)
            err_map = {
                401: "アクセストークン無効。Developers Console で再発行",
                403: "送信先が Bot を友だち未登録（個人宛）or Bot 未招待（グループ宛）",
                400: "送信先ID不正。user_id/group_id を確認",
                429: "LINEレート制限",
            }
            msg = err_map.get(status, f"LINE API エラー (status={status}): {getattr(e, 'reason', '')}")
            print(f"❌ LINE送信失敗: {msg}", file=sys.stderr)
            return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
