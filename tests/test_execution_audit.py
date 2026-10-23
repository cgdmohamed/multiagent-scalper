"""Unit tests for read-only diagnostic reconciliation."""
from app.execution_audit import execution_audit

def bars(n=24):
    return [(i*60000,100.,100.1,99.9,100.,5.) for i in range(n)]

def signal(at=30000, lab=-17.):
    return {"id":"one","symbol":"BTCUSDT","strategy":"TREND_SCALP",
            "direction":"LONG","at_ms":at,"entry":100.,"cost_bps":26.,
            "regime":"TRENDING","returns":{"15m":lab}}

def test_audit_reconciles_same_signal_and_cost_fields():
    out=execution_audit([signal()],{"BTCUSDT":bars()},hold_minutes=5)
    rec=out["records"][0]
    assert rec["status"]=="REPLAYED"
    assert rec["signal_at_ms"]==30000
    assert rec["entry_at_ms"]==60000
    assert rec["lab_15m_net_bps"]==-17.
    assert rec["fees_bps"]>0
    assert rec["replay_vs_lab_bps"]==round(rec["net_bps"]+17.,3)
    assert rec["modeled_entry_price"]>rec["raw_next_open"]
    assert out["mode"]=="RESEARCH_ONLY"

def test_missing_history_is_separate_from_loss():
    out=execution_audit([signal()],{})
    rec=out["records"][0]
    assert rec["status"]=="NO_HISTORICAL_1M_DATA"
    assert rec.get("net_bps") is None

def test_audit_limits_and_filters():
    sample=[signal(),{**signal(),"id":"other","symbol":"ETHUSDT"}]
    out=execution_audit(sample,{"BTCUSDT":bars()},limit=1,symbol="BTCUSDT")
    assert len(out["records"])==1
    assert out["records"][0]["symbol"]=="BTCUSDT"
