"""Observation-only short-horizon surge radar, using executed public trades."""
from collections import defaultdict, deque
import time

class OpportunityRadar:
    def __init__(self):
        self.tape=defaultdict(lambda:deque(maxlen=1200))
        self.alerts=deque(maxlen=120)
        self.last_alert={}
        self.tracked={}
        self.count=0
        self.watchlist=[]

    def set_watchlist(self,symbols):
        self.watchlist=list(symbols)
        active=set(symbols)
        for symbol in list(self.tape):
            if symbol not in active:
                del self.tape[symbol]

    def ingest(self, symbol, trades):
        tape=self.tape[symbol]
        now=int(time.time()*1000)
        for trade in trades:
            try:
                price=float(trade["p"]); qty=float(trade["v"])
                ts=int(trade["T"])
                side=trade["S"]
                if price<=0 or qty<=0 or side not in ("Buy","Sell") or abs(now-ts)>120000: continue
                identifier=str(trade.get("i",symbol+":"+str(ts)+":"+str(price)+":"+str(qty)))
                if identifier in self.tracked:continue
                self.tracked[identifier]=now
                tape.append((ts,price,price*qty,side))
            except (KeyError,TypeError,ValueError):continue
        if len(self.tracked)>10000:
            self.tracked={k:v for k,v in self.tracked.items() if now-v<120000}
        while tape and now-tape[0][0]>120000:tape.popleft()
        self._evaluate(symbol,now)

    def _evaluate(self,symbol,now):
        tape=self.tape[symbol]
        if len(tape)<12 or now-self.last_alert.get(symbol,0)<60000:return
        recent=[t for t in tape if now-t[0]<=15000]
        prior=[t for t in tape if 15000<now-t[0]<=75000]
        if len(recent)<8 or len(prior)<8:return
        volume=sum(t[2] for t in recent)
        prior_rate=sum(t[2] for t in prior)/60
        multiple=(volume/15)/prior_rate if prior_rate>0 else 0
        base=next((t[1] for t in recent),None)
        if not base:return
        change=(recent[-1][1]/base-1)*100
        buy=sum(t[2] for t in recent if t[3]=="Buy")
        flow=(buy/volume) if volume else .5
        if abs(change)<0.30 or multiple<3 or not ((change>0 and flow>=.68) or (change<0 and flow<=.32)):return
        alert={"symbol":symbol,"detected_at_ms":now,"direction":"UP" if change>0 else "DOWN",
               "price":recent[-1][1],"change_15s_pct":round(change,4),
               "relative_volume":round(multiple,2),"aggressive_buy_pct":round(flow*100,1),
               "notional_15s":round(volume,2),"observations":{},
               "status":"MONITORING","mode":"OBSERVE_ONLY"}
        self.alerts.appendleft(alert);self.last_alert[symbol]=now;self.count+=1

    def mark(self,symbol,price,now=None):
        now=now or int(time.time()*1000)
        for alert in self.alerts:
            if alert["symbol"]!=symbol:continue
            age=now-alert["detected_at_ms"]
            for label,delay in (("30s",30000),("1m",60000),("5m",300000)):
                if age>=delay and label not in alert["observations"] and price>0:
                    alert["observations"][label]=round((price/alert["price"]-1)*100,4)
            if len(alert["observations"])==3:alert["status"]="COMPLETE"

    def status(self):
        return {"mode":"OBSERVE_ONLY","watched_symbols":len(self.watchlist),"watchlist":list(self.watchlist),
                "total_alerts_this_run":self.count,"alerts":list(self.alerts)[:40],
                "criteria":"15s move >=0.30%; relative traded notional >=3x previous 60s rate; direction-aligned aggressive flow >=68%; 60s cooldown. Research thresholds, not validated signals.",
                "limitations":"Public trades only, no whale identity attribution; no liquidation or orderbook wall confirmation; 5m observation requires a later price update."}
