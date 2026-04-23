"""
ポートフォリオ損益・リスク分析
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from dataclasses import dataclass

from src.stock.fetcher import get_price, get_ohlcv
from src.db.portfolio import get_positions


@dataclass
class PositionSummary:
    ticker: str
    qty: float
    avg_cost: float
    current_price: float
    market_value: float    # 時価評価額
    unrealized_pnl: float  # 含み損益
    pnl_pct: float         # 損益率(%)
    daily_pnl: float       # 当日損益


@dataclass
class PortfolioSummary:
    total_cost: float
    total_value: float
    total_pnl: float
    total_pnl_pct: float
    daily_pnl: float
    positions: list[PositionSummary]
    sharpe_ratio: float | None  # 過去リターンのシャープレシオ


def analyze_portfolio(user_id: str) -> PortfolioSummary:
    positions = get_positions(user_id)
    if not positions:
        return PortfolioSummary(0, 0, 0, 0, 0, [], None)

    summaries: list[PositionSummary] = []
    total_cost = total_value = daily_pnl_sum = 0.0
    tickers_ret: dict[str, pd.Series] = {}

    for p in positions:
        ticker   = p["ticker"]
        qty      = float(p["qty"])
        avg_cost = float(p["avg_cost"])

        current = get_price(ticker)
        if current is None:
            current = avg_cost  # フォールバック

        # 当日損益計算
        df5 = get_ohlcv(ticker, period="5d", interval="1d")
        if len(df5) >= 2:
            prev_close = float(df5["Close"].squeeze().iloc[-2])
            daily_pnl_pos = (current - prev_close) * qty
        else:
            prev_close = current
            daily_pnl_pos = 0.0

        mv  = current * qty
        pnl = (current - avg_cost) * qty
        pct = (current - avg_cost) / avg_cost * 100

        summaries.append(PositionSummary(
            ticker=ticker,
            qty=qty,
            avg_cost=avg_cost,
            current_price=round(current, 2),
            market_value=round(mv, 0),
            unrealized_pnl=round(pnl, 0),
            pnl_pct=round(pct, 2),
            daily_pnl=round(daily_pnl_pos, 0),
        ))
        total_cost  += avg_cost * qty
        total_value += mv
        daily_pnl_sum += daily_pnl_pos

        # シャープレシオ用リターン系列収集
        df3m = get_ohlcv(ticker, period="3mo", interval="1d")
        if not df3m.empty:
            ret = df3m["Close"].squeeze().pct_change().dropna()
            tickers_ret[ticker] = ret * (mv / total_value) if total_value > 0 else ret

    total_pnl = total_value - total_cost
    total_pnl_pct = total_pnl / total_cost * 100 if total_cost > 0 else 0

    # ポートフォリオ全体シャープレシオ（等重平均リターンで近似）
    sharpe = None
    if tickers_ret:
        combined = pd.concat(list(tickers_ret.values()), axis=1).mean(axis=1).dropna()
        if len(combined) > 5 and combined.std() > 0:
            sharpe = round(combined.mean() / combined.std() * np.sqrt(252), 2)

    return PortfolioSummary(
        total_cost=round(total_cost, 0),
        total_value=round(total_value, 0),
        total_pnl=round(total_pnl, 0),
        total_pnl_pct=round(total_pnl_pct, 2),
        daily_pnl=round(daily_pnl_sum, 0),
        positions=sorted(summaries, key=lambda x: x.market_value, reverse=True),
        sharpe_ratio=sharpe,
    )


def format_portfolio_message(summary: PortfolioSummary) -> str:
    if not summary.positions:
        return "ポートフォリオが空です。\n/buy <ticker> <単価> <株数> で登録してください。"

    pnl_icon = "📈" if summary.total_pnl >= 0 else "📉"
    day_icon  = "📈" if summary.daily_pnl >= 0 else "📉"

    lines = [
        f"💼 ポートフォリオサマリー",
        f"時価総額:  ¥{summary.total_value:>12,.0f}",
        f"含み損益: {pnl_icon} ¥{summary.total_pnl:>+,.0f} ({summary.total_pnl_pct:+.2f}%)",
        f"当日損益:  {day_icon} ¥{summary.daily_pnl:>+,.0f}",
    ]
    if summary.sharpe_ratio is not None:
        lines.append(f"シャープ:  {summary.sharpe_ratio:.2f}")

    lines.append("\n--- 保有銘柄 ---")
    for pos in summary.positions:
        icon = "▲" if pos.unrealized_pnl >= 0 else "▼"
        lines.append(
            f"{icon} {pos.ticker}  {pos.qty:.0f}株\n"
            f"   現値 ¥{pos.current_price:,.0f}  "
            f"含み{pos.pnl_pct:+.1f}%  当日{pos.daily_pnl:+,.0f}円"
        )
    return "\n".join(lines)
