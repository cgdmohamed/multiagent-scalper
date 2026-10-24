from app.research_coordinator import research_cycle

def bars(n=520):
    return [(i*60000,100.,100.6,99.4,100.15,10.) for i in range(n)]

def signal(i):
    return {"symbol":"BTCUSDT","strategy":"TREND_SCALP",
            "direction":"LONG","at_ms":i*60000+20000,"cost_bps":25.}

def test_research_cycle_is_fail_closed():
    report=research_cycle([signal(i) for i in range(20,480,15)],
                          {"BTCUSDT":bars()})
    assert report["execution_authority"]=="NONE"
    assert report["mode"]=="RESEARCH_ONLY"
    assert report["summary"]["promoted"]==0
    assert report["hypothesis_reviews"]
    assert all(r["eligible_for_paper"] is False for r in report["hypothesis_reviews"])
    assert all(r["chief_agent"]["can_promote"] is False for r in report["hypothesis_reviews"])

def test_empty_research_cycle_is_safe():
    report=research_cycle([],{})
    assert report["summary"]["reviewed"]==0
    assert report["hypothesis_reviews"]==[]
