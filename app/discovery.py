"""Public market discovery only. Rankings are heuristics, not return forecasts."""
from __future__ import annotations
from dataclasses import dataclass, asdict
import math
import httpx

BASE = 'https://api.bybit.com'

@dataclass(frozen=True)
class PairCandidate:
    symbol: str
    turnover24h: float
    change24h_pct: float
    spread_bps: float
    score: float
    min_notional: float
    tick_size: float
    qty_step: float


def discover(instruments: list[dict], tickers: list[dict], *, top_n: int = 5, min_turnover: float = 5_000_000, max_spread_bps: float = 8.0) -> list[PairCandidate]:
    specs = {}
    for inst in instruments:
        symbol = inst.get('symbol', '')
        if (inst.get('status') != 'Trading' or inst.get('quoteCoin') != 'USDT' or inst.get('settleCoin') != 'USDT' or inst.get('contractType') != 'LinearPerpetual' or not symbol.endswith('USDT')):
            continue
        try:
            rules = inst['lotSizeFilter']
            minimum = float(rules.get('minNotionalValue') or 5)
            step = float(rules['qtyStep'])
            tick = float(inst['priceFilter']['tickSize'])
            if minimum <= 0 or step <= 0 or tick <= 0: continue
        except (KeyError, ValueError, TypeError): continue
        specs[symbol] = (minimum, tick, step)
    candidates = []
    for t in tickers:
        s = t.get('symbol')
        if s not in specs: continue
        try:
            turnover = float(t['turnover24h'])
            bid, ask = float(t['bid1Price']), float(t['ask1Price'])
            change = float(t['price24hPcnt']) * 100
            if not all(math.isfinite(v) for v in (turnover,bid,ask,change)) or turnover < min_turnover or bid <= 0 or ask <= bid: continue
            spread = (ask-bid)/((ask+bid)/2)*10000
            if spread > max_spread_bps: continue
            # Bounded liquidity and movement rankings, spread penalty. No predictive claim.
            score = min(10.0, math.log10(max(turnover, 1))) * 5 + min(abs(change), 8) * 2 - spread * 3
            candidates.append(PairCandidate(s,turnover,change,spread,round(score,4),*specs[s]))
        except (ValueError, TypeError, KeyError, OverflowError): continue
    return sorted(candidates,key=lambda c:(-c.score,-c.turnover24h,c.symbol))[:max(0,top_n)]

async def fetch_candidates(client: httpx.AsyncClient, *, top_n=5, min_turnover=5_000_000, max_spread_bps=8.0):
    async def fetch(path, params):
        r = await client.get(f'{BASE}{path}',params=params,timeout=12.0)
        r.raise_for_status()
        data = r.json()
        if data.get('retCode') != 0: raise RuntimeError(f"Bybit public API failure: {data.get('retCode')}")
        return data['result']
    instruments=[]
    cursor=None
    for _ in range(25):
        params={'category':'linear','limit':1000}
        if cursor: params['cursor']=cursor
        result=await fetch('/v5/market/instruments-info',params)
        instruments.extend(result.get('list',[]))
        next_cursor=result.get('nextPageCursor')
        if not next_cursor or next_cursor==cursor: break
        cursor=next_cursor
    else: raise RuntimeError('Instrument pagination exceeded bound')
    tickers=(await fetch('/v5/market/tickers',{'category':'linear'})).get('list',[])
    return discover(instruments,tickers,top_n=top_n,min_turnover=min_turnover,max_spread_bps=max_spread_bps)
