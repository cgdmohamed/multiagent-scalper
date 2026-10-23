"""Read-only signal-level execution reconciliation. No trade authority."""
from bisect import bisect_right
from collections import Counter
from .signal_replay import _replay_one, STRATEGIES

def execution_audit(signals,bars_by_symbol,*,fee_bps=10,slippage_bps=2,stop_bps=45,target_bps=100,hold_minutes=15,limit=100,symbol=None,strategy=None):
    limit=max(1,min(int(limit),200))
    records=[]
    counts=Counter()
    diagnostic={}
    for signal in sorted(signals,key=lambda x:x.get("at_ms",0),reverse=True):
        if signal.get("strategy") not in STRATEGIES:continue
        if symbol and signal.get("symbol")!=symbol:continue
        if strategy and signal.get("strategy")!=strategy:continue
        bars=sorted(bars_by_symbol.get(signal.get("symbol"),[]),key=lambda x:x[0])
        at=signal.get("at_ms")
        try: at=int(at)
        except (ValueError,TypeError):at=0
        lab_net=signal.get("returns",{}).get("15m")
        try: lab_net=float(lab_net) if lab_net is not None else None
        except (ValueError,TypeError):lab_net=None
        row={"id":signal.get("id"),"symbol":signal.get("symbol"),"strategy":signal.get("strategy"),
             "direction":signal.get("direction"),"signal_at_ms":at,"signal_mid":signal.get("entry"),
             "regime":signal.get("regime"),"lab_15m_net_bps":lab_net,
             "lab_assumed_cost_bps":signal.get("cost_bps")}
        if not bars:
            reason="NO_HISTORICAL_1M_DATA"
        elif at<bars[0][0]:
            reason="SIGNAL_BEFORE_HISTORY"
        elif at>=bars[-1][0]+60000:
            reason="SIGNAL_AFTER_HISTORY"
        else:
            replay,reason=_replay_one(signal,bars,[b[0] for b in bars],
                                       fee_bps,slippage_bps,stop_bps,target_bps,hold_minutes)
            if replay:
                row.update({key:replay[key] for key in ("entry_at_ms","exit_at_ms","net_bps",
                    "fees_bps","gross_after_spread_slippage_bps","outcome")})
                spread_bps=max(0,float(signal.get("cost_bps",24))-24)
                row["estimated_spread_bps"]=round(spread_bps,3)
                row["slippage_assumption_bps_roundtrip"]=2*slippage_bps
                row["modeled_entry_price"]=replay.get("entry_price")
                row["raw_next_open"]=replay.get("raw_next_open")
                row["modeled_exit_price"]=replay.get("exit_price")
                row["replay_vs_lab_bps"]=round(replay["net_bps"]-lab_net,3) if lab_net is not None else None
                reason="REPLAYED"
        row["status"]=reason
        counts[reason]+=1
        group=diagnostic.setdefault(row["strategy"],{"replayed":0,"stop_first":0,"target":0,
                                     "timed_exit":0,"losses":0,"missing_data":0,"net_bps_sum":0.})
        if reason=="REPLAYED":
            group["replayed"]+=1
            group["net_bps_sum"]+=row["net_bps"]
            group["losses"]+=int(row["net_bps"]<0)
            group["stop_first"]+=int(row.get("outcome")=="STOP_FIRST")
            group["target"]+=int(row.get("outcome")=="TARGET")
            group["timed_exit"]+=int(row.get("outcome")=="TIME")
        else:group["missing_data"]+=1
        if len(records)<limit:records.append(row)
    for group in diagnostic.values():
        n=group["replayed"]
        group["average_net_bps"]=round(group.pop("net_bps_sum")/n,3) if n else None
    return {"mode":"RESEARCH_ONLY","records":records,"strategy_diagnostics":diagnostic,
            "status_counts":dict(counts),
            "matched_filters":{"symbol":symbol,"strategy":strategy},
            "limitations":"Lab is a 15m future quote mark after estimated costs; replay is next-minute entry with stop/target and fees. Different exits and missing observations are not accounting errors. No actual fills; overlap and selection effects remain."}
