from types import SimpleNamespace
from app.experimental_paper import ExperimentalPaper

def book(ms,price=100.,symbol="DOGEUSDT"):
    return SimpleNamespace(symbol=symbol,bid=price-.01,ask=price+.01,
                           spread_bps=2.,received_ms=ms)

def signal(ms):
    return {"id":"test:1","symbol":"DOGEUSDT","strategy":"EXECUTED_CVD_CONFIRM",
            "direction":"LONG","at_ms":ms}

def test_virtual_paper_auto_arms_and_rejects_non_meme(tmp_path):
    ms=1_800_000_000_000
    p=ExperimentalPaper(tmp_path/"test.sqlite")
    p.on_quote(book(ms,symbol="BTCUSDT"),ms,[signal(ms)])
    assert p.position is None
    assert p.enabled
    assert p.status()["mode"]=="EXPERIMENTAL_PAPER_ONLY"

def test_entry_exit_persist_and_no_auto_resume(tmp_path):
    ms=1_800_000_000_000;db=tmp_path/"test.sqlite"
    p=ExperimentalPaper(db);p.control(True)
    p.on_quote(book(ms),ms,[signal(ms)])
    assert p.position is not None
    assert p.position["margin"]<=100.
    assert p.position["symbol"]=="DOGEUSDT"
    p.control(False)
    # Pausing entries does not orphan an existing virtual position.
    p.on_quote(book(ms+16*60000),ms+16*60000,[])
    assert p.position is None
    assert p.trades[-1]["type"]=="CLOSE"
    restored=ExperimentalPaper(db)
    assert not restored.enabled
    assert restored.position is None
    assert len(restored.trades)==2

def test_invalid_spread_rejects_entry(tmp_path):
    ms=1_800_000_000_000
    p=ExperimentalPaper(tmp_path/"test.sqlite");p.control(True)
    b=book(ms);b.spread_bps=10.
    p.on_quote(b,ms,[signal(ms)])
    assert p.position is None
