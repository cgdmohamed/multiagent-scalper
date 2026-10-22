"""Transparent research benchmarks over recorded Strategy Lab observations.

Not a candle-level historical backtest. Fixed-horizon midpoint observation prices
cannot reproduce grid intrabar fills, stop orders or Bybit's proprietary bots.
"""
from collections import defaultdict
import math

COST_BPS=24.0

def drawdown_pct(equity):
    peak=equity[0] if equity else 1.0
    worst=0.0
    for value in equity:
        peak=max(peak,value)
        if peak>0:worst=max(worst,(peak-value)/peak*100)
    return round(worst,4)

def compare(samples,initial_cash=1000.0,risk_fraction=.10):
    """Non-overlapping, single-symbol 15-minute signals versus buy/hold.

    Compare only windows with known terminal quote; do not invent ticks,
    stops/targets or mark-to-market paths. Each signal allocates a fixed 10%
    of equity, with matching buy/hold entry/exit dates and cost assumptions.
    """
    if not 0<risk_fraction<=1 or initial_cash<=0:raise ValueError("invalid capital/allocation")
    grouped=defaultdict(list)
    for r in samples:
        if not isinstance(r,dict) or "15m" not in r.get("returns",{}):continue
        try:
            at=int(r["at_ms"]); price=float(r["entry"]); cost=float(r["cost_bps"])
            gain=float(r["returns"]["15m"])
            if not all(math.isfinite(x) for x in (price,cost,gain)) or price<=0 or cost<0:continue
        except (ValueError,KeyError,TypeError):continue
        grouped[(r.get("symbol"),r.get("strategy"))].append((at,price,cost,gain,r["direction"]))
    strategies={}
    for (symbol,name),signals in grouped.items():
        signals.sort()
        equity=initial_cash;curve=[equity];next_free=-1
        trades=0;wins=0
        baseline=initial_cash;baseline_curve=[baseline]
        for at,price,cost,gain,direction in signals:
            if at<next_free:continue
            next_free=at+900000
            # Reconstruct observed directional gross move from net bps.
            signed=(gain+cost)*(1 if direction=="LONG" else -1)
            # Buy-and-hold benchmark uses the same windows and deployed cash.
            hold_net=signed-cost
            stake=equity*risk_fraction
            equity=max(0,equity+stake*gain/10000)
            baseline=max(0,baseline+baseline*risk_fraction*hold_net/10000)
            curve.append(equity);baseline_curve.append(baseline)
            trades+=1;wins+=gain>0
        if trades:
            strategies[f"{symbol}:{name}"]={
                "symbol":symbol,"strategy":name,"samples":trades,
                "net_pct":round((equity/initial_cash-1)*100,4),
                "win_pct":round(wins/trades*100,2),
                "max_closed_observation_drawdown_pct":drawdown_pct(curve),
                "hold_same_windows_net_pct":round((baseline/initial_cash-1)*100,4),
                "hold_max_closed_observation_drawdown_pct":drawdown_pct(baseline_curve),
                "beats_same_windows_hold":equity>baseline,
            }
    eligible=[v for v in strategies.values() if v["samples"]>=50 and v["net_pct"]>0 and v["beats_same_windows_hold"] and v["max_closed_observation_drawdown_pct"]<=3]
    eligible.sort(key=lambda v:(v["net_pct"]-v["hold_same_windows_net_pct"],-v["max_closed_observation_drawdown_pct"]),reverse=True)
    return {"selection_mode":"RESEARCH_CANDIDATE_ONLY","selected_candidate":eligible[0] if eligible else None,
            "selection_criteria":"At least 50 nonoverlapping 15m observations, positive modeled net result, above same-window long baseline and <=3% closed-observation drawdown. Requires out-of-sample validation before promotion.",
            "mode":"OBSERVATIONAL_BENCHMARK","initial_cash":initial_cash,
            "fixed_allocation_pct":round(risk_fraction*100,2),
            "grid_status":"NOT_COMPARABLE_WITHOUT_OHLC_OR_TICK_REPLAY",
            "limitations":"Not historical backtesting. Fixed 15m observation endpoints, no intrabar SL/TP or actual fills. Closed-observation drawdown underestimates intratrade risk. Buy/hold is matched-window long exposure, NOT continuous buy-and-hold. No claim of superiority over Bybit bots.",
            "results":strategies}
