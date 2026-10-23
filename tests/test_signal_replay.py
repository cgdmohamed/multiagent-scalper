"""Historical execution approximation using actual Strategy Lab generated signals."""
from app.signal_replay import replay_signals

def _bars(n=25,fall=False):
    result=[]
    for i in range(n):
        price=100-i*.2 if fall else 100+i*.2
        result.append((i*60000,price,price+.05,price-.05,price,1))
    return result

def _signal(at_ms=30000,strategy="TREND_SCALP",direction="LONG"):
    return {"strategy":strategy,"symbol":"BTCUSDT","direction":direction,
            "at_ms":at_ms,"cost_bps":26,"returns":{}}

def test_real_strategy_signal_replayed_not_prototype():
    result=replay_signals([_signal()],{"BTCUSDT":_bars()},hold_minutes=5)
    assert result["results"]["TREND_SCALP"]["trades"]==1
    assert result["execution_authority"]=="NONE"
    assert result["example_trades"][0]["entry_at_ms"]==60000

def test_stops_first_if_stop_and_target_inside_same_bar():
    bars=_bars()
    ts,o,_,_,c,v=bars[1]
    bars[1]=(ts,o,110,90,c,v)
    result=replay_signals([_signal()],{"BTCUSDT":bars},hold_minutes=5)
    assert result["example_trades"][0]["outcome"]=="STOP_FIRST"
    assert result["example_trades"][0]["net_bps"]<0

def test_missing_history_is_not_treated_as_loss():
    result=replay_signals([_signal()],{},hold_minutes=5)
    assert result["results"]["TREND_SCALP"]["trades"]==0
    assert result["skipped"]["NO_HISTORICAL_1M_DATA"]==1

def test_no_future_bars_cannot_be_replayed():
    result=replay_signals([_signal()],{"BTCUSDT":_bars(3)},hold_minutes=5)
    assert result["results"]["TREND_SCALP"]["trades"]==0

def test_all_twelve_strategies_have_separate_results():
    assert len(replay_signals([],{})["results"])==12

def test_all_candle_hypotheses_supported():
    for name in ("EMA_PULLBACK_9_21","SESSION_VWAP_PULLBACK","VOLUME_RANGE_BREAKOUT","RSI_RANGE_REVERSAL"):
        result=replay_signals([_signal(strategy=name)],{"BTCUSDT":_bars()},hold_minutes=5)
        assert result["results"][name]["trades"]==1

def test_history_start_is_explained_instead_of_missing_entry():
    result=replay_signals([_signal()],{"BTCUSDT":_bars()[2:]},hold_minutes=5)
    assert result["skipped"]["SIGNAL_BEFORE_HISTORY"]==1

def test_future_signal_is_not_assigned_historical_entry():
    result=replay_signals([_signal(at_ms=10_000_000)],{"BTCUSDT":_bars()},hold_minutes=5)
    assert result["skipped"]["SIGNAL_AFTER_HISTORY"]==1

def test_signal_requires_next_minute_not_later_candle():
    bars=_bars()
    bars.pop(1)
    result=replay_signals([_signal()],{"BTCUSDT":bars},hold_minutes=5)
    assert result["skipped"]["MISSING_ENTRY_CANDLE"]==1

def test_exit_on_last_available_holding_bar():
    result=replay_signals([_signal()],{"BTCUSDT":_bars(6)},hold_minutes=5)
    assert result["results"]["TREND_SCALP"]["trades"]==1
