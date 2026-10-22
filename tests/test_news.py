import asyncio
import httpx
from app.news import parse_feed, NewsMonitor


def sample(now):
    from email.utils import formatdate
    return f'''<rss><channel>
<item><title>Bitcoin ETF decision draws scrutiny</title><link>https://example.com/a</link><pubDate>{formatdate(now-60,usegmt=True)}</pubDate></item>
<item><title>Solana network outage reported</title><link>https://example.com/b</link><pubDate>{formatdate(now-90,usegmt=True)}</pubDate></item>
<item><title>Old news</title><link>https://example.com/c</link><pubDate>{formatdate(now-90000,usegmt=True)}</pubDate></item>
<item><title>Malicious url</title><link>javascript:alert(1)</link><pubDate>{formatdate(now-60,usegmt=True)}</pubDate></item>
</channel></rss>'''.encode()

def test_parse_relevance_and_staleness():
    now=1800000000
    items=parse_feed(sample(now),'example.com',now=now)
    assert len(items)==2
    assert items[0].assets==['BTC'] and items[0].high_impact
    assert items[1].assets==['SOL'] and items[1].high_impact

def test_undated_excluded():
    assert parse_feed(b'<rss><channel><item><title>News</title><link>https://x.org</link></item></channel></rss>','x')==[]

def test_large_payload_fails():
    import pytest
    with pytest.raises(ValueError):parse_feed(b'x'*1000001,'x')

def test_monitor_feed_failures_and_shadow_only():
    def handler(req):return httpx.Response(503)
    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            m=NewsMonitor(feeds=['https://example.com/rss'])
            result=await m.refresh(client)
            assert result['sources_ok']==0
            assert result['orders_controlled_by_news'] is False
    asyncio.run(go())

def test_related_market_news():
    from app.news import NewsItem
    m=NewsMonitor(feeds=[])
    m.items=[NewsItem('a','Bitcoin','https://x.org/a','x',1,['BTC'],True),NewsItem('b','Broad','https://x.org/b','x',1,[],False)]
    assert [i['id'] for i in m.related('SOLUSDT')]==['b']
