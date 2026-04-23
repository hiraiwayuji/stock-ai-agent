"""
銘柄スクリーナー
条件式（RSI, MA乖離, BB位置, 出来高比）でフィルタリング。
対象銘柄リストは環境変数 SCREEN_UNIVERSE から取得。
"""
from __future__ import annotations
import os
import logging
from dataclasses import dataclass

from src.stock.fetcher import get_ohlcv, get_price
from src.stock.technicals import compute_indicators, get_latest_signals

log = logging.getLogger(__name__)

# スクリーニング対象ユニバース（カンマ区切りで環境変数に持たせる）
DEFAULT_UNIVERSE = os.environ.get(
    "SCREEN_UNIVERSE",
    "7203.T,9984.T,6758.T,6861.T,8306.T,9432.T,7974.T,4063.T,6367.T,8035.T"
).split(",")


@dataclass
class ScreenResult:
    ticker: str
    price: float
    rsi: float
    ma_div_pct: float   # MA25乖離率(%)
    bb_pct: float       # ボリンジャー位置 (0=下限 1=上限)
    vol_ratio: float    # 出来高/20日平均
    matched_rules: list[str]


PRESET_SCREENS = {
    "oversold":     "RSI<30 の売られ過ぎ銘柄（逆張り買い候補）",
    "overbought":   "RSI>70 の買われ過ぎ銘柄（利確/空売り候補）",
    "breakout":     "BB上限突破＋出来高急増（ブレイクアウト）",
    "dip":          "MA乖離-5%以下の押し目買い候補",
    "volume_surge": "出来高2倍以上の急騰/急落候補",
}


def _eval_rules(sig: dict, vol_ratio: float) -> dict[str, bool]:
    return {
        "oversold":     sig["RSI"] < 30,
        "overbought":   sig["RSI"] > 70,
        "breakout":     sig["BB_pct"] > 0.9 and vol_ratio >= 1.5,
        "dip":          sig["MA_div_pct"] < -5.0,
        "volume_surge": vol_ratio >= 2.0,
    }


def run_screen(preset: str = "oversold", universe: list[str] | None = None) -> list[ScreenResult]:
    """指定プリセットでユニバースをスキャンし、条件を満たす銘柄を返す"""
    targets = universe or DEFAULT_UNIVERSE
    results: list[ScreenResult] = []

    for ticker in targets:
        ticker = ticker.strip()
        if not ticker:
            continue
        try:
            df = get_ohlcv(ticker, period="3mo", interval="1d")
            if df.empty or len(df) < 30:
                continue

            df = compute_indicators(df)
            sig = get_latest_signals(df)

            vol = df["Volume"].squeeze()
            vol_ma20   = float(vol.rolling(20).mean().iloc[-1])
            vol_now    = float(vol.iloc[-1])
            vol_ratio  = vol_now / vol_ma20 if vol_ma20 > 0 else 1.0

            rules = _eval_rules(sig, vol_ratio)
            if not rules.get(preset, False):
                continue

            price = get_price(ticker) or float(df["Close"].squeeze().iloc[-1])
            matched = [k for k, v in rules.items() if v]

            results.append(ScreenResult(
                ticker=ticker,
                price=round(price, 2),
                rsi=sig["RSI"],
                ma_div_pct=sig["MA_div_pct"],
                bb_pct=sig["BB_pct"],
                vol_ratio=round(vol_ratio, 1),
                matched_rules=matched,
            ))
        except Exception as e:
            log.warning(f"screen {ticker}: {e}")

    return sorted(results, key=lambda x: x.rsi)


def run_custom_screen(
    rsi_max: float | None = None,
    rsi_min: float | None = None,
    ma_div_max: float | None = None,
    vol_ratio_min: float | None = None,
    universe: list[str] | None = None,
) -> list[ScreenResult]:
    """カスタム条件スクリーン"""
    targets = universe or DEFAULT_UNIVERSE
    results: list[ScreenResult] = []

    for ticker in targets:
        ticker = ticker.strip()
        if not ticker:
            continue
        try:
            df = get_ohlcv(ticker, period="3mo", interval="1d")
            if df.empty or len(df) < 30:
                continue

            df = compute_indicators(df)
            sig = get_latest_signals(df)

            vol = df["Volume"].squeeze()
            vol_ma20  = float(vol.rolling(20).mean().iloc[-1])
            vol_now   = float(vol.iloc[-1])
            vol_ratio = vol_now / vol_ma20 if vol_ma20 > 0 else 1.0

            if rsi_max is not None and sig["RSI"] > rsi_max:
                continue
            if rsi_min is not None and sig["RSI"] < rsi_min:
                continue
            if ma_div_max is not None and sig["MA_div_pct"] > ma_div_max:
                continue
            if vol_ratio_min is not None and vol_ratio < vol_ratio_min:
                continue

            price = get_price(ticker) or float(df["Close"].squeeze().iloc[-1])
            results.append(ScreenResult(
                ticker=ticker,
                price=round(price, 2),
                rsi=sig["RSI"],
                ma_div_pct=sig["MA_div_pct"],
                bb_pct=sig["BB_pct"],
                vol_ratio=round(vol_ratio, 1),
                matched_rules=["custom"],
            ))
        except Exception as e:
            log.warning(f"screen {ticker}: {e}")

    return results


def format_screen_message(preset: str, results: list[ScreenResult]) -> str:
    desc = PRESET_SCREENS.get(preset, preset)
    if not results:
        return f"🔍 [{preset}] 該当銘柄なし\n条件: {desc}"

    lines = [f"🔍 スクリーニング結果: {preset}", f"条件: {desc}", f"該当: {len(results)}銘柄\n"]
    for r in results[:10]:  # 最大10件
        lines.append(
            f"• {r.ticker}  ¥{r.price:,.0f}\n"
            f"  RSI {r.rsi:.0f}  MA乖離 {r.ma_div_pct:+.1f}%  出来高比 {r.vol_ratio}x"
        )
    if len(results) > 10:
        lines.append(f"... 他{len(results)-10}銘柄")
    return "\n".join(lines)
