"""Fail-closed, fee-aware notional and quantity sizing (paper research only)."""
import math

def size_position(*,equity,cash,entry,stop,qty_step,min_notional,risk_fraction,
                  fee_bps,slippage_bps,allocation_fraction,total_free_notional,
                  available_depth_notional=None,depth_fraction=0.01):
    values=(equity,cash,entry,stop,qty_step,min_notional,risk_fraction,fee_bps,
            slippage_bps,allocation_fraction,total_free_notional)
    if not all(math.isfinite(v) for v in values) or min(equity,cash,entry,stop,qty_step)>0 is False:
        return {"allowed":False,"reason":"INVALID_SIZING_INPUT"}
    if any(v<0 for v in (min_notional,risk_fraction,fee_bps,slippage_bps,allocation_fraction,total_free_notional)):
        return {"allowed":False,"reason":"INVALID_SIZING_LIMIT"}
    # Assume one adverse slippage impact on both sides in addition to entry/exit fees.
    unit_loss=abs(entry-stop)+(entry+stop)*(fee_bps+slippage_bps)/10000
    if unit_loss<=0:return {"allowed":False,"reason":"INVALID_STOP_DISTANCE"}
    caps=[equity*risk_fraction/unit_loss,equity*allocation_fraction/entry,
          total_free_notional/entry,cash/(entry*(1+fee_bps/10000))]
    if available_depth_notional is not None:
        if not math.isfinite(available_depth_notional) or available_depth_notional<=0:
            return {"allowed":False,"reason":"INVALID_LIQUIDITY"}
        caps.append(available_depth_notional*depth_fraction/entry)
    qty=math.floor(min(caps)/qty_step+1e-10)*qty_step
    notional=qty*entry
    if qty<=0 or notional<min_notional:return {"allowed":False,"reason":"MINIMUM_ORDER_EXCEEDS_RISK_BUDGET"}
    estimated_max_loss=qty*unit_loss
    if estimated_max_loss>equity*risk_fraction+1e-6:
        return {"allowed":False,"reason":"RISK_BUDGET_EXCEEDED"}
    return {"allowed":True,"qty":qty,"notional":round(notional,8),
            "estimated_stop_loss":round(estimated_max_loss,8),
            "risk_budget":round(equity*risk_fraction,8),
            "risk_pct":round(estimated_max_loss/equity*100,5)}
