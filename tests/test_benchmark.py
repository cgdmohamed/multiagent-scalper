from app.benchmark import compare,drawdown_pct

def sample(at,ret,direction="LONG",strategy="BREAKOUT"):
    return {"at_ms":at,"symbol":"BTCUSDT","strategy":strategy,
            "entry":100,"direction":direction,"cost_bps":25,
            "returns":{"15m":ret}}

def test_empty_benchmark_is_unproven():
    r=compare([])
    assert r["results"]=={}
    assert r["grid_status"].startswith("NOT_COMPARABLE")

def test_long_matches_buy_and_hold_same_window():
    r=compare([sample(0,50)])
    item=r["results"]["BTCUSDT:BREAKOUT"]
    assert item["samples"]==1
    assert item["net_pct"]==item["hold_same_windows_net_pct"]

def test_short_profit_not_confused_with_long_benchmark():
    r=compare([sample(0,50,"SHORT")])
    item=r["results"]["BTCUSDT:BREAKOUT"]
    assert item["net_pct"]>0
    assert item["hold_same_windows_net_pct"]<0

def test_overlapping_signals_are_skipped():
    r=compare([sample(0,50),sample(60000,50),sample(900000,-80)])
    item=r["results"]["BTCUSDT:BREAKOUT"]
    assert item["samples"]==2
    assert item["max_closed_observation_drawdown_pct"]>0

def test_incomplete_and_invalid_samples_are_ignored():
    r=compare([{"symbol":"BTCUSDT","strategy":"X","returns":{}},sample(0,float("nan"))])
    assert r["results"]=={}
