"""Regression: rotating watched symbols must have enough preloaded bars for ADX."""
from app.technical_indicators import snapshot

def test_20_bars_were_not_enough():
    bars=[(i*60000,101+i*.01,99+i*.01,100+i*.01) for i in range(20)]
    assert snapshot(bars)["ready"] is False

def test_120_preloaded_closed_bars_are_enough():
    bars=[(i*60000,101+i*.01,99+i*.01,100+i*.01) for i in range(120)]
    result=snapshot(bars)
    assert result["ready"] is True
    assert 0<=result["adx14"]<=100
    assert 0<=result["rsi14"]<=100
