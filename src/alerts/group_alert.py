import logging
from datetime import datetime, timezone, timedelta
from src.db.supabase_client import get_client
from src.stock.fetcher import get_indices, get_ohlcv
from src.db.groups import list_group_members
from src.db.portfolio import get_positions

log = logging.getLogger(__name__)
JST = timezone(timedelta(hours=9))


def check_group_alerts() -> list[tuple[str, str, list[str]]]:
    client = get_client()
    alerts_to_send = []
    
    # 1. Fetch indices (VIX, N225)
    vix_value = None
    n225_ret = None
    try:
        indices = get_indices()
        vix_value = indices.get("VIX")
        
        df_n225 = get_ohlcv("^N225", period="5d", interval="1d")
        if not df_n225.empty and len(df_n225) >= 2:
            close = df_n225["Close"].squeeze()
            n225_ret = (float(close.iloc[-1]) - float(close.iloc[-2])) / float(close.iloc[-2]) * 100
    except Exception as e:
        log.warning(f"Market fetch error: {e}")

    # 2. Fetch all groups with line_group_id
    res = client.table("groups").select("*").execute()
    groups = [g for g in (res.data or []) if g.get("line_group_id") is not None]
    
    today_start_iso = datetime.now(JST).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    
    for g in groups:
        line_group_id = g["line_group_id"]
        group_id = g["id"]
        group_name = g["name"]
        
        try:
            # 重複通知チェック
            hist = (
                client.table("alert_history")
                .select("alert_type")
                .eq("user_id", line_group_id)
                .gte("sent_at", today_start_iso)
                .execute()
            )
            sent_types = {row["alert_type"] for row in (hist.data or [])}

            group_msgs = []
            triggered_types: list[str] = []

            if (
                vix_value is not None
                and vix_value >= 30
                and "group_critical_vix" not in sent_types
            ):
                group_msgs.append(f"・VIX 急騰: {vix_value:.1f}")
                triggered_types.append("group_critical_vix")
            if (
                n225_ret is not None
                and n225_ret <= -3.0
                and "group_critical_n225" not in sent_types
            ):
                group_msgs.append(f"・日経平均 {n225_ret:+.1f}%")
                triggered_types.append("group_critical_n225")

            # グループ保有銘柄の暴落 (-7%以下)
            members = list_group_members(group_id)
            all_tickers = set()
            for m in members:
                uid = m["user_id"]
                pos = get_positions(uid)
                for p in pos:
                    all_tickers.add(p["ticker"])
                    
            crashed_tickers = []
            for ticker in all_tickers:
                try:
                    df = get_ohlcv(ticker, period="5d", interval="1d")
                    if not df.empty and len(df) >= 2:
                        close = df["Close"].squeeze()
                        daily_ret = (float(close.iloc[-1]) - float(close.iloc[-2])) / float(close.iloc[-2]) * 100
                        if daily_ret <= -7.0:
                            crashed_tickers.append(f"{ticker} {daily_ret:+.1f}%")
                except Exception as e:
                    pass
                    
            if crashed_tickers and "group_critical_crash" not in sent_types:
                group_msgs.append(f"・保有銘柄急落: {' / '.join(crashed_tickers)}")
                triggered_types.append("group_critical_crash")

            if group_msgs:
                message = f"🚨 {group_name} 市場重大アラート\n" + "\n".join(group_msgs)
                alerts_to_send.append((line_group_id, message, triggered_types))

        except Exception as e:
            log.warning(f"Error checking group alert for {group_name}: {e}")

    return alerts_to_send
