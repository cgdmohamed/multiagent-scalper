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

def test_disabled_strategies_do_not_emit():
    lab=StrategyLab()
    # Momentum conditions would previously fire TREND_SCALP and MOMENTUM_BREAKOUT.
    changed=lab.observe(Book("BTCUSDT",100,100.01,1000,300,1_000_000,1_000_000,1),40,25)
    names={v["strategy"] for v in changed}
    assert "TREND_SCALP" in names
    for name in ("MOMENTUM_BREAKOUT","TREND_ADX_FILTER","TREND_ALL_CONFIRMATIONS","EMA_PULLBACK_9_21","ORDERBOOK_PRESSURE_PROXY"):
        assert name not in names

def test_disabled_orderbook_pressure_not_emitted():
    lab=StrategyLab()
    lab.last_quotes["BTCUSDT"]=(999_000,100)
    # A fast 100bps mid move with aligned imbalance would fire ORDERBOOK_PRESSURE_PROXY.
    changed=lab.observe(Book("BTCUSDT",101,101.01,1000,300,1_000_000,1_000_000,1),0,0)
    assert not [v for v in changed if v["strategy"]=="ORDERBOOK_PRESSURE_PROXY"]

def test_disabled_research_hypotheses_not_emitted():
    lab=StrategyLab()
    changed=lab.observe(Book("BTCUSDT",100,100.01,1000,300,1_000_000,1_000_000,1),40,25,
        indicators={"research_hypotheses":{"EMA_PULLBACK_9_21":"LONG","SESSION_VWAP_PULLBACK":"LONG"},"research_context":{"bar_at_ms":1}})
    names={v["strategy"] for v in changed}
    assert "EMA_PULLBACK_9_21" not in names
    assert "SESSION_VWAP_PULLBACK" in names

def test_pending_disabled_samples_still_measured():
    lab=StrategyLab()
    start=1_000_000
    # Emit before disabling semantics matter here: inject a legacy pending sample directly.
    lab.pending.append({"strategy":"MOMENTUM_BREAKOUT","symbol":"BTCUSDT","direction":"LONG","at_ms":start,"entry":100,"cost_bps":24,"returns":{}})
    changed=lab.observe(Book("BTCUSDT",101,101.01,1000,300,start+900001,start+900001,2),0,0)
    measured=[v for v in changed if v["strategy"]=="MOMENTUM_BREAKOUT"]
    assert measured and measured[0]["returns"]["15m"]>0
