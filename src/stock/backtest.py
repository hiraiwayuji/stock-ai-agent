"""
バックテストエンジン — pure pandas/numpy実装
外部ライブラリ不要、カスタム戦略を簡単に追加できる設計
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from abc import ABC, abstractmethod
from typing import Literal


# ------------------------------------------------------------------ #
# データクラス
# ------------------------------------------------------------------ #

@dataclass
class Trade:
    entry_date: str
    exit_date: str
    side: Literal["long", "short"]
    entry_price: float
    exit_price: float
    pnl: float
    pnl_pct: float
    hold_days: int


@dataclass
class BacktestResult:
    ticker: str
    strategy: str
    period: str
    total_return_pct: float
    annual_return_pct: float
    sharpe_ratio: float
    max_drawdown_pct: float
    win_rate_pct: float
    profit_factor: float
    total_trades: int
    trades: list[Trade] = field(default_factory=list)
    equity_curve: pd.Series | None = None   # 資産推移


# ------------------------------------------------------------------ #
# 戦略基底クラス
# ------------------------------------------------------------------ #

class Strategy(ABC):
    name: str = "base"
    description: str = ""

    @abstractmethod
    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        """
        +1 = 買いシグナル, -1 = 売りシグナル, 0 = 何もしない
        を日次で返す pd.Series
        """
        ...


# ------------------------------------------------------------------ #
# エンジン本体
# ------------------------------------------------------------------ #

def run_backtest(
    df: pd.DataFrame,
    strategy: Strategy,
    ticker: str,
    initial_cash: float = 1_000_000,
    commission_pct: float = 0.001,   # 0.1% 往復
) -> BacktestResult:
    """
    シンプルなイベント駆動バックテスト。
    ロング専用（空売りは将来拡張）。
    """
    close = df["Close"].squeeze().dropna()
    if len(close) < 30:
        raise ValueError(f"データ不足: {len(close)}本 (最低30本必要)")
    signals = strategy.generate_signals(df).reindex(close.index).fillna(0)

    cash = initial_cash
    position = 0.0        # 保有株数
    entry_price = 0.0
    entry_date = ""
    trades: list[Trade] = []
    equity: list[float] = []

    for i, (date, price) in enumerate(close.items()):
        sig = signals.get(date, 0)
        date_str = str(date)[:10]

        # ポジションなし → 買いシグナルで買い
        if position == 0 and sig == 1:
            shares = (cash * (1 - commission_pct)) // price
            if shares > 0:
                position    = shares
                entry_price = price
                entry_date  = date_str
                cash       -= shares * price * (1 + commission_pct)

        # ポジションあり → 売りシグナルで決済
        elif position > 0 and sig == -1:
            proceeds = position * price * (1 - commission_pct)
            pnl      = proceeds - position * entry_price * (1 + commission_pct)
            pnl_pct  = (price - entry_price) / entry_price * 100

            hold = (pd.Timestamp(date_str) - pd.Timestamp(entry_date)).days

            trades.append(Trade(
                entry_date=entry_date,
                exit_date=date_str,
                side="long",
                entry_price=round(entry_price, 2),
                exit_price=round(price, 2),
                pnl=round(pnl, 0),
                pnl_pct=round(pnl_pct, 2),
                hold_days=hold,
            ))
            cash     += proceeds
            position  = 0.0

        # 時価評価
        equity.append(cash + position * price)

    # 最後にポジション残があれば強制クローズ
    if position > 0:
        last_price = float(close.iloc[-1])
        proceeds   = position * last_price * (1 - commission_pct)
        pnl        = proceeds - position * entry_price * (1 + commission_pct)
        trades.append(Trade(
            entry_date=entry_date,
            exit_date=str(close.index[-1])[:10],
            side="long",
            entry_price=round(entry_price, 2),
            exit_price=round(last_price, 2),
            pnl=round(pnl, 0),
            pnl_pct=round((last_price - entry_price) / entry_price * 100, 2),
            hold_days=(close.index[-1] - pd.Timestamp(entry_date)).days,
        ))
        cash += proceeds

    # ---- 指標計算 ----
    equity_s = pd.Series(equity, index=close.index)
    total_ret = (equity_s.iloc[-1] - initial_cash) / initial_cash * 100
    days      = (close.index[-1] - close.index[0]).days
    annual    = ((1 + total_ret / 100) ** (365 / max(days, 1)) - 1) * 100

    daily_ret = equity_s.pct_change().dropna()
    sharpe    = (daily_ret.mean() / daily_ret.std() * np.sqrt(252)) if daily_ret.std() > 0 else 0.0

    roll_max  = equity_s.cummax()
    drawdown  = (equity_s - roll_max) / roll_max * 100
    max_dd    = float(drawdown.min())

    wins   = [t for t in trades if t.pnl > 0]
    losses = [t for t in trades if t.pnl <= 0]
    win_rate = len(wins) / len(trades) * 100 if trades else 0.0
    gross_profit = sum(t.pnl for t in wins)
    gross_loss   = abs(sum(t.pnl for t in losses))
    pf = gross_profit / gross_loss if gross_loss > 0 else float("inf")

    period_str = f"{str(close.index[0])[:10]} ~ {str(close.index[-1])[:10]}"

    return BacktestResult(
        ticker=ticker,
        strategy=strategy.name,
        period=period_str,
        total_return_pct=round(total_ret, 2),
        annual_return_pct=round(annual, 2),
        sharpe_ratio=round(sharpe, 2),
        max_drawdown_pct=round(max_dd, 2),
        win_rate_pct=round(win_rate, 1),
        profit_factor=round(pf, 2),
        total_trades=len(trades),
        trades=trades,
        equity_curve=equity_s,
    )


# ------------------------------------------------------------------ #
# 結果フォーマット
# ------------------------------------------------------------------ #

def format_backtest_message(result: BacktestResult) -> str:
    ret_icon = "📈" if result.total_return_pct >= 0 else "📉"
    lines = [
        f"📊 バックテスト結果",
        f"銘柄: {result.ticker}  戦略: {result.strategy}",
        f"期間: {result.period}",
        f"",
        f"{ret_icon} 総リターン:    {result.total_return_pct:+.2f}%",
        f"   年率リターン: {result.annual_return_pct:+.2f}%",
        f"   シャープ比:   {result.sharpe_ratio:.2f}",
        f"   最大DD:       {result.max_drawdown_pct:.2f}%",
        f"",
        f"勝率:           {result.win_rate_pct:.1f}%",
        f"PF:             {result.profit_factor:.2f}",
        f"総トレード数:   {result.total_trades}回",
    ]

    if result.trades:
        lines.append("\n--- 直近5トレード ---")
        for t in result.trades[-5:]:
            icon = "▲" if t.pnl >= 0 else "▼"
            lines.append(
                f"{icon} {t.entry_date}→{t.exit_date}  "
                f"{t.pnl_pct:+.1f}%  {t.pnl:+,.0f}円  {t.hold_days}日"
            )

    return "\n".join(lines)
