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

def test_futures_does_not_require_obsolete_tick_warmup():
    e=setup_engine("SHORT")
    e.history["BTCUSDT"].clear()
    d=e.evaluate(book("SHORT"),600000)
    assert d is not None
    assert "INSUFFICIENT_HISTORY" not in d.reasons
    assert d.market["direction"]=="SHORT"

def test_conflicting_timeframes_reported_explicitly():
    e=setup_engine("LONG")
    e.candles["BTCUSDT"]["3"].clear()
    for i in range(3):
        e.on_candle("BTCUSDT","3",i*180000,100-i)
    d=e.evaluate(book("LONG"),600000)
    assert "TREND_TIMEFRAMES_CONFLICT" in d.reasons
    assert d.market["direction"] is None

def test_position_analytics_short_and_realized_totals():
    e=setup_engine("SHORT")
    b=book("SHORT")
    e._enter(b,600000,"analytics-short","SHORT")
    p=e.positions["BTCUSDT"]
    e.books["BTCUSDT"]=Book("BTCUSDT",p.entry*.98,p.entry*.9801,100,100,601000,601000,12)
    analytics=e.position_analytics()["BTCUSDT"]
    assert analytics["unrealized_pnl"]>0
    assert analytics["estimated_exit_fee"]>0
    assert e.status()["unrealized_pnl"]>0
    e._exit(e.books["BTCUSDT"],601000)
    status=e.status()
    assert status["realized_pnl"]>0
    assert status["unrealized_pnl"]==0
    assert status["closed_trades"]==1

def test_short_marked_loss_when_price_rises():
    e=setup_engine("SHORT")
    b=book("SHORT")
    e._enter(b,600000,"analytics-loss","SHORT")
    p=e.positions["BTCUSDT"]
    e.books["BTCUSDT"]=Book("BTCUSDT",p.entry*1.01,p.entry*1.0101,100,100,601000,601000,12)
    assert e.position_analytics()["BTCUSDT"]["unrealized_pnl"]<0
