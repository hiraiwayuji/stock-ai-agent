from supabase import create_client, Client
from dotenv import load_dotenv
import os

load_dotenv()

_client: Client | None = None


def get_client() -> Client:
    global _client
    if _client is None:
        url = os.environ["SUPABASE_URL"]
        key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
        _client = create_client(url, key)
    return _client


def get_watchlist(user_id: str) -> list[dict]:
    """監視銘柄一覧を取得"""
    client = get_client()
    res = client.table("watchlist").select("*").eq("user_id", user_id).execute()
    return res.data or []


def upsert_watchlist(user_id: str, ticker: str, alert_price: float | None = None, alert_pct: float | None = None):
    """監視銘柄を追加/更新"""
    client = get_client()
    client.table("watchlist").upsert({
        "user_id": user_id,
        "ticker": ticker,
        "alert_price": alert_price,
        "alert_pct": alert_pct,
    }).execute()


def get_user_settings(user_id: str) -> dict:
    """ユーザー設定取得"""
    client = get_client()
    res = client.table("user_settings").select("*").eq("user_id", user_id).maybe_single().execute()
    return res.data or {}
