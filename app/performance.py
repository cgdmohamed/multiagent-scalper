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
