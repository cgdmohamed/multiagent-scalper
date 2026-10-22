from app.paper_eligibility import eligibility

def ready(**overrides):
    values=dict(feed_ok=True,bot_stopped=False,operator_paused=False,risk_halted=False,
        capital_allowed=True,recovery_ok=True,
        qualified_benchmark={"symbol":"BTCUSDT","strategy":"TREND_SCALP"},
        qualified_optimizer=[{"symbol":"BTCUSDT","strategy":"TREND_SCALP"}],
        strategy_bound=True)
    values.update(overrides)
    return eligibility(**values)

def test_missing_qualified_execution_binding_blocks_paper():
    result=ready(strategy_bound=False)
    assert not result["eligible"]
    assert "NO_VALIDATED_STRATEGY_BOUND_TO_EXECUTION_ENGINE" in result["reasons"]

def test_stale_feed_blocks_paper():
    assert not ready(feed_ok=False)["eligible"]

def test_circuit_breaker_blocks_paper():
    assert not ready(risk_halted=True)["eligible"]

def test_candidate_must_match_benchmark():
    assert not ready(qualified_optimizer=[])["eligible"]

def test_all_requirements_must_hold():
    assert ready()["eligible"]

def test_actual_application_does_not_promote_unbound_lab_signals():
    from app.main import PAPER_STRATEGY_BOUND,engine
    assert PAPER_STRATEGY_BOUND is False
    assert engine.research_only is True
