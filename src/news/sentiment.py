"""
アルゴリズム③: ニュースセンチメント×株価乖離スコア (Divergence Score)
ニュース感情がポジティブなのに株価が下落 → 機関の売り逃げ検知
ニュース感情がネガティブなのに株価が上昇  → 仕込み検知
"""
from __future__ import annotations
import numpy as np
from dataclasses import dataclass
from openai import OpenAI
import os
from dotenv import load_dotenv

from src.news.fetcher import fetch_today_headlines
from src.stock.fetcher import get_ohlcv

load_dotenv()
_openai = OpenAI(api_key=os.environ.get("OPENAI_API_KEY", ""))


@dataclass
class SentimentResult:
    ticker: str
    sentiment_score: float   # -1.0(悲観) ~ +1.0(楽観)
    price_change_pct: float  # 当日株価変動率(%)
    divergence_score: float  # 乖離スコア（大きいほど注目シグナル）
    signal: str              # "逆張り買い候補" / "逆張り売り候補" / "トレンド追随" / "中立"
    summary: str


def _score_sentiment(headlines: list[dict], ticker: str) -> float:
    """OpenAI に銘柄関連ニュースのセンチメントスコアを付けさせる"""
    if not headlines:
        return 0.0

    texts = "\n".join([f"- {h['title']}" for h in headlines[:10]])
    prompt = (
        f"以下のニュースについて、{ticker} の株価に与える影響を"
        f"-1.0（非常に悲観的）から+1.0（非常に楽観的）の数値1つだけで回答してください。\n"
        f"数値のみ返答（例: 0.35）\n\nニュース:\n{texts}"
    )
    try:
        res = _openai.chat.completions.create(
            model=os.environ.get("OPENAI_MODEL", "gpt-4o"),
            messages=[{"role": "user", "content": prompt}],
            max_tokens=10,
        )
        return float(res.choices[0].message.content.strip())
    except Exception:
        return 0.0


def _get_today_return(ticker: str) -> float:
    """当日の株価変動率(%)を取得"""
    df = get_ohlcv(ticker, period="5d", interval="1d")
    if df.empty or len(df) < 2:
        return 0.0
    close = df["Close"].squeeze()
    return float((close.iloc[-1] - close.iloc[-2]) / close.iloc[-2] * 100)


def compute_divergence(ticker: str) -> SentimentResult:
    """
    Divergence Score = sentiment × (−1) × price_direction
    同方向なら0付近、逆方向なら絶対値が大きくなる
    """
    headlines = fetch_today_headlines(max_per_feed=5)
    sentiment = _score_sentiment(headlines, ticker)
    price_ret = _get_today_return(ticker)

    # 乖離スコア: センチメントと株価が逆方向なら正の大きい値
    # sentiment>0 かつ price<0 → divergence 正（異常）
    if abs(sentiment) < 0.1 or abs(price_ret) < 0.3:
        divergence = 0.0
    else:
        # センチメントと価格変動の符号が逆なら乖離
        divergence = abs(sentiment) * abs(price_ret) * (
            -1.0 if (sentiment > 0) == (price_ret > 0) else 1.0
        )

    # シグナル分類
    if divergence >= 1.5 and sentiment > 0 and price_ret < 0:
        signal = "逆張り買い候補"  # ポジティブニュースなのに下落
    elif divergence >= 1.5 and sentiment < 0 and price_ret > 0:
        signal = "逆張り売り候補"  # ネガティブニュースなのに上昇
    elif abs(divergence) < 0.5:
        signal = "中立"
    else:
        signal = "トレンド追随"

    summary = (
        f"センチメント: {sentiment:+.2f} / 株価変動: {price_ret:+.2f}% / "
        f"乖離スコア: {divergence:+.2f}"
    )
    return SentimentResult(
        ticker=ticker,
        sentiment_score=round(sentiment, 2),
        price_change_pct=round(price_ret, 2),
        divergence_score=round(divergence, 2),
        signal=signal,
        summary=summary,
    )


def format_divergence_message(result: SentimentResult) -> str:
    icons = {
        "逆張り買い候補": "🔥",
        "逆張り売り候補": "⚠️",
        "トレンド追随": "➡️",
        "中立": "💤",
    }
    icon = icons.get(result.signal, "")
    return (
        f"{icon} {result.ticker} センチメント分析\n"
        f"{result.summary}\n"
        f"シグナル: {result.signal}"
    )
