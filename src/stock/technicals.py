import pandas as pd
import ta


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """RSI / MACD / ボリンジャーバンド / 移動平均乖離率 を付与"""
    close = df["Close"].squeeze()

    df["RSI"] = ta.momentum.RSIIndicator(close, window=14).rsi()

    macd = ta.trend.MACD(close)
    df["MACD"] = macd.macd()
    df["MACD_signal"] = macd.macd_signal()
    df["MACD_diff"] = macd.macd_diff()

    bb = ta.volatility.BollingerBands(close, window=20, window_dev=2)
    df["BB_upper"] = bb.bollinger_hband()
    df["BB_lower"] = bb.bollinger_lband()
    df["BB_pct"] = bb.bollinger_pband()  # 0=下限, 1=上限

    df["MA25"] = close.rolling(25).mean()
    df["MA75"] = close.rolling(75).mean()
    df["MA_div"] = (close - df["MA25"]) / df["MA25"] * 100  # 乖離率(%)

    return df


def get_latest_signals(df: pd.DataFrame) -> dict:
    """最新バーのシグナルサマリー"""
    row = df.iloc[-1]
    return {
        "RSI": round(row.get("RSI", float("nan")), 1),
        "MACD_diff": round(row.get("MACD_diff", float("nan")), 4),
        "BB_pct": round(row.get("BB_pct", float("nan")), 2),
        "MA_div_pct": round(row.get("MA_div", float("nan")), 2),
    }
