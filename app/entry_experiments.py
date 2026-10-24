"""Non-executing entry/stop experiments with chronological holdout.

Only uses recorded signals and stored 1m candles; never reconstructs historical
CVD or orderbook. No signal promotion, orders, or wallet mutation.
"""
from bisect import bisect_right
from collections import defaultdict
from .signal_replay import _replay_one

VARIANTS=("NEXT_OPEN_FIXED","CONFIRM_CLOSE_FIXED","PULLBACK_LIMIT_FIXED",
          "NEXT_OPEN_ATR")
def _atr(bars,i,n=14):
    if i<n+1:return None
    ranges=[]
    for j in range(i-n,i):
        _,_,h,l,c,_=bars[j]
        prev=bars[j-1][4]
        ranges.append(max(h-l,abs(h-prev),abs(l-prev))/c*10000)
    return sum(ranges)/n

def experiment(signals,bars_by_symbol,*,fee_bps=10,slippage_bps=2,hold_minutes=15):
    grouped=defaultdict(list); skipped=defaultdict(int)
    indexed={sym:(ordered,[b[0] for b in ordered]) for sym,rows in bars_by_symbol.items()
             if (ordered:=sorted(rows,key=lambda b:b[0]))}
    for signal in sorted(signals,key=lambda s:s.get("at_ms",0)):
        sym=signal.get("symbol")
        if sym not in indexed:skipped["NO_HISTORY"]+=1;continue
        bars,start=indexed[sym]
        try:
            at=int(signal["at_ms"])
            side=1 if signal["direction"]=="LONG" else -1
            if signal["direction"] not in ("LONG","SHORT"):continue
        except (KeyError,TypeError,ValueError):continue
        # Historical signal-time spread is recorded in cost_bps. Never use
        # current market conditions to retroactively admit old observations.
        try: spread=max(0.,float(signal.get("cost_bps",24))-24.)
        except (TypeError,ValueError):skipped["UNKNOWN_SIGNAL_SPREAD"]+=1;continue
        if spread>3.:
            skipped["SIGNAL_SPREAD_TOO_WIDE"]+=1;continue
        i=bisect_right(start,at)
        if i>=len(bars) or start[i]-at>60000:
            skipped["NO_NEXT_ENTRY"]+=1;continue
        # ATR is computed strictly from completed candles before entry.
        atr=_atr(bars,i)
        for variant in VARIANTS:
            idx=i
            stop=45.
            if variant=="NEXT_OPEN_ATR":
                if atr is None:
                    skipped["INSUFFICIENT_PAST_FOR_ATR"]+=1;continue
                stop=max(30.,min(180.,atr*1.5))
            if variant=="CONFIRM_CLOSE_FIXED":
                # Confirmation uses candle i close; order starts at i+1 open.
                if i+1>=len(bars) or bars[i+1][0]!=start[i]+60000:continue
                confirm=side*(bars[i][4]-bars[i][1])
                if confirm<=0:continue
                idx=i+1
            if variant=="PULLBACK_LIMIT_FIXED":
                # Hypothetical passive entry at next candle open; only if
                # favorable intrabar move occurs. No within-bar hindsight fills:
                # entry starts at the FOLLOWING candle, conservatively.
                if i+1>=len(bars) or bars[i+1][0]!=start[i]+60000:continue
                threshold=bars[i][1]*(1-side*10/10000)
                touched=bars[i][3]<=threshold if side==1 else bars[i][2]>=threshold
                if not touched:continue
                idx=i+1
            if idx+hold_minutes>len(bars):continue
            if any(bars[j][0]!=bars[j-1][0]+60000 for j in range(idx+1,idx+hold_minutes)):
                skipped["CANDLE_GAP"]+=1;continue
            # Pass timestamp preceding entry open; _replay_one uses bisect_right.
            synthetic={**signal,"at_ms":start[idx]-1}
            result,error=_replay_one(synthetic,bars,start,fee_bps,slippage_bps,
                                     stop,100.,hold_minutes)
            if error:
                skipped[error]+=1;continue
            grouped[(sym,signal["strategy"],variant)].append(
                (at,result["net_bps"],result["outcome"],stop))
    rows=[]
    for (sym,strategy,variant),data in grouped.items():
        # Sort chronologically, enforce nonoverlapping 15m observations.
        selected=[];last=-10**30
        for at,net,outcome,stop in sorted(data):
            if at-last<hold_minutes*60000:continue
            selected.append((at,net,outcome,stop));last=at
        if len(selected)<20:continue
        split=max(1,int(len(selected)*.7))
        train=selected[:split];holdout=selected[split:]
        def stats(v):
            if not v:return {"n":0,"mean_net_bps":None,"win_pct":None}
            return {"n":len(v),"mean_net_bps":round(sum(x[1] for x in v)/len(v),3),
                    "win_pct":round(100*sum(x[1]>0 for x in v)/len(v),2)}
        rows.append({"symbol":sym,"strategy":strategy,"variant":variant,
                     "train":stats(train),"holdout":stats(holdout),
                     "mean_stop_bps":round(sum(x[3] for x in selected)/len(selected),2),
                     "eligible_for_paper":False})
    rows.sort(key=lambda r:(r["symbol"],r["strategy"],r["variant"]))
    return {"mode":"RESEARCH_ONLY","execution_authority":"NONE",
            "variants":list(VARIANTS),"results":rows,"skipped":dict(skipped),
            "qualification":"NONE — experimental comparisons, not independent validated optimization",
            "limitations":"Chronological 70/30 observational holdout; variants are tested on historical recorded signals, not regenerated strategies. Confirmation and pullback enter on later candle open, not a promised limit fill. Rejects recorded signal-time spread above 3bps; contract metadata is not historically verified. Signal-time spread/fees modeled, ATR uses past candles. No slippage sensitivity, intrabar tape, liquidity proof or wallet simulation."}
