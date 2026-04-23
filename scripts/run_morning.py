"""
朝イチブリーフィング 単発実行スクリプト
GitHub Actions の morning_briefing.yml から呼ばれる
"""
import os
import sys
import logging
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from src.news.fetcher import fetch_today_headlines, format_headlines_for_ai
from src.stock.fetcher import get_indices, get_ohlcv
from src.stock.technicals import compute_indicators, get_latest_signals
from src.stock.regime import detect_regime, format_regime_message, Regime
from src.ai.analyst import analyze
from src.line.client import push_text

USER_ID = os.environ["LINE_USER_ID"]

WATCH_TICKERS = os.environ.get("WATCH_TICKERS", "^N225,^VIX").split(",")


def build_technicals_summary() -> str:
    lines = []
    for ticker in WATCH_TICKERS[:3]:
        ticker = ticker.strip()
        try:
            df = get_ohlcv(ticker, period="1mo")
            if df.empty:
                continue
            df = compute_indicators(df)
            sig = get_latest_signals(df)
            lines.append(
                f"{ticker}: RSI {sig['RSI']}  MA乖離 {sig['MA_div_pct']}%  BB {sig['BB_pct']}"
            )
        except Exception as e:
            log.warning(f"technicals {ticker}: {e}")
    return "\n".join(lines)


def main():
    log.info("朝イチブリーフィング開始")

    # 指数スナップショット
    indices = get_indices()
    idx_lines = []
    for name, val in indices.items():
        idx_lines.append(f"{name}: {val:.2f}" if val else f"{name}: N/A")
    indices_text = "\n".join(idx_lines)

    # ニュース
    headlines = fetch_today_headlines()
    headline_text = format_headlines_for_ai(headlines)

    # テクニカルサマリー
    tech_text = build_technicals_summary()

    # 日経レジーム判定
    vix = indices.get("VIX")
    try:
        regime_result = detect_regime("^N225", vix=vix)
        regime_text = format_regime_message("日経225", regime_result)
        regime_warning = "\n\n" + regime_text if regime_result.regime in (Regime.CRISIS, Regime.TREND_DOWN) else ""
    except Exception:
        regime_warning = ""

    # AI分析
    context = (
        f"【主要指数】\n{indices_text}\n\n"
        f"【テクニカル】\n{tech_text}\n\n"
        f"【本日のニュース】\n{headline_text}"
    )
    analysis = analyze(context)

    # LINE送信
    message = (
        f"おはようございます！本日の相場ブリーフィングです。\n\n"
        f"--- 主要指数 ---\n{indices_text}"
        f"{regime_warning}\n\n"
        f"--- AI分析 ---\n{analysis}"
    )
    push_text(USER_ID, message)
    log.info("送信完了")


if __name__ == "__main__":
    main()
