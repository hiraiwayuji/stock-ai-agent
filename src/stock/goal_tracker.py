"""
投資目標の進捗計算・ペース予測
trade_history テーブルの実績と investment_goals を突き合わせる
"""
from __future__ import annotations
import calendar
from dataclasses import dataclass
from datetime import date, datetime, timezone, timedelta

from src.db.goals import get_goal, YEARLY_MONTH
from src.db.supabase_client import get_client

JST = timezone(timedelta(hours=9))


@dataclass
class GoalProgress:
    goal_type: str
    year: int
    month: int          # yearly は 0
    # 目標
    target_pnl: float
    target_winrate: float | None
    target_trades: int | None
    # 実績
    actual_pnl: float
    actual_winrate: float
    total_trades: int
    win_trades: int
    # 達成率
    achievement_pct: float
    remaining_pnl: float
    # ペース予測
    elapsed_days: int
    total_days: int
    pace_pnl: float         # このペースで終わると最終いくら？
    is_on_track: bool
    pace_message: str


def _fetch_trades(user_id: str, start: date, end: date) -> list[dict]:
    """期間内の sell 履歴を取得"""
    res = (
        get_client()
        .table("trade_history")
        .select("pnl, traded_at")
        .eq("user_id", user_id)
        .eq("side", "sell")
        .gte("traded_at", start.isoformat())
        .lte("traded_at", end.isoformat())
        .execute()
    )
    return res.data or []


def calc_goal_progress(
    user_id: str,
    goal_type: str,
    year: int,
    month: int | None = None,
) -> GoalProgress | None:
    goal = get_goal(user_id, goal_type, year, month)
    if not goal:
        return None

    today = datetime.now(JST).date()

    if goal_type == "monthly":
        m = month or today.month
        start = date(year, m, 1)
        end   = date(year, m, calendar.monthrange(year, m)[1])
    else:
        start = date(year, 1, 1)
        end   = date(year, 12, 31)

    trades = _fetch_trades(user_id, start, end)
    pnl_list = [float(t["pnl"]) for t in trades if t.get("pnl") is not None]

    actual_pnl   = sum(pnl_list)
    total_trades = len(pnl_list)
    win_trades   = sum(1 for p in pnl_list if p > 0)
    actual_wr    = (win_trades / total_trades * 100) if total_trades > 0 else 0.0

    target_pnl   = float(goal["target_pnl"])
    achievement  = (actual_pnl / target_pnl * 100) if target_pnl != 0 else 0.0
    remaining    = target_pnl - actual_pnl

    elapsed = max((min(today, end) - start).days + 1, 1)
    total   = (end - start).days + 1
    pace    = (actual_pnl / elapsed) * total if elapsed > 0 else 0.0
    on_track = pace >= target_pnl

    if actual_pnl < 0:
        pace_msg = f"💪 巻き返せ！現在 ¥{actual_pnl:+,.0f}"
    elif achievement >= 100:
        pace_msg = f"🏆 目標達成！！ ¥{actual_pnl:+,.0f} ({achievement:.0f}%)"
    elif on_track:
        pace_msg = f"🎯 達成ペース！予測 ¥{pace:+,.0f}"
    else:
        short = target_pnl - pace
        pace_msg = f"あと ¥{short:,.0f} 必要（現ペース予測 ¥{pace:+,.0f}）"

    return GoalProgress(
        goal_type=goal_type,
        year=year,
        month=goal["month"],
        target_pnl=target_pnl,
        target_winrate=goal.get("target_winrate"),
        target_trades=goal.get("target_trades"),
        actual_pnl=round(actual_pnl, 0),
        actual_winrate=round(actual_wr, 1),
        total_trades=total_trades,
        win_trades=win_trades,
        achievement_pct=round(achievement, 1),
        remaining_pnl=round(remaining, 0),
        elapsed_days=elapsed,
        total_days=total,
        pace_pnl=round(pace, 0),
        is_on_track=on_track,
        pace_message=pace_msg,
    )


def _effect_icon(achievement_pct: float, actual_pnl: float) -> str:
    if actual_pnl < 0:    return "💪"
    if achievement_pct >= 100: return "🏆🎉"
    if achievement_pct >= 90:  return "🎯"
    if achievement_pct >= 60:  return "⚡"
    if achievement_pct >= 30:  return "🔥"
    return "🌱"


def format_goal_message(p: GoalProgress) -> str:
    icon  = _effect_icon(p.achievement_pct, p.actual_pnl)
    label = f"{p.year}年{p.month}月" if p.goal_type == "monthly" else f"{p.year}年間"

    # 達成率バー (20マス)
    filled = int(min(p.achievement_pct, 100) / 5)
    bar    = "█" * filled + "░" * (20 - filled)

    lines = [
        f"{icon} {label}目標進捗",
        f"[{bar}] {p.achievement_pct:.1f}%",
        f"",
        f"実現損益:  ¥{p.actual_pnl:>+12,.0f}",
        f"目標損益:  ¥{p.target_pnl:>+12,.0f}",
        f"残り:      ¥{p.remaining_pnl:>+12,.0f}",
        f"",
        f"勝率: {p.actual_winrate:.1f}%  ({p.win_trades}勝/{p.total_trades - p.win_trades}敗)",
    ]
    if p.target_winrate:
        lines.append(f"目標勝率: {p.target_winrate:.1f}%")
    if p.target_trades:
        lines.append(f"目標取引数: {p.target_trades}回 (現在 {p.total_trades}回)")

    lines += [
        f"",
        f"経過: {p.elapsed_days}/{p.total_days}日",
        f"{p.pace_message}",
    ]
    return "\n".join(lines)
