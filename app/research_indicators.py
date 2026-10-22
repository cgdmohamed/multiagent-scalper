"""Bounded public-trade CVD/VWAP and closed-candle ATR for research only."""
from collections import defaultdict,deque
from datetime import datetime,timezone
import math
import time
from .technical_indicators import snapshot as technical_snapshot
from .market_regime_strategies import evaluate as research_strategy_evaluate

class ResearchIndicators:
    def __init__(self):
        self.trades=defaultdict(lambda:deque(maxlen=5000))
        self.trade_ids=defaultdict(lambda:deque(maxlen=6000))
        self.candles=defaultdict(lambda:deque(maxlen=120))
    def ingest_trades(self,symbol,rows,now_ms=None):
        now_ms=now_ms or int(time.time()*1000)
        tape=self.trades[symbol]; seen=self.trade_ids[symbol]
        known=set(seen)
        parsed=[]
        for t in rows:
            try:
                ts=int(t["T"]); price=float(t["p"]); size=float(t["v"]);side=t["S"]
                ident=str(t.get("i") or f"{ts}:{price}:{size}:{side}")
                if ident in known or side not in ("Buy","Sell") or not 0<price or not 0<size or not all(map(math.isfinite,(price,size))) or abs(ts-now_ms)>120000:continue
                parsed.append((ts,ident,price,size,side))
                known.add(ident)
            except (ValueError,KeyError,TypeError):continue
        for ts,ident,price,size,side in sorted(parsed):
            tape.append((ts,price,price*size,1 if side=="Buy" else -1))
            seen.append(ident)
        while tape and now_ms-tape[0][0]>300000:tape.popleft()
    def ingest_closed_candle(self,symbol,start,high,low,close,volume=0):
        values=(high,low,close,volume)
        if not all(isinstance(x,(float,int)) and math.isfinite(x) and x>0 for x in values) or high<low or not low<=close<=high or volume<0:return
        bars=self.candles[symbol]
        if bars and start<bars[-1][0]:return
        if bars and start==bars[-1][0]:bars[-1]=(start,high,low,close,volume)
        else:bars.append((start,high,low,close,volume))
    def snapshot(self,symbol,now_ms):
        tape=[r for r in self.trades.get(symbol,()) if 0<=now_ms-r[0]<=120000]
        notional=sum(r[2] for r in tape)
        signed=sum(r[2]*r[3] for r in tape)
        # VWAP computed from last 2min of *executed* trades, not a session VWAP.
        vwap=sum(r[1]*r[2] for r in tape)/notional if notional else None
        recent=sum(r[2]*r[3] for r in tape if now_ms-r[0]<=30000)
        previous=sum(r[2]*r[3] for r in tape if 30000<now_ms-r[0]<=120000)
        candles=list(self.candles.get(symbol,()))
        trs=[]
        for previous_bar,bar in zip(candles,candles[1:]):
            high,low=bar[1],bar[2]
            prev_close=previous_bar[3]
            trs.append(max(high-low,abs(high-prev_close),abs(low-prev_close)))
        atr=sum(trs[-14:])/14 if len(trs)>=14 else None
        close=candles[-1][3] if candles else None
        technical=technical_snapshot(candles)
        hypotheses,context=research_strategy_evaluate(candles,technical)
        return {"research_hypotheses":hypotheses,"research_context":context,"vwap_2m":vwap,"cvd_notional_2m":round(signed,3) if tape else None,
                "cvd_recent_30s":round(recent,3) if tape else None,
                "cvd_prior_90s":round(previous,3) if tape else None,
                "notional_2m":round(notional,3),"atr_1m_14":atr,
                "atr_bps":round(atr/close*10000,2) if atr and close else None,
                "public_trades":len(tape),"closed_1m_bars":len(candles),
                "technical":technical}
