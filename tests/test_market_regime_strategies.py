from app.market_regime_strategies import evaluate,NAMES
from app.research_indicators import ResearchIndicators

def test_four_hypotheses_safe_with_missing_candles():
    signals,meta=evaluate([],{"ready":False})
    assert signals=={} and meta["state"]=="NOT_READY"
    assert len(NAMES)==4

def test_full_closed_ohlcv_history_does_not_raise():
    ind=ResearchIndicators()
    for i in range(120):
        high=101+i*.01
        low=99+i*.01
        close=100+i*.01
        ind.ingest_closed_candle("BTCUSDT",i*60000,high,low,close,100+i)
    data=ind.snapshot("BTCUSDT",120*60000)
    assert data["closed_1m_bars"]==120
    assert data["technical"]["ready"] is True
    assert data["research_context"]["state"]=="READY"
    assert set(data["research_hypotheses"]).issubset(set(NAMES))

def test_gap_cannot_trigger_stale_candle_signal():
    ind=ResearchIndicators()
    for i in range(120):
        ts=(i+1)*60000 if i>=110 else i*60000
        ind.ingest_closed_candle("BTCUSDT",ts,101,99,100,100)
    data=ind.snapshot("BTCUSDT",121*60000)
    assert data["research_hypotheses"]=={}
    assert data["research_context"]["state"]=="GAPPED_CANDLES"
