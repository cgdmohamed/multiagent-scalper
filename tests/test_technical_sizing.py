from app.technical_indicators import snapshot
from app.position_sizing import size_position
from app.core import Book
from app.strategy_lab import StrategyLab

def test_technicals_are_closed_bar_only_and_need_warmup():
    assert not snapshot([(0,100,99,99.5)])["ready"]
    bars=[(i*60000,101+i*.2,99+i*.2,100+i*.2) for i in range(60)]
    result=snapshot(bars)
    assert result["ready"]
    assert 0<=result["rsi14"]<=100
    assert result["adx14"]>=0
    assert result["macd_hist"] is not None

def test_dynamic_size_is_bounded_by_risk_and_liquidity():
    v=size_position(equity=1000,cash=1000,entry=100,stop=99.5,
          qty_step=.001,min_notional=10,risk_fraction=.001,fee_bps=10,
          slippage_bps=2,allocation_fraction=.20,total_free_notional=400,
          available_depth_notional=10000)
    assert v["allowed"]
    assert v["estimated_stop_loss"]<=1
    assert v["notional"]<=100.00001

def test_min_order_cannot_override_capital_guard():
    v=size_position(equity=1000,cash=1000,entry=100,stop=90,
          qty_step=1,min_notional=50,risk_fraction=.001,fee_bps=10,
          slippage_bps=2,allocation_fraction=.20,total_free_notional=400)
    assert not v["allowed"]

def test_technical_variants_do_not_emit_without_indicators():
    lab=StrategyLab()
    b=Book("BTCUSDT",100,100.01,500,100,1000000,1000000,10)
    rows=lab.observe(b,40,30,{})
    assert not any("FILTER" in r["strategy"] or "CONFIRMATIONS" in r["strategy"] for r in rows)
