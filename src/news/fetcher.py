import feedparser
import httpx
from datetime import datetime, timezone, timedelta

JST = timezone(timedelta(hours=9))

RSS_FEEDS = {
    "日経電子版": "https://www.nikkei.com/rss/news.rss",
    "Reuters JP": "https://feeds.reuters.com/reuters/JPjpMarketNews",
    "Bloomberg JP": "https://feeds.bloomberg.com/markets/news.rss",
}


def fetch_today_headlines(max_per_feed: int = 3) -> list[dict]:
    """今日の主要ニュースヘッドラインを取得"""
    today = datetime.now(JST).date()
    results = []

    for source, url in RSS_FEEDS.items():
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:max_per_feed]:
                results.append({
                    "source": source,
                    "title": entry.get("title", ""),
                    "link": entry.get("link", ""),
                })
        except Exception:
            continue

    return results


def format_headlines_for_ai(headlines: list[dict]) -> str:
    lines = [f"- [{h['source']}] {h['title']}" for h in headlines]
    return "\n".join(lines)
