from app.core import PaperEngine, Settings, Book

def book(symbol="BTCUSDT",mid=100, imbalance=0.6, ms=100000, spread=0.02):
    return Book(symbol,mid-spread/2,mid+spread/2,100*(1+imbalance),100*(1-imbalance),ms,ms,5)

def test_stale_and_spread_gates():
    eng=PaperEngine()
    b=book()
    assert "STALE_BOOK" in eng.gates(b,103000)
    b.ask=102
    assert "SPREAD_TOO_WIDE" in eng.gates(b,100000)

def test_no_trade_without_history():
    eng=PaperEngine()
    d=eng.on_book(book(),100000)
    assert d.verdict=="SKIP"
    assert "INSUFFICIENT_HISTORY" in d.reasons
    assert not eng.positions

def test_negative_imbalance_veto():
    eng=PaperEngine()
    for i in range(8): eng.history["BTCUSDT"].append(99+i/10)
    opinions,_=eng.agents(book(imbalance=-.5))
    assert opinions[-1].action=="VETO"

def test_drawdown_circuit_breaker():
    eng=PaperEngine()
    eng.cash=900
    assert "CIRCUIT_BREAKER" in eng.gates(book(),100000)
    assert eng.halted

def test_fee_burden_blocks_trade():
    eng=PaperEngine(Settings(taker_fee_bps=100))
    eng.history["BTCUSDT"].extend([99,99.1,99.2,99.3,99.4,99.5])
    decision=eng.on_book(book(),100000)
    assert "COST_EXCEEDS_HYPOTHETICAL_EDGE" in decision.reasons

def test_risk_budget_position():
    eng=PaperEngine(Settings(taker_fee_bps=0,slippage_bps_per_side=0))
    b=book()
    eng._enter(b,100000,"test")
    p=eng.positions["BTCUSDT"]
    assert p.qty*(p.entry-p.stop)<=eng.cfg.initial_cash*eng.cfg.risk_per_trade+1e-8
