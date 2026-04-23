"""
ポートフォリオ CRUD — Supabase portfolio テーブル
"""
from __future__ import annotations
from dataclasses import dataclass
from src.db.supabase_client import get_client


@dataclass
class Position:
    ticker: str
    qty: float
    avg_cost: float       # 平均取得単価
    note: str = ""


def add_position(user_id: str, ticker: str, qty: float, cost: float, note: str = "") -> None:
    """保有ポジション追加 / 平均コスト自動計算でupsert"""
    client = get_client()
    existing = (
        client.table("portfolio")
        .select("qty, avg_cost")
        .eq("user_id", user_id)
        .eq("ticker", ticker)
        .maybe_single()
        .execute()
    ).data

    if existing:
        old_qty  = float(existing["qty"])
        old_cost = float(existing["avg_cost"])
        new_qty  = old_qty + qty
        new_cost = (old_qty * old_cost + qty * cost) / new_qty  # 加重平均
        client.table("portfolio").update({
            "qty": new_qty,
            "avg_cost": round(new_cost, 4),
            "note": note or existing.get("note", ""),
        }).eq("user_id", user_id).eq("ticker", ticker).execute()
    else:
        client.table("portfolio").insert({
            "user_id": user_id,
            "ticker": ticker,
            "qty": qty,
            "avg_cost": cost,
            "note": note,
        }).execute()


def reduce_position(user_id: str, ticker: str, qty: float, sell_price: float | None = None) -> float:
    """売却。残数を返す。0以下になれば行を削除し、履歴を記録"""
    client = get_client()
    row = (
        client.table("portfolio")
        .select("qty, avg_cost")
        .eq("user_id", user_id)
        .eq("ticker", ticker)
        .maybe_single()
        .execute()
    ).data
    if not row:
        raise ValueError(f"{ticker} はポートフォリオに存在しません")

    avg_cost  = float(row["avg_cost"])
    remaining = float(row["qty"]) - qty
    if remaining <= 0:
        client.table("portfolio").delete().eq("user_id", user_id).eq("ticker", ticker).execute()
        remaining = 0.0
    else:
        client.table("portfolio").update({"qty": remaining}).eq("user_id", user_id).eq("ticker", ticker).execute()

    # 売買履歴を記録
    pnl = (sell_price - avg_cost) * qty if sell_price else None
    client.table("trade_history").insert({
        "user_id": user_id,
        "ticker":  ticker,
        "side":    "sell",
        "qty":     qty,
        "price":   sell_price or avg_cost,
        "pnl":     round(pnl, 0) if pnl is not None else None,
    }).execute()

    return remaining


def record_buy(user_id: str, ticker: str, qty: float, cost: float) -> None:
    """買いの売買履歴を記録"""
    get_client().table("trade_history").insert({
        "user_id": user_id,
        "ticker":  ticker,
        "side":    "buy",
        "qty":     qty,
        "price":   cost,
        "pnl":     None,
    }).execute()


def get_trade_history(user_id: str, ticker: str | None = None, limit: int = 20) -> list[dict]:
    client = get_client()
    q = client.table("trade_history").select("*").eq("user_id", user_id).order("traded_at", desc=True).limit(limit)
    if ticker:
        q = q.eq("ticker", ticker)
    return q.execute().data or []


def get_positions(user_id: str) -> list[dict]:
    client = get_client()
    res = client.table("portfolio").select("*").eq("user_id", user_id).execute()
    return res.data or []
