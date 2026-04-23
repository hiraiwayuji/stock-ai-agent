"""
ウォッチリスト自動最適化
スクリーナー × ML予測 × レジーム判定 × 類似パターン を統合スコアリング。
上位銘柄を自動推薦し、既存ウォッチリストの「劣化銘柄」を検出する。
"""
from __future__ import annotations
import logging
from dataclasses import dataclass, field

from src.stock.screener import run_screen, DEFAULT_UNIVERSE
from src.stock.ml_predictor import train_and_predict, MLPrediction
from src.stock.regime import detect_regime, Regime
from src.stock.pattern_match import find_similar_patterns
from src.stock.fetcher import get_ohlcv
from src.stock.technicals import compute_indicators, get_latest_signals

log = logging.getLogger(__name__)


@dataclass
class StockScore:
    ticker: str
    total_score: float             # 0~100
    ml_score: float                # ML上昇確率スコア
    regime_score: float            # レジームスコア
    pattern_score: float           # 過去パターン期待値スコア
    technical_score: float         # テクニカルスコア
    reasons: list[str] = field(default_factory=list)
    recommendation: str = ""       # "強力買い推奨" / "買い推奨" / "様子見" / "除外推奨"


def _technical_score(ticker: str) -> tuple[float, list[str]]:
    """テクニカル指標から0〜25点のスコアを計算"""
    reasons = []
    score = 0.0
    try:
        df = get_ohlcv(ticker, period="3mo")
        if df.empty:
            return 0.0, []
        df = compute_indicators(df)
        sig = get_latest_signals(df)

        rsi = sig["RSI"]
        ma_div = sig["MA_div_pct"]
        bb_pct = sig["BB_pct"]

        # RSI: 30〜50が買い優位
        if 30 <= rsi <= 50:
            score += 8
            reasons.append(f"RSI買い優位域({rsi:.0f})")
        elif rsi < 30:
            score += 5
            reasons.append(f"RSI売られ過ぎ({rsi:.0f})")

        # MA乖離: 軽度の押し目
        if -8 <= ma_div <= -1:
            score += 8
            reasons.append(f"MA押し目({ma_div:.1f}%)")
        elif ma_div > 0:
            score += 4

        # BB位置: 下半分が望ましい
        if bb_pct < 0.3:
            score += 9
            reasons.append(f"BB底圏({bb_pct:.2f})")
        elif bb_pct < 0.5:
            score += 5

    except Exception as e:
        log.warning(f"technical_score {ticker}: {e}")

    return min(score, 25.0), reasons


def _regime_score(ticker: str, vix: float | None = None) -> tuple[float, list[str]]:
    """レジームから0〜25点"""
    reasons = []
    score = 0.0
    try:
        result = detect_regime(ticker, vix)
        if result.regime == Regime.TREND_UP:
            score = 25.0 * result.score
            reasons.append(f"上昇トレンド(確信{result.score*100:.0f}%)")
        elif result.regime == Regime.RANGE:
            score = 12.0
            reasons.append("レンジ相場")
        elif result.regime == Regime.TREND_DOWN:
            score = 5.0
            reasons.append("下降トレンド中")
        elif result.regime == Regime.CRISIS:
            score = 0.0
            reasons.append("クライシス回避")
    except Exception as e:
        log.warning(f"regime_score {ticker}: {e}")
    return score, reasons


def _pattern_score(ticker: str) -> tuple[float, list[str]]:
    """過去類似パターンの平均期待リターンから0〜25点"""
    reasons = []
    score = 0.0
    try:
        matches = find_similar_patterns(ticker, top_n=5)
        if matches:
            avg_ret = sum(m.forward_return for m in matches) / len(matches)
            up_count = sum(1 for m in matches if m.outcome == "上昇")
            win_rate = up_count / len(matches)

            # 期待リターンと勝率を合成
            score = max(0, min(25, avg_ret * 2 + win_rate * 15))
            reasons.append(f"類似パターン勝率{win_rate*100:.0f}% 期待{avg_ret:+.1f}%")
    except Exception as e:
        log.warning(f"pattern_score {ticker}: {e}")
    return score, reasons


def _ml_score(ticker: str) -> tuple[float, MLPrediction | None, list[str]]:
    """ML予測確率から0〜25点"""
    reasons = []
    try:
        pred = train_and_predict(ticker, forward_days=5)
        score = pred.prob_up * 25  # 100%確率 → 25点
        reasons.append(f"ML上昇確率{pred.prob_up*100:.1f}%(確信:{pred.confidence})")
        return score, pred, reasons
    except Exception as e:
        log.warning(f"ml_score {ticker}: {e}")
        return 12.5, None, ["ML予測スキップ"]  # 中間値


def score_ticker(ticker: str, vix: float | None = None) -> StockScore:
    """4軸スコアリングで銘柄を評価"""
    t_score, t_reasons = _technical_score(ticker)
    r_score, r_reasons = _regime_score(ticker, vix)
    p_score, p_reasons = _pattern_score(ticker)
    m_score, pred, m_reasons = _ml_score(ticker)

    total = t_score + r_score + p_score + m_score
    all_reasons = t_reasons + r_reasons + p_reasons + m_reasons

    if total >= 75:
        rec = "強力買い推奨"
    elif total >= 55:
        rec = "買い推奨"
    elif total >= 35:
        rec = "様子見"
    else:
        rec = "除外推奨"

    return StockScore(
        ticker=ticker,
        total_score=round(total, 1),
        ml_score=round(m_score, 1),
        regime_score=round(r_score, 1),
        pattern_score=round(p_score, 1),
        technical_score=round(t_score, 1),
        reasons=all_reasons,
        recommendation=rec,
    )


def optimize_watchlist(
    universe: list[str] | None = None,
    top_n: int = 5,
    vix: float | None = None,
) -> list[StockScore]:
    """
    ユニバース全銘柄をスコアリングして上位 top_n を返す。
    スクリーナーで一次フィルタリング後に精密評価する。
    """
    targets = universe or DEFAULT_UNIVERSE

    # 一次フィルタ: スクリーナーで候補を絞る（複数プリセットのOR）
    screened = set()
    for preset in ["oversold", "dip", "volume_surge"]:
        for r in run_screen(preset, targets):
            screened.add(r.ticker)

    # スクリーナーにかからなかったものも全件評価（ユニバースが小さい場合）
    if len(screened) < top_n * 2:
        screened = set(targets)

    log.info(f"スコアリング対象: {len(screened)}銘柄")

    scores: list[StockScore] = []
    for ticker in screened:
        try:
            s = score_ticker(ticker.strip(), vix)
            scores.append(s)
            log.info(f"{ticker}: {s.total_score:.1f}点 ({s.recommendation})")
        except Exception as e:
            log.warning(f"skip {ticker}: {e}")

    return sorted(scores, key=lambda x: x.total_score, reverse=True)[:top_n]


def format_optimize_message(scores: list[StockScore]) -> str:
    if not scores:
        return "スコアリング対象銘柄なし"

    lines = [f"🏆 ウォッチリスト最適化 TOP{len(scores)}", ""]
    for i, s in enumerate(scores, 1):
        rec_icon = {"強力買い推奨": "🔥", "買い推奨": "✅", "様子見": "🔶", "除外推奨": "❌"}.get(s.recommendation, "")
        lines.append(
            f"{i}. {rec_icon} {s.ticker}  総合: {s.total_score:.0f}/100\n"
            f"   ML:{s.ml_score:.0f} レジーム:{s.regime_score:.0f} "
            f"パターン:{s.pattern_score:.0f} テクニカル:{s.technical_score:.0f}\n"
            f"   {' / '.join(s.reasons[:2])}"
        )
    return "\n".join(lines)


def audit_watchlist(user_watchlist: list[str]) -> list[StockScore]:
    """既存ウォッチリストを評価し、除外推奨銘柄を返す"""
    results = []
    for ticker in user_watchlist:
        try:
            s = score_ticker(ticker)
            results.append(s)
        except Exception as e:
            log.warning(f"audit {ticker}: {e}")
    return sorted(results, key=lambda x: x.total_score)
