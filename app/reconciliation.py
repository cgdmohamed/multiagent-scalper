"""Read-only legacy paper-ledger reconciliation. Unknown restarts cannot be inferred."""
from collections import defaultdict
from math import isclose

def analyze(trades):
    pending=defaultdict(list)
    matched=[]
    issues=[]
    for index, trade in enumerate(trades):
        event=trade.get("event")
        if event not in ("OPEN","CLOSE"):
            continue
        symbol=trade.get("symbol")
        direction=trade.get("direction")
        qty=trade.get("qty")
        if not symbol or direction not in ("LONG","SHORT") or not isinstance(qty,(int,float)) or qty<=0:
            issues.append({"index":index,"issue":"INVALID_TRADE","symbol":symbol})
            continue
        key=(symbol,direction)
        if event=="OPEN":
            if pending[key]:
                issues.append({"index":index,"issue":"OVERLAPPING_OPEN","symbol":symbol,"direction":direction})
            pending[key].append(trade)
        else:
            candidates=pending[key]
            match=next((i for i,v in enumerate(candidates) if isclose(float(v["qty"]),float(qty),rel_tol=1e-6,abs_tol=1e-9)),None)
            if match is None:
                issues.append({"index":index,"issue":"CLOSE_WITHOUT_MATCHING_OPEN","symbol":symbol,"direction":direction})
            else:
                opened=candidates.pop(match)
                matched.append({"symbol":symbol,"direction":direction,"entry_at":opened.get("timestamp"),
                                "exit_at":trade.get("timestamp"),"pnl":trade.get("pnl")})
    unmatched=[{"symbol":symbol,"direction":direction,"qty":trade.get("qty"),"entry_at":trade.get("timestamp")}
               for (symbol,direction),items in pending.items() for trade in items]
    return {"mode":"READ_ONLY_RECONCILIATION","matched_round_trips":len(matched),
            "unmatched_opens":unmatched,"issues":issues,
            "complete_trade_pairing":not unmatched and not issues,
            "account_reconstruction_trusted":False,
            "warning":"Matching trade records cannot prove complete portfolio continuity across pre-checkpoint restarts.",
            "closed_pnl_in_ledger":round(sum(float(t.get("pnl",0)) for t in trades if t.get("event")=="CLOSE"),6)}
