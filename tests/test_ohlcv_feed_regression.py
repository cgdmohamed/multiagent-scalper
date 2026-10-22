"""Regression for the live feed crash caused by expanding closed bars to OHLCV."""
from app.research_indicators import ResearchIndicators

def test_snapshot_with_120_ohlcv_bars_does_not_crash():
    research=ResearchIndicators()
    for i in range(120):
        price=100+i*.01
        research.ingest_closed_candle("BTCUSDT",i*60000,price+1,price-1,price,100+i)
    result=research.snapshot("BTCUSDT",120*60000)
    assert result["closed_1m_bars"]==120
    assert result["technical"]["ready"] is True
    assert result["research_context"]["state"]=="READY"
    assert isinstance(result["research_hypotheses"],dict)
