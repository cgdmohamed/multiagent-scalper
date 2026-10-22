from app.core import PaperEngine, Book


def make_book(ms=100000, imbalance=0.25):
    return Book("BTCUSDT", 99.99, 100.01, 100*(1+imbalance),
                100*(1-imbalance), ms, ms, 10)


def test_candles_require_completed_history():
    engine = PaperEngine()
    for i in range(3):
        engine.on_candle("BTCUSDT", "1", i*60000, 100+i)
        engine.on_candle("BTCUSDT", "3", i*180000, 100+i)
    assert engine.candle_momentum("BTCUSDT") == (None, None)
    decision = engine.on_book(make_book(), 100000)
    assert "CANDLE_HISTORY_NOT_READY" in decision.reasons


def test_confirmed_trends_make_market_agent_buy():
    engine = PaperEngine()
    for i in range(4):
        engine.on_candle("BTCUSDT", "1", i*60000, 100+i)
    for i in range(3):
        engine.on_candle("BTCUSDT", "3", i*180000, 100+i)
    opinions, momentum = engine.agents(make_book())
    assert momentum > 1
    assert opinions[0].action == "BUY"
    assert opinions[1].action == "BUY"
    assert opinions[3].action != "VETO"


def test_candle_replay_not_double_counted():
    engine = PaperEngine()
    engine.on_candle("BTCUSDT", "1", 1000, 100)
    engine.on_candle("BTCUSDT", "1", 1000, 101)
    engine.on_candle("BTCUSDT", "1", 900, 999)
    assert list(engine.candles["BTCUSDT"]["1"]) == [(1000, 101)]
