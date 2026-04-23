"""
アルゴリズム①: 相場レジーム検出
RSI + VIX + 出来高 の3軸で「トレンド / レンジ / クライシス」を判定する。
TradingViewの単一指標アラートより誤報率が低い。
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from dataclasses import dataclass
from enum import Enum

from src.stock.fetcher import get_ohlcv, get_price
from src.stock.technicals import compute_indicators


class Regime(str, Enum):
    TREND_UP   = "TREND_UP"     # 上昇トレンド
    TREND_DOWN = "TREND_DOWN"   # 下降トレンド
    RANGE      = "RANGE"        # レンジ相場
    CRISIS     = "CRISIS"       # 危機（クライシス）


@dataclass
class RegimeResult:
    regime: Regime
    score: float          # 0.0 ~ 1.0（確信度）
    reasons: list[str]


def detect_regime(ticker: str, vix: float | None = None) -> RegimeResult:
    """
    3スコアを合算してレジームを判定。
      - rsi_score  : RSIが過熱/低迷 → トレンドの方向
      - vol_score  : 出来高の急増 → ブレイクアウト/クライシスの強度
      - vix_score  : VIXが30超で危機モード
    """
    df = get_ohlcv(ticker, period="3mo", interval="1d")
    if df.empty:
        return RegimeResult(Regime.RANGE, 0.0, ["データ取得失敗"])

    df = compute_indicators(df)
    row = df.iloc[-1]
    close = df["Close"].squeeze()

    reasons: list[str] = []
    crisis_votes = 0
    trend_up_votes = 0
    trend_down_votes = 0

    # --- RSI ---
    rsi = float(row.get("RSI", 50))
    if rsi >= 70:
        trend_up_votes += 2
        reasons.append(f"RSI過熱: {rsi:.1f}")
    elif rsi <= 30:
        trend_down_votes += 2
        reasons.append(f"RSI売られ過ぎ: {rsi:.1f}")
    else:
        reasons.append(f"RSI中立: {rsi:.1f}")

    # --- 出来高急増 ---
    vol = df["Volume"].squeeze()
    vol_ma20 = float(vol.rolling(20).mean().iloc[-1])
    vol_now  = float(vol.iloc[-1])
    vol_ratio = vol_now / vol_ma20 if vol_ma20 > 0 else 1.0
    if vol_ratio >= 2.0:
        crisis_votes += 2
        reasons.append(f"出来高急増: {vol_ratio:.1f}x")
    elif vol_ratio >= 1.5:
        trend_up_votes += 1
        reasons.append(f"出来高増: {vol_ratio:.1f}x")

    # --- VIX ---
    if vix is not None:
        if vix >= 35:
            crisis_votes += 3
            reasons.append(f"VIX危機水準: {vix:.1f}")
        elif vix >= 25:
            crisis_votes += 1
            reasons.append(f"VIX警戒水準: {vix:.1f}")
        else:
            reasons.append(f"VIX安定: {vix:.1f}")

    # --- 移動平均の配置 ---
    ma25 = float(row.get("MA25", close.iloc[-1]))
    ma75 = float(row.get("MA75", close.iloc[-1]))
    price_now = float(close.iloc[-1])
    if price_now > ma25 > ma75:
        trend_up_votes += 1
        reasons.append("価格>MA25>MA75 (上昇配列)")
    elif price_now < ma25 < ma75:
        trend_down_votes += 1
        reasons.append("価格<MA25<MA75 (下降配列)")

    # --- 判定 ---
    total = crisis_votes + trend_up_votes + trend_down_votes + 1e-9
    if crisis_votes >= 3:
        regime = Regime.CRISIS
        score = min(crisis_votes / (total), 1.0)
    elif trend_up_votes > trend_down_votes:
        regime = Regime.TREND_UP
        score = trend_up_votes / total
    elif trend_down_votes > trend_up_votes:
        regime = Regime.TREND_DOWN
        score = trend_down_votes / total
    else:
        regime = Regime.RANGE
        score = 0.5

    return RegimeResult(regime=regime, score=round(score, 2), reasons=reasons)


def format_regime_message(ticker: str, result: RegimeResult) -> str:
    icons = {
        Regime.TREND_UP:   "📈",
        Regime.TREND_DOWN: "📉",
        Regime.RANGE:      "↔️",
        Regime.CRISIS:     "🚨",
    }
    labels = {
        Regime.TREND_UP:   "上昇トレンド",
        Regime.TREND_DOWN: "下降トレンド",
        Regime.RANGE:      "レンジ相場",
        Regime.CRISIS:     "クライシス警戒",
    }
    icon = icons[result.regime]
    label = labels[result.regime]
    reason_text = " / ".join(result.reasons)
    return (
        f"{icon} [{ticker}] レジーム: {label} (確信度 {result.score*100:.0f}%)\n"
        f"根拠: {reason_text}"
    )
