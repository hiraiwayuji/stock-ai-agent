"""
AI 総合投資デイリーレポート
全アルゴリズムを統合して「本日の最注目銘柄」を自動選定し、
ポートフォリオリスク評価 + 市場コンテキストを朝イチに送信
"""
from __future__ import annotations
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta

from src.stock.watchlist_optimizer import score_ticker, StockScore
from src.stock.fetcher import get_indices
from src.stock.regime import detect_regime, Regime
from src.news.fetcher import fetch_today_headlines, format_headlines_for_ai
from src.news.ticker_news import scan_ticker_news, format_ticker_news_message
from src.stock.earnings_calendar import check_earnings_alerts, format_earnings_message
from src.ai.analyst import analyze
from src.db.supabase_client import get_client

log = logging.getLogger(__name__)
JST = timezone(timedelta(hours=9))


@dataclass
class DailyReport:
    date_str: str
    top_picks: list[StockScore]          # 最注目銘柄 TOP3
    market_regime: str                   # 市場全体のレジーム
    indices_summary: str                 # 指数スナップショット
    news_summary: str                    # ニュース要約
    earnings_alerts: str                 # 決算アラート
    ticker_news_alerts: str              # 銘柄個別ニュース
    portfolio_risk: str                  # ポートフォリオリスク評価
    ai_strategy: str                     # AI総合戦略
    warnings: list[str] = field(default_factory=list)


def _get_all_tickers(user_id: str) -> tuple[list[str], list[str]]:
    """watchlist + portfolio の全ティッカーを取得"""
    client = get_client()
    wl  = [r["ticker"] for r in
           (client.table("watchlist").select("ticker").eq("user_id", user_id).execute().data or [])]
    hld = [r["ticker"] for r in
           (client.table("portfolio").select("ticker").eq("user_id", user_id).execute().data or [])]
    return wl, hld


def _score_universe(universe: list[str], vix: float | None) -> list[StockScore]:
    """ユニバースを並列スコアリング（エラー銘柄はスキップ）"""
    scores = []
    for ticker in set(universe):
        try:
            s = score_ticker(ticker, vix)
            scores.append(s)
        except Exception as e:
            log.warning(f"score {ticker}: {e}")
    return sorted(scores, key=lambda x: x.total_score, reverse=True)


def build_daily_report(
    user_id: str,
    scan_universe: list[str] | None = None,
) -> DailyReport:
    today_str = datetime.now(JST).strftime("%Y年%m月%d日")
    warnings  = []

    # ---- 指数 & VIX ----
    indices = {}
    vix     = None
    try:
        indices = get_indices()
        vix = indices.get("VIX")
        idx_lines = [f"{k}: {v:.2f}" if v else f"{k}: N/A"
                     for k, v in indices.items()]
        indices_summary = "\n".join(idx_lines)
    except Exception:
        indices_summary = "指数取得失敗"

    # ---- 市場レジーム ----
    market_regime = "不明"
    try:
        r = detect_regime("^N225", vix=vix)
        regime_labels = {
            Regime.TREND_UP:   "📈 上昇トレンド",
            Regime.TREND_DOWN: "📉 下降トレンド",
            Regime.RANGE:      "↔️ レンジ相場",
            Regime.CRISIS:     "🚨 クライシス警戒",
        }
        market_regime = f"{regime_labels[r.regime]} (確信度{r.score*100:.0f}%)"
        if r.regime == Regime.CRISIS:
            warnings.append("🚨 市場クライシス検知 — 新規買いは慎重に")
    except Exception:
        pass

    # ---- ニュース ----
    news_summary = ""
    try:
        headlines  = fetch_today_headlines()
        news_text  = format_headlines_for_ai(headlines)
        news_summary = analyze(
            f"【指数】\n{indices_summary}\n\n【ニュース】\n{news_text}",
            "本日の相場に最も影響するニュース TOP3 を箇条書きで要約してください（各1行）"
        )
    except Exception as e:
        log.warning(f"news: {e}")

    # ---- ユーザー銘柄取得 ----
    watchlist, holdings = [], []
    try:
        watchlist, holdings = _get_all_tickers(user_id)
    except Exception:
        pass

    universe = scan_universe or list(set(watchlist + holdings)) or \
               os.environ.get("SCREEN_UNIVERSE", "").split(",")

    # ---- 最注目銘柄スコアリング ----
    scores   = _score_universe([t for t in universe if t.strip()], vix)
    top_picks = scores[:3]

    # ---- 銘柄ニュースアラート ----
    ticker_news_alerts = ""
    if universe:
        try:
            news_items = scan_ticker_news(
                [t for t in universe if t.strip()],
                importance_threshold=0.65,
            )
            ticker_news_alerts = format_ticker_news_message(news_items)
        except Exception as e:
            log.warning(f"ticker_news: {e}")

    # ---- 決算アラート ----
    earnings_alerts = ""
    try:
        alerts = check_earnings_alerts(watchlist, holdings)
        earnings_alerts = format_earnings_message(alerts)
        if any(a.is_holding for a in alerts if a.days_until <= 1):
            warnings.append("⚠️ 保有銘柄の決算が本日・明日です")
    except Exception as e:
        log.warning(f"earnings: {e}")

    # ---- ポートフォリオリスク評価 ----
    portfolio_risk = ""
    if holdings:
        try:
            from src.stock.portfolio_analyzer import analyze_portfolio, format_portfolio_message
            summary = analyze_portfolio(user_id)
            port_txt = format_portfolio_message(summary)
            portfolio_risk = analyze(
                port_txt,
                "本日の市場環境を踏まえ、このポートフォリオのリスクを1〜3点で評価してください"
            )
        except Exception as e:
            log.warning(f"port_risk: {e}")

    # ---- AI 総合戦略 ----
    context_parts = [
        f"市場: {market_regime}",
        f"指数:\n{indices_summary}",
        f"ニュース:\n{news_summary}",
    ]
    if top_picks:
        picks_txt = "\n".join([
            f"{s.ticker}: {s.total_score:.0f}点 ({s.recommendation})"
            for s in top_picks
        ])
        context_parts.append(f"最注目銘柄:\n{picks_txt}")
    if warnings:
        context_parts.append("⚠️ 警告: " + " / ".join(warnings))

    ai_strategy = analyze(
        "\n\n".join(context_parts),
        "本日の投資戦略を3点で具体的に提案してください（各1〜2行）"
    )

    return DailyReport(
        date_str=today_str,
        top_picks=top_picks,
        market_regime=market_regime,
        indices_summary=indices_summary,
        news_summary=news_summary,
        earnings_alerts=earnings_alerts,
        ticker_news_alerts=ticker_news_alerts,
        portfolio_risk=portfolio_risk,
        ai_strategy=ai_strategy,
        warnings=warnings,
    )


def format_daily_report_messages(report: DailyReport) -> list[str]:
    """
    LINE の 5000 字制限に合わせて複数メッセージに分割して返す
    """
    msgs = []

    # メッセージ①: 市場サマリー
    m1_parts = [
        f"🌅 {report.date_str} 投資デイリーレポート",
        f"\n【市場レジーム】\n{report.market_regime}",
        f"\n【主要指数】\n{report.indices_summary}",
    ]
    if report.warnings:
        m1_parts.append("\n" + "\n".join(report.warnings))
    msgs.append("\n".join(m1_parts))

    # メッセージ②: ニュース + 決算
    m2_parts = [f"📰 本日のニュース要約\n{report.news_summary}"]
    if report.earnings_alerts:
        m2_parts.append(f"\n{report.earnings_alerts}")
    if report.ticker_news_alerts:
        m2_parts.append(f"\n{report.ticker_news_alerts}")
    msgs.append("\n".join(m2_parts))

    # メッセージ③: 最注目銘柄
    if report.top_picks:
        lines = ["🏆 本日の最注目銘柄"]
        for i, s in enumerate(report.top_picks, 1):
            rec_icon = {"強力買い推奨": "🔥", "買い推奨": "✅",
                        "様子見": "🔶", "除外推奨": "❌"}.get(s.recommendation, "")
            lines.append(
                f"\n{i}. {rec_icon} {s.ticker}  {s.total_score:.0f}/100\n"
                f"   {' / '.join(s.reasons[:2])}"
            )
        msgs.append("\n".join(lines))

    # メッセージ④: AI戦略
    ai_parts = [f"🤖 本日のAI投資戦略\n{report.ai_strategy}"]
    if report.portfolio_risk:
        ai_parts.append(f"\n💼 ポートフォリオリスク評価\n{report.portfolio_risk}")
    msgs.append("\n".join(ai_parts))

    return [m[:4999] for m in msgs if m.strip()]
