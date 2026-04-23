from src.stock.fetcher import get_price, get_indices, get_ohlcv
from src.stock.regime import detect_regime, format_regime_message, Regime
from src.line.client import push_text
import logging

log = logging.getLogger(__name__)

VIX_DANGER_THRESHOLD = 30.0
VIX_CRISIS_THRESHOLD = 35.0


def check_market_alert(user_id: str) -> None:
    """
    主要指数を監視 + レジーム検出で複合アラートを生成。
    VIX単体より誤報が少ない3軸判定。
    """
    indices = get_indices()
    alerts = []

    vix = indices.get("VIX")
    if vix:
        if vix >= VIX_CRISIS_THRESHOLD:
            alerts.append(f"🚨 VIX緊急: {vix:.1f} (クライシス水準)")
        elif vix >= VIX_DANGER_THRESHOLD:
            alerts.append(f"⚠️ VIX警戒: {vix:.1f} (恐怖指数上昇中)")

    # 日経225のレジーム判定
    try:
        nikkei_regime = detect_regime("^N225", vix=vix)
        if nikkei_regime.regime == Regime.CRISIS:
            alerts.append(format_regime_message("日経225", nikkei_regime))
        elif nikkei_regime.regime == Regime.TREND_DOWN and nikkei_regime.score > 0.7:
            alerts.append(format_regime_message("日経225", nikkei_regime))
    except Exception as e:
        log.warning(f"regime check failed: {e}")

    if alerts:
        push_text(user_id, "\n\n".join(alerts))


def check_watchlist_alerts(user_id: str, watchlist: list[dict]) -> None:
    """
    監視銘柄の指値接近 + 変動率アラートを通知。
    レジームがCRISISの場合は即座に警告を追加。
    """
    for item in watchlist:
        ticker = item["ticker"]
        alert_price = item.get("alert_price")
        alert_pct   = item.get("alert_pct", 5.0)  # デフォルト±5%
        current = get_price(ticker)

        if current is None:
            continue

        msgs = []

        # 指値接近チェック
        if alert_price:
            diff_pct = (current - alert_price) / alert_price * 100
            if abs(diff_pct) <= 1.0:
                direction = "接近↑" if current >= alert_price else "接近↓"
                msgs.append(f"🔔 指値 ¥{alert_price:,.0f} に{direction} (現在 ¥{current:,.0f})")

        # 前日比変動率チェック
        try:
            df = get_ohlcv(ticker, period="5d", interval="1d")
            if len(df) >= 2:
                close = df["Close"].squeeze()
                daily_ret = (float(close.iloc[-1]) - float(close.iloc[-2])) / float(close.iloc[-2]) * 100
                if abs(daily_ret) >= (alert_pct or 5.0):
                    icon = "📈" if daily_ret > 0 else "📉"
                    msgs.append(f"{icon} 前日比 {daily_ret:+.2f}% (閾値 ±{alert_pct}%)")
        except Exception:
            pass

        if msgs:
            body = f"[{ticker}]\n" + "\n".join(msgs)
            push_text(user_id, body)
