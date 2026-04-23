"""
バックテスト用 プリセット戦略3種
新しい戦略は Strategy を継承して generate_signals() を実装するだけで追加可能
"""
from __future__ import annotations
import pandas as pd
from src.stock.backtest import Strategy
from src.stock.technicals import compute_indicators


class GoldenCrossStrategy(Strategy):
    """
    ゴールデンクロス / デッドクロス戦略
    MA25 が MA75 を上抜け → 買い
    MA25 が MA75 を下抜け → 売り
    """
    name = "golden_cross"
    description = "MA25/MA75 ゴールデンクロス戦略"

    def __init__(self, fast: int = 25, slow: int = 75):
        self.fast = fast
        self.slow = slow

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        close = df["Close"].squeeze()
        ma_fast = close.rolling(self.fast).mean()
        ma_slow = close.rolling(self.slow).mean()

        signals = pd.Series(0, index=df.index)
        # クロスを検出: 前日は fast < slow、今日は fast >= slow → 買い
        cross_up   = (ma_fast >= ma_slow) & (ma_fast.shift(1) < ma_slow.shift(1))
        cross_down = (ma_fast <= ma_slow) & (ma_fast.shift(1) > ma_slow.shift(1))
        signals[cross_up]   = 1
        signals[cross_down] = -1
        return signals


class RSIMeanReversionStrategy(Strategy):
    """
    RSI 逆張り戦略
    RSI が oversold（30以下）で買い → overbought（70以上）で売り
    """
    name = "rsi_reversion"
    description = "RSI逆張り戦略（RSI<30買い / RSI>70売り）"

    def __init__(self, oversold: float = 30.0, overbought: float = 70.0, window: int = 14):
        self.oversold   = oversold
        self.overbought = overbought
        self.window     = window

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        import ta
        close   = df["Close"].squeeze()
        rsi     = ta.momentum.RSIIndicator(close, window=self.window).rsi()
        signals = pd.Series(0, index=df.index)

        # RSI が oversold から回復した瞬間（下から oversold を上抜け）→ 買い
        buy  = (rsi > self.oversold)  & (rsi.shift(1) <= self.oversold)
        sell = (rsi > self.overbought) & (rsi.shift(1) <= self.overbought)
        signals[buy]  = 1
        signals[sell] = -1
        return signals


class BBBreakoutStrategy(Strategy):
    """
    ボリンジャーバンド ブレイクアウト戦略
    終値が BB上限を突破 → 買い（モメンタム）
    終値が BB下限を割り込む → 売り
    """
    name = "bb_breakout"
    description = "BBブレイクアウト戦略（上限突破買い / 下限割れ売り）"

    def __init__(self, window: int = 20, std: float = 2.0):
        self.window = window
        self.std    = std

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        import ta
        close   = df["Close"].squeeze()
        bb      = ta.volatility.BollingerBands(close, window=self.window, window_dev=self.std)
        upper   = bb.bollinger_hband()
        lower   = bb.bollinger_lband()
        signals = pd.Series(0, index=df.index)

        # 上限ブレイクアウト（前日は上限以下、今日は上限超え）
        buy  = (close > upper) & (close.shift(1) <= upper.shift(1))
        sell = (close < lower) & (close.shift(1) >= lower.shift(1))
        signals[buy]  = 1
        signals[sell] = -1
        return signals


class MACDCrossStrategy(Strategy):
    """
    MACDシグナルクロス戦略
    MACD が シグナル線を上抜け → 買い
    MACD が シグナル線を下抜け → 売り
    """
    name = "macd_cross"
    description = "MACDシグナルクロス戦略"

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        import ta
        close    = df["Close"].squeeze()
        macd_obj = ta.trend.MACD(close)
        macd     = macd_obj.macd()
        signal   = macd_obj.macd_signal()
        signals  = pd.Series(0, index=df.index)

        buy  = (macd > signal) & (macd.shift(1) <= signal.shift(1))
        sell = (macd < signal) & (macd.shift(1) >= signal.shift(1))
        signals[buy]  = 1
        signals[sell] = -1
        return signals


# 登録済み戦略マップ（コマンド名 → インスタンス）
STRATEGY_MAP: dict[str, Strategy] = {
    "golden":  GoldenCrossStrategy(),
    "rsi":     RSIMeanReversionStrategy(),
    "bb":      BBBreakoutStrategy(),
    "macd":    MACDCrossStrategy(),
}

STRATEGY_DESCRIPTIONS = {k: v.description for k, v in STRATEGY_MAP.items()}
