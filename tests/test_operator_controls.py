from app.core import Book
from app.futures import FuturesPaperEngine
from app.main import cookie_valid, auth_cookie_value

def test_pause_blocks_new_entry_without_risk_halt():
    engine=FuturesPaperEngine()
    engine.operator_paused=True
    book=Book("BTCUSDT",100,100.01,200,100,1000,1000,1)
    reasons=engine.gates(book,1000)
    assert "OPERATOR_PAUSED" in reasons
    assert engine.halted is False

def test_cookie_requires_admin_token(monkeypatch):
    import app.main as main
    monkeypatch.setattr(main,"ADMIN_TOKEN","testing-secret")
    value=auth_cookie_value()
    assert cookie_valid(value)
    assert not cookie_valid(value+"tampered")
    monkeypatch.setattr(main,"ADMIN_TOKEN","rotated")
    assert not cookie_valid(value)
