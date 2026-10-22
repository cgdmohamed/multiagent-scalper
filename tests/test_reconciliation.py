from app.reconciliation import analyze

def test_complete_legacy_pairing_is_not_wallet_authority():
    trades=[
        {"event":"OPEN","symbol":"BTCUSDT","direction":"SHORT","qty":2,"timestamp":"2026-10-22T01:00:00Z"},
        {"event":"CLOSE","symbol":"BTCUSDT","direction":"SHORT","qty":2,"pnl":1.5,"timestamp":"2026-10-22T01:02:00Z"},
    ]
    result=analyze(trades)
    assert result["matched_round_trips"]==1
    assert result["complete_trade_pairing"]
    assert not result["account_reconstruction_trusted"]

def test_unmatched_open_and_duplicate_history_are_reported():
    trades=[
        {"event":"OPEN","symbol":"ALTUSDT","direction":"SHORT","qty":10},
        {"event":"OPEN","symbol":"ALTUSDT","direction":"SHORT","qty":10},
        {"event":"CLOSE","symbol":"ALTUSDT","direction":"SHORT","qty":10,"pnl":-1},
    ]
    result=analyze(trades)
    assert len(result["unmatched_opens"])==1
    assert any(issue["issue"]=="OVERLAPPING_OPEN" for issue in result["issues"])
    assert not result["complete_trade_pairing"]

def test_unmatched_close_detected():
    result=analyze([{"event":"CLOSE","symbol":"DOGEUSDT","direction":"LONG","qty":15,"pnl":-2}])
    assert result["issues"][0]["issue"]=="CLOSE_WITHOUT_MATCHING_OPEN"
