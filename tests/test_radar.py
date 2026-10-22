from app.radar import OpportunityRadar

def test_surge_alert_and_followup(monkeypatch):
    import app.radar as mod
    now=1_800_000_000_000
    monkeypatch.setattr(mod.time,"time",lambda:now/1000)
    radar=OpportunityRadar()
    trades=[]
    # Reference period with modest activity; aggressive buy surge in last 15s.
    for i in range(30):
        trades.append({"p":"100","v":"1","T":now-70000+i*1700,"S":"Buy" if i%2 else "Sell","i":f"old-{i}"})
    for i in range(15):
        trades.append({"p":str(100+i*.05),"v":"5","T":now-14000+i*900,"S":"Buy","i":f"recent-{i}"})
    radar.ingest("BTCUSDT",trades)
    assert len(radar.alerts)==1
    assert radar.alerts[0]["direction"]=="UP"
    assert radar.status()["mode"]=="OBSERVE_ONLY"
    radar.mark("BTCUSDT",101,now+30_000)
    assert radar.alerts[0]["observations"]["30s"]>0
    radar.mark("BTCUSDT",99,now+300_000)
    assert radar.alerts[0]["status"]=="COMPLETE"

def test_no_alert_without_trade_flow_confirmation(monkeypatch):
    import app.radar as mod
    now=1_800_000_000_000
    monkeypatch.setattr(mod.time,"time",lambda:now/1000)
    radar=OpportunityRadar()
    trades=[{"p":"100","v":"1","T":now-70000+i*1700,"S":"Buy","i":f"old-{i}"} for i in range(30)]
    trades += [{"p":str(100+i*.1),"v":"5","T":now-14000+i*900,"S":"Sell","i":f"recent-{i}"} for i in range(15)]
    radar.ingest("BTCUSDT",trades)
    assert radar.status()["total_alerts_this_run"]==0
