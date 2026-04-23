"""
銘柄ニュース個別監視
監視銘柄に関連するニュースを RSS + OpenAI で重要度スコアリング
スコア閾値超えたものだけ LINE アラート
"""
from __future__ import annotations
import logging
from dataclasses import dataclass

import feedparser
from openai import OpenAI
import os
from dotenv import load_dotenv

load_dotenv()
log = logging.getLogger(__name__)
_openai = OpenAI(api_key=os.environ.get("OPENAI_API_KEY", ""))


@dataclass
class NewsItem:
    ticker: str
    title: str
    source: str
    link: str
    importance: float    # 0.0〜1.0（GPT が判定）
    summary: str         # 30字要約
    sentiment: str       # "positive" | "negative" | "neutral"


# 銘柄名から検索クエリを組み立てるためのマッピング（主要日本株）
TICKER_QUERY_MAP: dict[str, str] = {
    "7203.T": "トヨタ自動車",
    "9984.T": "ソフトバンクグループ",
    "6758.T": "ソニーグループ",
    "6861.T": "キーエンス",
    "8306.T": "三菱UFJフィナンシャル",
    "9432.T": "NTT",
    "7974.T": "任天堂",
    "4063.T": "信越化学",
    "6367.T": "ダイキン工業",
    "8035.T": "東京エレクトロン",
}

# RSS フィード（銘柄フィルタリング前の全般ニュース）
NEWS_FEEDS = {
    "日経": "https://www.nikkei.com/rss/news.rss",
    "Reuters JP": "https://feeds.reuters.com/reuters/JPjpMarketNews",
}


def _fetch_all_headlines(max_per_feed: int = 20) -> list[dict]:
    results = []
    for source, url in NEWS_FEEDS.items():
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:max_per_feed]:
                results.append({
                    "source": source,
                    "title":  entry.get("title", ""),
                    "link":   entry.get("link", ""),
                    "summary": entry.get("summary", "")[:200],
                })
        except Exception as e:
            log.warning(f"feed {source}: {e}")
    return results


def _score_news_for_ticker(headlines: list[dict], ticker: str) -> list[NewsItem]:
    """OpenAI で銘柄関連ニュースを抽出・スコアリング"""
    query = TICKER_QUERY_MAP.get(ticker, ticker.replace(".T", ""))
    # 関連しそうなヘッドラインを事前フィルタ（キーワード一致）
    candidates = [h for h in headlines
                  if query in h["title"] or query in h.get("summary", "")]
    if not candidates:
        return []

    texts = "\n".join([f"{i+1}. {h['title']}" for i, h in enumerate(candidates[:10])])
    prompt = (
        f"以下のニュースを {query}({ticker}) の株価への影響で評価してください。\n"
        f"各ニュースを JSON 配列で返してください:\n"
        f"[{{\"index\":1, \"importance\":0.8, \"sentiment\":\"negative\", \"summary\":\"30字要約\"}},...]\n"
        f"importance は 0.0〜1.0、sentiment は positive/negative/neutral。\n\n"
        f"ニュース:\n{texts}\n\n"
        f"JSON のみ返答（```は不要）:"
    )
    try:
        import json
        res = _openai.chat.completions.create(
            model=os.environ.get("OPENAI_MODEL", "gpt-4o"),
            messages=[{"role": "user", "content": prompt}],
            max_tokens=600,
        )
        scored = json.loads(res.choices[0].message.content.strip())
    except Exception as e:
        log.warning(f"score_news {ticker}: {e}")
        return []

    items = []
    for s in scored:
        idx = s.get("index", 1) - 1
        if idx < 0 or idx >= len(candidates):
            continue
        h = candidates[idx]
        items.append(NewsItem(
            ticker=ticker,
            title=h["title"],
            source=h["source"],
            link=h["link"],
            importance=float(s.get("importance", 0)),
            summary=s.get("summary", h["title"][:30]),
            sentiment=s.get("sentiment", "neutral"),
        ))
    return items


def scan_ticker_news(
    tickers: list[str],
    importance_threshold: float = 0.6,
) -> list[NewsItem]:
    """全監視銘柄のニュースをスキャンし、重要度閾値超えのみ返す"""
    headlines = _fetch_all_headlines()
    if not headlines:
        return []

    all_items: list[NewsItem] = []
    for ticker in tickers:
        items = _score_news_for_ticker(headlines, ticker)
        all_items.extend(i for i in items if i.importance >= importance_threshold)

    return sorted(all_items, key=lambda x: x.importance, reverse=True)


def format_ticker_news_message(items: list[NewsItem]) -> str:
    if not items:
        return ""
    lines = ["📰 銘柄ニュースアラート"]
    for item in items[:8]:
        sent_icon = {"positive": "📈", "negative": "📉", "neutral": "➡️"}.get(
            item.sentiment, "")
        lines.append(
            f"{sent_icon} [{item.ticker}] {item.summary}\n"
            f"   重要度: {'★' * int(item.importance * 5)}  ({item.source})"
        )
    return "\n\n".join(lines)
