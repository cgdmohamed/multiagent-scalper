"""Regression: the live-feed indicator snapshot must resolve its strategy evaluator."""
from app.research_indicators import ResearchIndicators

def test_snapshot_can_evaluate_regime_strategies():
    indicators=ResearchIndicators()
    for i in range(120):
        price=100+i*0.01
        indicators.ingest_closed_candle("BTCUSDT",i*60000,price+1,price-1,price,100+i)
    result=indicators.snapshot("BTCUSDT",120*60000)
    assert result["technical"]["ready"] is True
    assert result["research_context"]["state"]=="READY"
    assert isinstance(result["research_hypotheses"],dict)
