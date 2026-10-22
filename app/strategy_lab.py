"""Observation-only strategy comparison; no simulated fills or live order authority."""
from collections import deque
from datetime import datetime,timezone
import time
class StrategyLab:
    def __init__(self):
        self.samples=deque(maxlen=2000)
        self.pending=[]
        self.last_signal={}
        self.last_quotes={}
        self.regimes={}
    def observe(self,book,m1,m3,indicators=None):
        now=book.received_ms
        sym=book.symbol
        mid=book.mid
        previous=self.last_quotes.get(sym)
        self.last_quotes[sym]=(now,mid)
        changed=[]
        for item in list(self.pending):
            if item["symbol"]!=sym:continue
            age=now-item["at_ms"]
            for horizon in (60000,300000,900000):
                key=str(horizon//60000)+"m"
                if age>=horizon and key not in item["returns"]:
                    move=(mid/item["entry"]-1)*(1 if item["direction"]=="LONG" else -1)*10000
                    item["returns"][key]=round(move-item["cost_bps"],3)
                    changed.append(item)
            if age>=900000:
                self.pending.remove(item)
        if m1 is None or m3 is None:return changed
        imbalance=book.imbalance
        regime="TRENDING" if abs(m1)>15 and m1*m3>0 else "CHOPPY" if abs(m1)>10 and m1*m3<=0 else "QUIET" if abs(m1)<8 else "MIXED"
        self.regimes[sym]={"regime":regime,"at_ms":now,"spread_bps":round(book.spread_bps,3)}
        if book.spread_bps>5:return changed
        signals={}
        indicators=indicators or {}
        vwap=indicators.get("vwap_2m")
        atr=indicators.get("atr_1m_14")
        atr_bps=indicators.get("atr_bps")
        recent_cvd=indicators.get("cvd_recent_30s")
        prior_cvd=indicators.get("cvd_prior_90s")
        traded=indicators.get("notional_2m",0)
        sufficient=indicators.get("public_trades",0)>=30 and traded>=25000 and atr_bps is not None
        liquid=book.spread_bps<=3 and sufficient and 8<=atr_bps<=180
        if liquid and recent_cvd is not None and prior_cvd is not None and abs(recent_cvd)>max(5000,abs(prior_cvd)*.4):
            if m1*m3>0 and m1*recent_cvd>0 and abs(m1)>12:
                signals["EXECUTED_CVD_CONFIRM"]="LONG" if m1>0 else "SHORT"
        if liquid and vwap is not None and atr is not None and m1*m3>0:
            distance=(mid-vwap)/atr
            if abs(distance)<=.30 and m1*imbalance>0 and abs(imbalance)>.18:
                signals["VWAP_PULLBACK"]="LONG" if m1>0 else "SHORT"

        if m1*m3>0 and abs(m1)>12 and abs(imbalance)>.18 and m1*imbalance>0:signals["TREND_SCALP"]="LONG" if m1>0 else "SHORT"
        if abs(m1)>30 and abs(m3)>15 and m1*m3>0 and abs(imbalance)>.12 and m1*imbalance>0:signals["MOMENTUM_BREAKOUT"]="LONG" if m1>0 else "SHORT"
        if previous:
            delta=now-previous[0]
            move=(mid/previous[1]-1)*10000 if previous[1]>0 else 0
            if 500<=delta<=30000 and abs(move)>8 and abs(imbalance)>.3 and move*imbalance>0:signals["ORDERBOOK_PRESSURE_PROXY"]="LONG" if move>0 else "SHORT"
        for strategy,direction in signals.items():
            key=(sym,strategy)
            if now-self.last_signal.get(key,-10**15)<15*60*1000:continue
            self.last_signal[key]=now
            item={"strategy":strategy,"symbol":sym,"direction":direction,"at_ms":now,
                  "timestamp":datetime.fromtimestamp(now/1000,timezone.utc).isoformat(),
                  "entry":mid,"cost_bps":round(24+book.spread_bps,2),"regime":regime,
                  "research_indicators":{k:indicators.get(k) for k in ("vwap_2m","cvd_recent_30s","atr_bps","public_trades")},
                  "returns":{}}
            item["id"]=f"{sym}:{strategy}:{now}"
            self.samples.appendleft(item)
            changed.append(item)
            self.pending.append(item)
        return changed
    def report(self):
        stats={}
        for name in ("TREND_SCALP","MOMENTUM_BREAKOUT","ORDERBOOK_PRESSURE_PROXY","EXECUTED_CVD_CONFIRM","VWAP_PULLBACK"):
            rows=[r for r in self.samples if r["strategy"]==name]
            measured=[r["returns"]["15m"] for r in rows if "15m" in r["returns"]]
            stats[name]={"signals":len(rows),"observed_15m":len(measured),
                         "avg_15m_net_bps":round(sum(measured)/len(measured),2) if measured else None,
                         "positive_15m_pct":round(100*sum(x>0 for x in measured)/len(measured),2) if measured else None}
        return {"market_regimes":self.regimes,"mode":"RESEARCH_ONLY","execution":"NONE","indicator_requirements":"30 public trades, 25k USDT executed /2m, <=3bps spread, 14 closed 1m ATR bars, 8-180bps ATR for new strategies","price_basis":"mid_quote","note":"Indicative fixed-horizon net returns, not realized fills or stop/target simulations. Orderbook pressure is not executed trade flow. Samples are checkpointed in SQLite when configured.", "strategies":stats,
                "latest":list(self.samples)[:15]}
