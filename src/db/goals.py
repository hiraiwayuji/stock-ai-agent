"""
投資目標 CRUD
yearly は month=0 で統一（NULL だと UNIQUE 制約が機能しないため）
金額は int(円) で管理し float 精度問題を回避
"""
from __future__ import annotations
from decimal import Decimal, ROUND_HALF_UP
from src.db.supabase_client import get_client

YEARLY_MONTH = 0  # yearly の month フィールドはこの値で固定


def _normalize(goal_type: str, month: int | None) -> int:
    """goal_type に応じて month を正規化"""
    if goal_type not in ("monthly", "yearly"):
        raise ValueError(f"goal_type は 'monthly' か 'yearly': {goal_type}")
    if goal_type == "yearly":
        return YEARLY_MONTH
    if month is None or not (1 <= month <= 12):
        raise ValueError(f"monthly goal には 1〜12 の month が必要です: {month}")
    return month


def set_goal(
    user_id: str,
    goal_type: str,
    year: int,
    month: int | None,
    target_pnl: int | float,
    target_winrate: float | None = None,
    target_trades: int | None = None,
) -> None:
    """目標を upsert（on_conflict 明示）"""
    if goal_type not in ("monthly", "yearly"):
        raise ValueError(f"goal_type は 'monthly' か 'yearly': {goal_type}")

    month_val = _normalize(goal_type, month)
    # 金額は整数円に丸める
    pnl_int = int(Decimal(str(target_pnl)).to_integral_value(ROUND_HALF_UP))

    data: dict = {
        "user_id":   user_id,
        "goal_type": goal_type,
        "year":      year,
        "month":     month_val,
        "target_pnl": pnl_int,
    }
    if target_winrate is not None:
        if not 0 <= target_winrate <= 100:
            raise ValueError("target_winrate は 0〜100")
        data["target_winrate"] = round(target_winrate, 2)
    if target_trades is not None:
        if target_trades <= 0:
            raise ValueError("target_trades は 1 以上")
        data["target_trades"] = target_trades

    get_client().table("investment_goals").upsert(
        data,
        on_conflict="user_id,goal_type,year,month",
    ).execute()


def get_goal(
    user_id: str,
    goal_type: str,
    year: int,
    month: int | None = None,
) -> dict | None:
    month_val = _normalize(goal_type, month)
    res = (
        get_client()
        .table("investment_goals")
        .select("*")
        .eq("user_id",   user_id)
        .eq("goal_type", goal_type)
        .eq("year",      year)
        .eq("month",     month_val)
        .maybe_single()
        .execute()
    )
    return res.data


def get_all_goals(user_id: str) -> list[dict]:
    res = (
        get_client()
        .table("investment_goals")
        .select("*")
        .eq("user_id", user_id)
        .order("year",  desc=True)
        .order("month", desc=True)
        .execute()
    )
    return res.data or []
