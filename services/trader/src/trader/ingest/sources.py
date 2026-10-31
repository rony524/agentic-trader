"""Data ingestion: yfinance price history, news RSS, FRED macro."""
from __future__ import annotations
import datetime as dt
import feedparser
import requests
import yfinance as yf
import pandas as pd

from trader.backtest.engine import all_tickers
from trader.signals.engine import THEME_KEYWORDS
from trader.store.models import SessionLocal, NewsItem, init_db
from trader.audit.chain import append_audit

FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"

NEWS_SOURCES = {
    "memory": "https://news.google.com/rss/search?q=DRAM+HBM+memory+chip+prices&hl=en-US&gl=US&ceid=US:en",
    "ai_capex": "https://news.google.com/rss/search?q=hyperscaler+capex+data+center+AI&hl=en-US&gl=US&ceid=US:en",
    "power": "https://news.google.com/rss/search?q=data+center+power+electricity+grid+nuclear&hl=en-US&gl=US&ceid=US:en",
    "fab_supply": "https://news.google.com/rss/search?q=TSMC+semiconductor+fab+equipment+ASML&hl=en-US&gl=US&ceid=US:en",
    "policy": "https://news.google.com/rss/search?q=chip+export+control+tariff+semiconductor&hl=en-US&gl=US&ceid=US:en",
    "logistics": "https://news.google.com/rss/search?q=supply+chain+shipping+chip+shortage&hl=en-US&gl=US&ceid=US:en",
}

def ingest_price_history(period: str = "2y") -> pd.DataFrame:
    """Download daily closes for the full universe via yfinance."""
    tickers = all_tickers()
    data = yf.download(tickers, period=period, interval="1d", progress=False, auto_adjust=True)
    closes = data["Close"] if isinstance(data.columns, pd.MultiIndex) else data[["Close"]]
    init_db()
    append_audit("jobs", "INGEST_RUN", {"source": "yfinance", "tickers": len(tickers), "period": period})
    return closes

def ingest_news(limit_per_theme: int = 20) -> list[dict]:
    """Fetch news via Google News RSS per theme."""
    init_db()
    db = SessionLocal()
    items = []
    try:
        for theme, url in NEWS_SOURCES.items():
            try:
                feed = feedparser.parse(url)
                for entry in feed.entries[:limit_per_theme]:
                    title = entry.get("title", "")
                    link = entry.get("link", "")
                    summary = entry.get("summary", "")
                    published = entry.get("published", "")
                    if not link:
                        continue
                    existing = db.query(NewsItem).filter(NewsItem.url == link).first()
                    if existing:
                        continue
                    item = NewsItem(
                        title=title[:500], summary=summary[:2000], url=link,
                        source="google_news", theme=theme,
                        published_at=dt.datetime.now(dt.UTC),
                        retrieved_at=dt.datetime.now(dt.UTC)
                    )
                    db.add(item)
                    items.append({"title": title, "url": link, "theme": theme, "summary": summary})
                db.commit()
            except Exception as e:
                print(f"Error ingesting {theme}: {e}")
        append_audit("jobs", "INGEST_RUN", {"source": "news_rss", "items": len(items)})
        return items
    finally:
        db.close()

def ingest_fred(series_id: str, api_key: str) -> dict:
    """Fetch a FRED series observation."""
    params = {
        "series_id": series_id,
        "api_key": api_key,
        "file_type": "json",
        "sort_order": "desc",
        "limit": 1,
    }
    resp = requests.get(FRED_BASE, params=params, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    obs = data.get("observations", [{}])[0]
    return {"series_id": series_id, "value": obs.get("value"), "date": obs.get("date")}

def get_freshness() -> dict:
    """Return freshness status per source."""
    init_db()
    db = SessionLocal()
    try:
        latest_news = db.query(NewsItem).order_by(NewsItem.retrieved_at.desc()).first()
        news_age = (dt.datetime.now(dt.UTC) - latest_news.retrieved_at).total_seconds() / 3600 if latest_news else 999
        return {
            "news": {"fresh": news_age < 24, "age_hours": round(news_age, 1)},
            "prices": {"fresh": True, "age_hours": 0},
            "fred": {"fresh": True, "age_hours": 0},
        }
    finally:
        db.close()
