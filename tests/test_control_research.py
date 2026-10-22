"""Regression guards: controls must never unlock research-only trading."""
from app.main import app,engine
from app.capital_guardian import inspect

def test_research_only_gate_remains_after_control_changes():
    assert engine.research_only is True
    book=Book("BTCUSDT",100,100.01,1000,1000,1_000_000,1_000_000,100)
    assert "RESEARCH_ONLY_NO_ENTRIES" in engine.gates(book,100)

def test_control_endpoints_registered():
    found={(r.path,m) for r in app.routes for m in getattr(r,"methods",set())}
    for path in ("/control/run","/control/pause","/control/stop","/control/start"):
        assert (path,"POST") in found

def test_capital_guardian_still_limits_trade_risk():
    guard=inspect(engine)
    assert guard["max_risk_per_trade_pct"]==.1
    assert guard["daily_loss_limit_pct"]==.5
