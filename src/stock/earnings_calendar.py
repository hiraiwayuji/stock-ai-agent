"""
決算カレンダー監視
yfinance から決算日を取得し、保有・監視銘柄の決算 N 日前に LINE アラート
"""
from __future__ import annotations
import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone, timedelta

import yfinance as yf

log = logging.getLogger(__name__)
JST = timezone(timedelta(hours=9))


@dataclass
class EarningsAlert:
    ticker: str
    earnings_date: date
    days_until: int
    is_holding: bool   # 保有中か監視中か


def get_earnings_date(ticker: str) -> date | None:
    """yfinance から次回決算日を取得"""
    try:
        info = yf.Ticker(ticker).calendar
        if info is None or info.empty:
            return None
        # calendar は DataFrame: 列が日付、行が指標
        col = info.columns[0]
        return col.date() if hasattr(col, "date") else None
    except Exception as e:
        log.warning(f"earnings {ticker}: {e}")
        return None


def check_earnings_alerts(
    watchlist: list[str],
    holdings: list[str],
    alert_days: list[int] | None = None,
) -> list[EarningsAlert]:
    """
    全対象銘柄の決算日を確認し、alert_days のいずれかに一致したものを返す。
    alert_days: 何日前にアラートするか（デフォルト [1, 3, 7]）
    """
    if alert_days is None:
        alert_days = [1, 3, 7]

    today   = datetime.now(JST).date()
    targets = {t: True for t in holdings}     # is_holding=True
    for t in watchlist:
        if t not in targets:
            targets[t] = False                 # is_holding=False

    alerts: list[EarningsAlert] = []
    for ticker, is_holding in targets.items():
        edate = get_earnings_date(ticker)
        if edate is None:
            continue
        days = (edate - today).days
        if days in alert_days or (0 <= days <= 1):
            alerts.append(EarningsAlert(
                ticker=ticker,
                earnings_date=edate,
                days_until=days,
                is_holding=is_holding,
            ))
    return alerts


def format_earnings_message(alerts: list[EarningsAlert]) -> str:
    if not alerts:
        return ""

    lines = ["📅 決算アラート"]
    for a in sorted(alerts, key=lambda x: x.days_until):
        hold_icon = "💼" if a.is_holding else "👁️"
        if a.days_until == 0:
            timing = "本日"
        elif a.days_until == 1:
            timing = "明日"
        else:
            timing = f"{a.days_until}日後"
        lines.append(
            f"{hold_icon} {a.ticker}  {timing}（{a.earnings_date}）"
            + ("  ⚠️ 保有中" if a.is_holding else "")
        )
    return "\n".join(lines)
