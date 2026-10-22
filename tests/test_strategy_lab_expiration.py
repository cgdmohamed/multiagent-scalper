from app.strategy_lab import StrategyLab
from app.core import Book

def test_old_pending_without_quote_is_not_a_loss():
    lab=StrategyLab()
    lab.observe(Book("BTCUSDT",100,100.01,1000,100,1_000_000,1_000_000,1),40,20)
    assert lab.pending
    changed=lab.expire_pending(1_000_000+21*60*1000)
    assert changed
    assert all(r["measurement_status"]=="EXPIRED_NO_FRESH_QUOTE" for r in changed)
    assert all("15m" not in r["returns"] for r in changed)
    assert not lab.pending
    assert lab.report()["strategies"]["TREND_SCALP"]["expired_no_quote"]==1

def test_new_signal_keeps_pending():
    lab=StrategyLab()
    lab.observe(Book("BTCUSDT",100,100.01,1000,100,1_000_000,1_000_000,1),40,20)
    assert lab.expire_pending(1_000_000+10*60*1000)==[]
    assert lab.pending
