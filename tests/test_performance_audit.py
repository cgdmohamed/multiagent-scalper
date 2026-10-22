from app.performance import cooldown_study, account_audit

def test_cooldown_windows_are_observational():
    trades=[
      {"event":"OPEN","symbol":"ALTUSDT","timestamp":"2026-10-22T02:00:00+00:00"},
      {"event":"CLOSE","symbol":"ALTUSDT","reason":"STOP","timestamp":"2026-10-22T02:00:20+00:00","pnl":-1.3},
      {"event":"OPEN","symbol":"ALTUSDT","timestamp":"2026-10-22T02:02:10+00:00"},
      {"event":"OPEN","symbol":"BTCUSDT","timestamp":"2026-10-22T02:02:15+00:00"},
      {"event":"OPEN","symbol":"ALTUSDT","timestamp":"2026-10-22T02:04:00+00:00"},
    ]
    result=cooldown_study(trades)
    assert result["windows"]["3m"]["entries_within_cooldown"]==1
    assert result["windows"]["5m"]["entries_within_cooldown"]==2
    assert result["mode"]=="OBSERVATIONAL_ONLY"

def test_audit_marks_theoretical_equity_as_non_authoritative():
    result=account_audit([{"event":"CLOSE","symbol":"X","pnl":-3.53}],1000,{},1000)
    assert result["theoretical_flat_equity"]==996.47
    assert result["theoretical_equity_is_authoritative"] is False
