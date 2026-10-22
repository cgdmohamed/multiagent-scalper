from app.strategy_lab import StrategyLab
from app.core import Book
from app.futures import FuturesPaperEngine

def test_research_gate_blocks_new_positions():
    e=FuturesPaperEngine()
    e.research_only=True
    b=Book("BTCUSDT",100,100.01,100,80,1000,1000,1)
    assert "RESEARCH_ONLY_NO_ENTRIES" in e.gates(b,1000)

def test_observation_emits_signal_without_order():
    lab=StrategyLab()
    book=Book("BTCUSDT",100,100.01,1000,300,1_000_000,1_000_000,1)
    changed=lab.observe(book,40,25)
    assert len(changed)>=1
    assert all(v["direction"]=="LONG" for v in changed)
    assert lab.report()["mode"]=="RESEARCH_ONLY"

def test_cost_adjusted_forward_price_returns():
    lab=StrategyLab()
    start=1_000_000
    lab.observe(Book("BTCUSDT",100,100.01,1000,300,start,start,1),40,25)
    lab.observe(Book("BTCUSDT",101,101.01,1000,300,start+900001,start+900001,2),0,0)
    rows=lab.report()["strategies"]
    assert rows["TREND_SCALP"]["observed_15m"]==1
    assert rows["TREND_SCALP"]["avg_15m_net_bps"]>0
