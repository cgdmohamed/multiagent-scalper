from app.futures import FuturesPaperEngine
from app.core import Book
from app.discovery import PairCandidate

def setup_engine(direction):
    e=FuturesPaperEngine()
    e.set_candidates([PairCandidate("BTCUSDT",10000000,2,1,40,5,.01,.001)])
    e.order_manager.allowed_symbols.add("BTCUSDT")
    for i in range(4):
        e.on_candle("BTCUSDT","1",i*60000,100+i if direction=="LONG" else 100-i)
    for i in range(3):
        e.on_candle("BTCUSDT","3",i*180000,100+i if direction=="LONG" else 100-i)
    for _ in range(6):e.history["BTCUSDT"].append(100)
    return e

def book(direction,ms=600000):
    imbalance=.7 if direction=="LONG" else -.7
    return Book("BTCUSDT",99.99,100.01,100*(1+imbalance),100*(1-imbalance),ms,ms,10)

def test_long_and_short_signals():
    for direction in ("LONG","SHORT"):
        e=setup_engine(direction)
        votes,_=e.agents(book(direction))
        assert votes[0].action==("BUY" if direction=="LONG" else "SELL")
        assert votes[1].action==votes[0].action
        assert votes[3].action!="VETO"

def test_short_profit_is_positive_on_price_fall():
    e=setup_engine("SHORT");b=book("SHORT")
    e._enter(b,600000,"short-1","SHORT")
    p=e.positions["BTCUSDT"]
    assert p.direction=="SHORT"
    exit_book=Book("BTCUSDT",p.entry*.97,p.entry*.9701,100,100,601000,601000,11)
    e._exit(exit_book,601000)
    assert e.trades[0]["event"]=="CLOSE"
    assert e.trades[0]["reduce_only"] is True
    assert e.trades[0]["pnl"]>0
    assert e.equity()>1000

def test_long_profit_is_positive_on_price_rise():
    e=setup_engine("LONG");b=book("LONG")
    e._enter(b,600000,"long-1","LONG")
    p=e.positions["BTCUSDT"]
    exit_book=Book("BTCUSDT",p.entry*1.03,p.entry*1.0301,100,100,601000,601000,11)
    e._exit(exit_book,601000)
    assert e.trades[0]["pnl"]>0
