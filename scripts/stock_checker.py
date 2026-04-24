"""
株価チェッカー
指定した銘柄の最新価格と前日比騰落率をターミナルに表示する。

使い方:
    python scripts/stock_checker.py
    python scripts/stock_checker.py NVDA IONQ IBM ^GSPC
    python scripts/stock_checker.py --json
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import sys
from dataclasses import dataclass, asdict

try:
    import yfinance as yf
except ModuleNotFoundError as exc:  # pragma: no cover - import failure path
    yf = None
    YFINANCE_IMPORT_ERROR = exc
else:
    YFINANCE_IMPORT_ERROR = None


DEFAULT_TICKERS = ["NVDA", "IONQ", "IBM", "^GSPC"]


@dataclass
class Quote:
    ticker: str
    name: str
    price: float
    prev_close: float
    change: float
    change_pct: float
    currency: str

    @property
    def arrow(self) -> str:
        if self.change > 0:
            return "▲"
        if self.change < 0:
            return "▼"
        return "-"


def warn(message: str) -> None:
    """標準エラーに警告を出す。"""
    print(f"[WARN] {message}", file=sys.stderr)


def fail_dependency() -> int:
    """依存不足時に案内を出して終了する。"""
    assert YFINANCE_IMPORT_ERROR is not None
    print(
        "yfinance が見つかりません。`pip install -r requirements.txt` "
        "または `venv\\Scripts\\python.exe scripts\\stock_checker.py` を使ってください。",
        file=sys.stderr,
    )
    warn(str(YFINANCE_IMPORT_ERROR))
    return 1


def get_currency(info: object) -> str:
    """fast_info から通貨コードを取り出す。"""
    if isinstance(info, dict):
        return info.get("currency") or "USD"
    return getattr(info, "currency", None) or "USD"


def get_display_name(ticker_obj: "yf.Ticker", ticker: str) -> str:
    """銘柄名を取得し、失敗時はティッカーにフォールバックする。"""
    try:
        with contextlib.redirect_stderr(io.StringIO()):
            raw_info = ticker_obj.info or {}
    except Exception as exc:
        warn(f"{ticker} の銘柄名取得に失敗: {exc}")
        return ticker

    return raw_info.get("shortName") or raw_info.get("longName") or ticker


def fetch_quote(ticker: str) -> Quote | None:
    """yfinance から最新価格と前日終値を取得して Quote を返す。失敗時は None。"""
    if yf is None:
        return None

    try:
        ticker_obj = yf.Ticker(ticker)
        with contextlib.redirect_stderr(io.StringIO()):
            hist = ticker_obj.history(period="5d", auto_adjust=False)
        if hist.empty or len(hist) < 2:
            warn(f"{ticker} の株価データが不足しています。")
            return None

        price = float(hist["Close"].iloc[-1])
        prev_close = float(hist["Close"].iloc[-2])
        change = price - prev_close
        change_pct = (change / prev_close * 100) if prev_close else 0.0

        info = getattr(ticker_obj, "fast_info", {}) or {}
        currency = get_currency(info)
        name = get_display_name(ticker_obj, ticker)

        return Quote(
            ticker=ticker,
            name=name,
            price=price,
            prev_close=prev_close,
            change=change,
            change_pct=change_pct,
            currency=currency,
        )
    except Exception as exc:
        warn(f"{ticker} の取得に失敗: {exc}")
        return None


def format_quote_line(q: Quote) -> str:
    sign = "+" if q.change > 0 else ""
    price_str = f"{q.price:,.2f} {q.currency}"
    change_pct_str = f"{q.change_pct:+.2f}%"
    return (
        f"{q.arrow} {q.ticker:<6} {q.name[:28]:<28} "
        f"{price_str:>18}  "
        f"{sign}{q.change:,.2f} ({change_pct_str})"
    )


def print_table(quotes: list[Quote]) -> None:
    header = f"{'  ':<2} {'Ticker':<6} {'Name':<28} {'Price':>18}  Change (Pct)"
    print(header)
    print("-" * len(header))
    for q in quotes:
        print(format_quote_line(q))


def main() -> int:
    parser = argparse.ArgumentParser(description="最新株価と前日比騰落率を表示")
    parser.add_argument(
        "tickers",
        nargs="*",
        default=DEFAULT_TICKERS,
        help="ティッカー (例: NVDA IONQ ^GSPC)",
    )
    parser.add_argument("--json", action="store_true", help="JSON で出力（AI解説パイプライン向け）")
    args = parser.parse_args()

    if yf is None:
        return fail_dependency()

    tickers = args.tickers or DEFAULT_TICKERS
    quotes: list[Quote] = []
    failed_tickers: list[str] = []
    for ticker in tickers:
        q = fetch_quote(ticker)
        if q is not None:
            quotes.append(q)
        else:
            failed_tickers.append(ticker)

    if not quotes:
        print("データを取得できませんでした。", file=sys.stderr)
        return 1

    if failed_tickers:
        warn(f"一部の銘柄を取得できませんでした: {', '.join(failed_tickers)}")

    if args.json:
        print(json.dumps([asdict(q) for q in quotes], ensure_ascii=False, indent=2))
    else:
        print_table(quotes)

    return 0


if __name__ == "__main__":
    sys.exit(main())
