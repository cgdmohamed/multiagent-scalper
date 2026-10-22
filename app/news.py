"""Untrusted RSS headline monitor; research-only and never an order authority."""
import asyncio
import hashlib
import os
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from datetime import timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

import httpx

DEFAULT_FEEDS = (
    'https://www.coindesk.com/arc/outboundfeeds/rss/',
    'https://cointelegraph.com/rss',
)
ASSETS = {'BTC': ('bitcoin', 'btc'), 'ETH': ('ethereum', 'ether', 'eth'),
          'SOL': ('solana', 'sol')}
HIGH_IMPACT = re.compile(r'\b(hack|hacked|exploit|breach|bankrupt|liquidation|etf|sec|fed|fomc|interest rate|lawsuit|delist|outage|suspends? withdrawals?|sanctions?)\b', re.I)


def text_of(node, tag):
    child = node.find(tag)
    return (child.text or '').strip() if child is not None else ''


def event_time(raw, now):
    try:
        dt = parsedate_to_datetime(raw)
        return dt.replace(tzinfo=timezone.utc).timestamp() if dt.tzinfo is None else dt.timestamp()
    except (TypeError, ValueError, OverflowError):
        return None  # Do not treat unverified timestamps as fresh news.


def parse_feed(xml_bytes, source, now=None, max_age_hours=24):
    now = time.time() if now is None else now
    if len(xml_bytes) > 1_000_000:
        raise ValueError('feed too large')
    root = ET.fromstring(xml_bytes)
    results = []
    for item in root.findall('.//item')[:100]:
        title = ' '.join(text_of(item, 'title').split())[:240]
        url = text_of(item, 'link')[:600]
        published = event_time(text_of(item, 'pubDate'), now)
        if not title or published is None or published > now + 300 or now - published > max_age_hours * 3600:
            continue
        if urlparse(url).scheme not in ('https', 'http'):
            continue
        key = hashlib.sha256((source+'|'+url+'|'+title).encode()).hexdigest()[:20]
        low = title.lower()
        matches = [asset for asset, aliases in ASSETS.items() if any(re.search(r'(?<![a-z])'+re.escape(a)+r'(?![a-z])', low) for a in aliases)]
        results.append(NewsItem(key,title,url,source,published,matches,bool(HIGH_IMPACT.search(title))))
    return results


@dataclass(frozen=True)
class NewsItem:
    id: str
    title: str
    url: str
    source: str
    published_at: float
    assets: list[str]
    high_impact: bool


class NewsMonitor:
    def __init__(self, feeds=None, interval=180, max_age_hours=24):
        self.feeds = tuple(feeds if feeds is not None else DEFAULT_FEEDS)
        self.interval = max(60, int(interval))
        self.max_age_hours = max_age_hours
        self.items = []
        self.last_update = None
        self.last_error = None
        self.sources_ok = 0

    def related(self, symbol, limit=5):
        base = symbol.removesuffix('USDT').upper()
        return [asdict(x) for x in self.items if not x.assets or base in x.assets][:limit]

    def status(self):
        return {'mode':'SHADOW_ONLY','sources_ok':self.sources_ok,
                'sources_total':len(self.feeds),'last_update':self.last_update,
                'last_error':self.last_error,'items':[asdict(x) for x in self.items[:30]],
                'orders_controlled_by_news':False}

    async def refresh(self, client):
        found = []
        failures = []
        for feed in self.feeds:
            try:
                # Only operator-configured HTTPS feeds, not article URLs from a feed.
                if urlparse(feed).scheme != 'https':
                    raise ValueError('only https feeds allowed')
                resp = await client.get(feed, follow_redirects=False, timeout=8,
                                        headers={'User-Agent':'ScalperResearch/0.5 (+RSS research)'})
                resp.raise_for_status()
                found.extend(parse_feed(resp.content, urlparse(feed).hostname or 'unknown',
                                        max_age_hours=self.max_age_hours))
            except (httpx.HTTPError, ValueError, ET.ParseError) as exc:
                failures.append(f'{urlparse(feed).hostname}:{type(exc).__name__}')
        unique = {i.id:i for i in found}
        if found:
            self.items = sorted(unique.values(), key=lambda x:x.published_at, reverse=True)[:150]
            self.last_update = time.time()
        self.sources_ok = len(self.feeds) - len(failures)
        self.last_error = ', '.join(failures) if failures else None
        return self.status()

    async def loop(self, callback=None):
        async with httpx.AsyncClient() as client:
            while True:
                await self.refresh(client)
                if callback:
                    callback(self.status())
                await asyncio.sleep(self.interval)
