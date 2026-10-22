from app.capital_guardian import configure_engine,inspect
from app.core import PaperEngine
from app.strategy_optimizer import evaluate

def test_guardian_restricts_engine():
    engine=PaperEngine()
    configure_engine(engine)
    assert engine.cfg.risk_per_trade<=.001
    assert engine.cfg.daily_loss_limit<=.005
    assert engine.cfg.drawdown_limit<=.02
    assert engine.cfg.max_positions==1

def test_daily_loss_denies_entries():
    engine=PaperEngine()
    configure_engine(engine)
    engine.cash=990
    state=inspect(engine)
    assert not state["allowed"]
    assert "DAILY_CAPITAL_GUARD" in state["reasons"]

def test_optimizer_rejects_small_samples():
    samples=[{"symbol":"BTCUSDT","strategy":"X","at_ms":i*900000,"returns":{"15m":100}} for i in range(10)]
    assert evaluate(samples)["qualified"]==[]

def test_optimizer_rejects_negative_out_of_sample():
    samples=[{"symbol":"BTCUSDT","strategy":"X","at_ms":i*900000,"returns":{"15m":10 if i<42 else -30}} for i in range(60)]
    result=evaluate(samples)
    assert len(result["rankings"])==1
    assert result["qualified"]==[]

def test_optimizer_never_authorizes_orders():
    assert evaluate([])["selection_authority"]=="NONE"
