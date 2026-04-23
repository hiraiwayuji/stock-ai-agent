import yfinance as yf
import pandas as pd


def get_price(ticker: str) -> float | None:
    """現在株価取得"""
    t = yf.Ticker(ticker)
    info = t.fast_info
    return getattr(info, "last_price", None)


def get_ohlcv(ticker: str, period: str = "3mo", interval: str = "1d") -> pd.DataFrame:
    """OHLCV取得"""
    return yf.download(ticker, period=period, interval=interval, progress=False)


def get_indices() -> dict[str, float | None]:
    """主要指数スナップショット（日経、VIX、マザーズ）"""
    tickers = {
        "日経225": "^N225",
        "VIX": "^VIX",
        "グロース250": "^IGRO",  # 旧マザーズ相当
        "S&P500": "^GSPC",
        "ドル円": "JPY=X",
    }
    return {name: get_price(sym) for name, sym in tickers.items()}
