"""Descriptive statistics for historical paper trades only."""
from collections import defaultdict

def summary(items):
    values = [float(x['pnl']) for x in items if x.get('event') == 'CLOSE' and isinstance(x.get('pnl'), (float, int))]
    wins = [x for x in values if x > 0]
    losses = [x for x in values if x < 0]
    return {'trades': len(values), 'wins': len(wins), 'losses': len(losses), 'win_rate_pct': round(100 * len(wins) / len(values), 2) if values else None, 'net_pnl': round(sum(values), 6), 'average_win': round(sum(wins) / len(wins), 6) if wins else None, 'average_loss': round(sum(losses) / len(losses), 6) if losses else None, 'profit_factor': round(sum(wins) / -sum(losses), 4) if losses else None, 'expectancy': round(sum(values) / len(values), 6) if values else None}

def report(trades):
    closed = [x for x in trades if x.get('event') == 'CLOSE']
    groups = {'by_symbol': defaultdict(list), 'by_direction': defaultdict(list), 'by_exit_reason': defaultdict(list)}
    for trade in closed:
        groups['by_symbol'][trade.get('symbol', 'UNKNOWN')].append(trade)
        groups['by_direction'][trade.get('direction', 'UNKNOWN')].append(trade)
        groups['by_exit_reason'][trade.get('reason', 'UNKNOWN')].append(trade)
    return {'mode': 'PAPER_ONLY', 'note': 'Closed trades only; fee/slippage estimates, no funding/liquidation.', 'overall': summary(closed), **{group: {key: summary(items) for key, items in sorted(rows.items())} for group, rows in groups.items()}}

def cooldown_study(trades, minutes=(3, 5)):
    """Retrospective proximity analysis, NOT simulated counterfactual profit."""
    from datetime import datetime
    ordered=sorted((t for t in trades if t.get("event") in ("OPEN","CLOSE") and t.get("timestamp")),key=lambda t:t["timestamp"])
    stops={}
    results={}
    for minutes_value in minutes:
        affected=[]
        for trade in ordered:
            symbol=trade.get("symbol")
            try: ts=datetime.fromisoformat(trade["timestamp"].replace("Z","+00:00")).timestamp()
            except ValueError:continue
            if trade["event"]=="OPEN" and symbol in stops:
                elapsed=(ts-stops[symbol])/60
                if 0<=elapsed<minutes_value:
                    affected.append({"symbol":symbol,"timestamp":trade["timestamp"],"minutes_since_stop":round(elapsed,2)})
            if trade["event"]=="CLOSE" and trade.get("reason")=="STOP":
                stops[symbol]=ts
        results[str(minutes_value)+"m"]={"entries_within_cooldown":len(affected),"sample":affected[:20]}
        stops.clear()
    return {"mode":"OBSERVATIONAL_ONLY","note":"Counts historical entries within N minutes after same-symbol STOP. Cannot infer avoided losses/profits without full market replay.", "windows":results}


def account_audit(trades, cash, open_positions, starting_cash=1000):
    """Reconcile a *single known account lineage*; never merge unrelated restarts."""
    opened=sum(1 for t in trades if t.get("event")=="OPEN")
    closed=[t for t in trades if t.get("event")=="CLOSE"]
    net=sum(float(t.get("pnl",0)) for t in closed)
    return {"ledger_open_events":opened,"ledger_close_events":len(closed),
            "all_time_closed_pnl":round(net,6),
            "theoretical_flat_equity":round(starting_cash+net,6),
            "theoretical_equity_is_authoritative":False,
            "current_cash":round(cash,6),"current_open_positions":len(open_positions),
            "note":"Theoretical flat equity assumes one uninterrupted portfolio lineage, complete trades and zero deposits; historical restarts may invalidate it."}
