from app.research_indicators import ResearchIndicators
from app.strategy_lab import StrategyLab
from app.core import Book

def test_executed_trade_imbalance_and_vwap():
    m=ResearchIndicators()
    ts=1000000
    trades=[{"T":ts,"p":"100","v":"20","S":"Buy","i":"a"},
            {"T":ts+1,"p":"110","v":"10","S":"Sell","i":"b"}]
    m.ingest_trades("BTCUSDT",trades,ts+10)
    m.ingest_trades("BTCUSDT",trades,ts+10)
    result=m.snapshot("BTCUSDT",ts+10)
    assert result["public_trades"]==2
    assert result["cvd_notional_2m"]==900
    assert 100<result["vwap_2m"]<110

def test_true_range_atr_requires_completed_bars():
    m=ResearchIndicators()
    for i in range(15):
        m.ingest_closed_candle("BTCUSDT",i*60000,110,90,100)
    assert m.snapshot("BTCUSDT",1000000)["atr_1m_14"]==20

def test_new_signals_fail_closed_without_market_data():
    lab=StrategyLab()
    book=Book("BTCUSDT",100,100.01,1000,100,1000000,1000000,1)
    observed=lab.observe(book,40,25,{})
    assert not any(row["strategy"] in ("VWAP_PULLBACK","EXECUTED_CVD_CONFIRM") for row in observed)
