"""
アルゴリズム②: 過去類似パターン類似度スコア
直近N本の価格系列を正規化し、過去全データとコサイン類似度で比較。
「今の形は○年○月の〇〇前と XX%類似」をLINEで通知できる。
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from dataclasses import dataclass

from src.stock.fetcher import get_ohlcv


@dataclass
class PatternMatch:
    date: str           # 過去パターンの開始日
    similarity: float   # 類似度 0.0~1.0
    forward_return: float  # そのパターン後N日のリターン(%)
    outcome: str        # "上昇" / "下落" / "横ばい"


def _normalize(series: np.ndarray) -> np.ndarray:
    """ゼロ平均・単位ノルムに正規化（形のみ比較）"""
    s = series - series.mean()
    norm = np.linalg.norm(s)
    return s / norm if norm > 1e-10 else s


def find_similar_patterns(
    ticker: str,
    window: int = 20,
    top_n: int = 5,
    forward_days: int = 10,
) -> list[PatternMatch]:
    """
    直近 window 本と過去全期間を比較し、上位 top_n の類似パターンを返す。
    forward_days 後のリターンも付与。
    """
    df = get_ohlcv(ticker, period="5y", interval="1d")
    if df.empty or len(df) < window * 2:
        return []

    close = df["Close"].squeeze().values.astype(float)
    dates = df.index.strftime("%Y-%m-%d").tolist()

    # 直近パターン（比較対象）
    current_pattern = _normalize(close[-window:])

    results: list[PatternMatch] = []
    # スライディングウィンドウで過去全パターンと比較
    for i in range(len(close) - window - forward_days - 1):
        past_pattern = _normalize(close[i:i + window])
        # コサイン類似度
        sim = float(np.dot(current_pattern, past_pattern))
        sim = max(0.0, sim)  # 負値は類似なし

        # パターン後 forward_days のリターン
        end_price = close[i + window + forward_days - 1]
        start_price = close[i + window - 1]
        fwd_ret = (end_price - start_price) / start_price * 100 if start_price > 0 else 0.0

        results.append(PatternMatch(
            date=dates[i],
            similarity=round(sim, 3),
            forward_return=round(fwd_ret, 2),
            outcome="上昇" if fwd_ret > 1.5 else ("下落" if fwd_ret < -1.5 else "横ばい"),
        ))

    # 類似度 TOP N（直近30日は除外 — 自分自身との比較を防ぐ）
    results.sort(key=lambda x: x.similarity, reverse=True)
    # 直近 window*2 本は除外
    cutoff_date = dates[-(window * 2)]
    filtered = [r for r in results if r.date < cutoff_date]
    return filtered[:top_n]


def format_pattern_message(ticker: str, matches: list[PatternMatch], forward_days: int = 10) -> str:
    if not matches:
        return f"{ticker}: パターンデータ不足"

    lines = [f"🔍 {ticker} 過去類似パターン TOP{len(matches)} ({forward_days}日後リターン)"]
    up = sum(1 for m in matches if m.outcome == "上昇")
    down = sum(1 for m in matches if m.outcome == "下落")
    avg_ret = np.mean([m.forward_return for m in matches])

    for i, m in enumerate(matches, 1):
        icon = "📈" if m.outcome == "上昇" else ("📉" if m.outcome == "下落" else "↔️")
        lines.append(
            f"{i}. {m.date}  類似度{m.similarity*100:.0f}%  {icon}{m.forward_return:+.1f}%"
        )

    lines.append(f"\n予測: 上昇{up}/{len(matches)}件  平均リターン {avg_ret:+.1f}%")
    trend = "強気" if avg_ret > 2 else ("弱気" if avg_ret < -2 else "中立")
    lines.append(f"シグナル: {trend}")
    return "\n".join(lines)
