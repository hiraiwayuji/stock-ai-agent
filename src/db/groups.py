"""
グループ共有機能 DB ヘルパ
- groups / group_members / trade_shares / group_messages
通知ポリシー:
  - LINE グループ: 大きなお知らせのみ（月次ランキング・重大アラート）
  - in-app チャット (group_messages): 売買共有・コメント・タイムライン
  - 個人 LINE: 従来どおり個人AI秘書として継続
"""
from __future__ import annotations
import logging
import secrets
import string
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Optional

from src.db.supabase_client import get_client

log = logging.getLogger(__name__)
JST = timezone(timedelta(hours=9))


@dataclass
class Group:
    id: str
    name: str
    line_group_id: Optional[str]
    invite_code: str
    owner_id: str


def _gen_invite_code(n: int = 6) -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(n))


def create_group(name: str, owner_id: str, line_group_id: Optional[str] = None) -> Group:
    client = get_client()
    for _ in range(5):
        code = _gen_invite_code()
        try:
            row = client.table("groups").insert({
                "name": name,
                "line_group_id": line_group_id,
                "invite_code": code,
                "owner_id": owner_id,
            }).execute().data[0]
            break
        except Exception as e:
            log.warning(f"invite_code collision retry: {e}")
    else:
        raise RuntimeError("failed to generate unique invite_code")

    g = Group(
        id=row["id"],
        name=row["name"],
        line_group_id=row.get("line_group_id"),
        invite_code=row["invite_code"],
        owner_id=row["owner_id"],
    )
    join_group(g.id, owner_id)
    return g


def join_group(group_id: str, user_id: str, nickname: Optional[str] = None) -> bool:
    client = get_client()
    try:
        client.table("group_members").upsert({
            "group_id": group_id,
            "user_id": user_id,
            "nickname": nickname,
        }, on_conflict="group_id,user_id").execute()
        return True
    except Exception as e:
        log.warning(f"join_group: {e}")
        return False


def join_by_invite_code(code: str, user_id: str, nickname: Optional[str] = None) -> Optional[Group]:
    client = get_client()
    rows = client.table("groups").select("*").eq("invite_code", code.upper()).execute().data or []
    if not rows:
        return None
    row = rows[0]
    g = Group(
        id=row["id"], name=row["name"],
        line_group_id=row.get("line_group_id"),
        invite_code=row["invite_code"], owner_id=row["owner_id"],
    )
    join_group(g.id, user_id, nickname)
    return g


def get_group_by_line_id(line_group_id: str) -> Optional[Group]:
    client = get_client()
    rows = client.table("groups").select("*").eq("line_group_id", line_group_id).execute().data or []
    if not rows:
        return None
    r = rows[0]
    return Group(
        id=r["id"], name=r["name"],
        line_group_id=r.get("line_group_id"),
        invite_code=r["invite_code"], owner_id=r["owner_id"],
    )


def list_user_groups(user_id: str) -> list[Group]:
    client = get_client()
    mem = client.table("group_members").select("group_id").eq("user_id", user_id).execute().data or []
    gids = [m["group_id"] for m in mem]
    if not gids:
        return []
    rows = client.table("groups").select("*").in_("id", gids).execute().data or []
    return [Group(
        id=r["id"], name=r["name"],
        line_group_id=r.get("line_group_id"),
        invite_code=r["invite_code"], owner_id=r["owner_id"],
    ) for r in rows]


def list_group_members(group_id: str) -> list[dict]:
    client = get_client()
    return client.table("group_members").select("user_id, nickname, joined_at")\
        .eq("group_id", group_id).execute().data or []


def share_trade(
    group_id: str,
    user_id: str,
    ticker: str,
    side: str,
    qty: float,
    price: float,
    pnl: Optional[float] = None,
    comment: Optional[str] = None,
) -> str:
    client = get_client()
    row = client.table("trade_shares").insert({
        "group_id": group_id,
        "user_id": user_id,
        "ticker": ticker,
        "side": side,
        "qty": qty,
        "price": price,
        "pnl": pnl,
        "comment": comment,
    }).execute().data[0]
    # in-app タイムラインにも記録
    client.table("group_messages").insert({
        "group_id": group_id,
        "user_id": user_id,
        "kind": "trade",
        "body": comment or f"{side.upper()} {ticker} {qty}株 @{price}",
        "ref_trade_id": row["id"],
    }).execute()
    return row["id"]


def post_comment(group_id: str, user_id: str, body: str) -> str:
    client = get_client()
    row = client.table("group_messages").insert({
        "group_id": group_id,
        "user_id": user_id,
        "kind": "comment",
        "body": body,
    }).execute().data[0]
    return row["id"]


def fetch_timeline(group_id: str, limit: int = 20) -> list[dict]:
    client = get_client()
    return client.table("group_messages").select("*")\
        .eq("group_id", group_id).order("created_at", desc=True)\
        .limit(limit).execute().data or []


def ranking(
    group_id: str,
    period_days: int = 30,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
) -> list[dict]:
    """グループ内の実現損益ランキング (trade_shares.pnl 合算)

    since/until 指定時はその範囲で集計。未指定なら直近 period_days。
    """
    client = get_client()
    if since is None:
        since = datetime.now(JST) - timedelta(days=period_days)
    q = client.table("trade_shares").select("user_id, pnl")\
        .eq("group_id", group_id).gte("shared_at", since.isoformat())
    if until is not None:
        q = q.lt("shared_at", until.isoformat())
    rows = q.execute().data or []
    agg: dict[str, dict] = {}
    for r in rows:
        uid = r["user_id"]
        a = agg.setdefault(uid, {"user_id": uid, "pnl": 0.0, "trades": 0, "wins": 0})
        pnl = r.get("pnl") or 0
        a["pnl"] += float(pnl)
        a["trades"] += 1
        if pnl and float(pnl) > 0:
            a["wins"] += 1
    lst = list(agg.values())
    for a in lst:
        a["winrate"] = (a["wins"] / a["trades"] * 100) if a["trades"] else 0
    lst.sort(key=lambda x: x["pnl"], reverse=True)
    return lst
