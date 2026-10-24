from app.entry_experiments import experiment, VARIANTS

def bars(n=110,price=100.):
    return [(i*60000,price,price+0.6,price-0.6,price+0.15,10.) for i in range(n)]

def sig(i, cost=25.):
    return {"symbol":"BTCUSDT","strategy":"TREND_SCALP","direction":"LONG",
            "at_ms":i*60000+20000,"cost_bps":cost}

def test_experiments_are_read_only_with_no_promotion():
    result=experiment([sig(i) for i in range(20,470,15)],{"BTCUSDT":bars(500)})
    assert result["results"]
    assert any(row["holdout"]["n"]>0 for row in result["results"])
    assert result["execution_authority"]=="NONE"
    assert result["mode"]=="RESEARCH_ONLY"
    assert "NEXT_OPEN_ATR" in VARIANTS
    assert all(row["eligible_for_paper"] is False for row in result["results"])

def test_research_spread_gate():
    result=experiment([sig(25,29.)],{"BTCUSDT":bars()})
    assert result["skipped"]["SIGNAL_SPREAD_TOO_WIDE"]==1
    assert result["results"]==[]

def test_insufficient_past_atr_never_uses_future():
    result=experiment([sig(5)],{"BTCUSDT":bars()})
    assert result["skipped"]["INSUFFICIENT_PAST_FOR_ATR"]==1

def test_no_history_is_skipped_not_recorded_as_loss():
    result=experiment([sig(25)],{})
    assert result["skipped"]["NO_HISTORY"]==1
