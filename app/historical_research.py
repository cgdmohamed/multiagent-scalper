"""Bounded Bybit V5 historical candle loading and conservative OHLC replay.

Research only. No live or demo order routing. Intrabar stop wins ties.
"""
import asyncio
import math
import sqlite3
import time
from pathlib import Path

import httpx

INTERVALS={"1":60000,"3":180000,"5":300000}
BASE="https://api.bybit.com"
def store(db_path, symbol,interval,bars):
    with sqlite3.connect(db_path) as db:
        db.execute("CREATE TABLE IF NOT EXISTS historical_klines(symbol TEXT NOT NULL, interval TEXT NOT NULL, ts INTEGER NOT NULL, open REAL NOT NULL, high REAL NOT NULL, low REAL NOT NULL, close REAL NOT NULL, volume REAL NOT NULL, PRIMARY KEY(symbol,interval,ts))")
        db.executemany("INSERT OR REPLACE INTO historical_klines VALUES (?,?,?,?,?,?,?,?)",[(symbol,interval,*b) for b in bars])

def load(db_path,symbol,interval,limit=10000):
    with sqlite3.connect(db_path) as db:
        return db.execute("SELECT ts,open,high,low,close,volume FROM historical_klines WHERE symbol=? AND interval=? ORDER BY ts DESC LIMIT ?",(symbol,interval,limit)).fetchall()[::-1]

async def download(db_path,symbol,interval="1",days=7):
    if not symbol.isalnum() or not symbol.endswith("USDT") or len(symbol)>25:raise ValueError("Invalid symbol")
    if interval not in INTERVALS or not 1<=days<=30:raise ValueError("Unsupported history request")
    now=int(time.time()*1000)
    end=now-now%INTERVALS[interval]-1
    start=end-days*86400000
    total=0
    Path(db_path).parent.mkdir(parents=True,exist_ok=True)
    async with httpx.AsyncClient(timeout=20) as client:
        while end>start:
            resp=await client.get(BASE+"/v5/market/kline",params={"category":"linear","symbol":symbol,"interval":interval,"end":end,"limit":1000})
            resp.raise_for_status()
            data=resp.json()
            if data.get("retCode")!=0:raise RuntimeError("Bybit rejected kline request")
            raw=data.get("result",{}).get("list") or []
            parsed=[]
            for r in raw:
                try:
                    ts=int(r[0]); values=tuple(float(v) for v in r[1:6])
                    o,h,l,c,v=values
                    if ts<start or ts+INTERVALS[interval]>now or not all(map(math.isfinite,values)) or min(o,l,c)>h or l>min(o,c) or v<0:continue
                    parsed.append((ts,*values))
                except (ValueError,TypeError,IndexError):continue
            if not parsed:break
            store(db_path,symbol,interval,parsed)
            total+=len(parsed)
            older=min(b[0] for b in parsed)-1
            if older>=end:break
            end=older
            if len(raw)<1000:break
            await asyncio.sleep(.12)
    return {"symbol":symbol,"interval":interval,"downloaded":total,"stored":len(load(db_path,symbol,interval))}

def replay(bars,fee_bps=10,slippage_bps=2,stop_bps=45,target_bps=100):
    """Closed-candle momentum signal: decision at candle close; entry next candle open."""
    if len(bars)<40:return {"trades":0,"net_bps":0,"win_rate_pct":None,"max_drawdown_pct":0,"warnings":["INSUFFICIENT_HISTORY"]}
    equity=1000.;peak=equity;worst=0.;wins=0;trades=0
    i=20
    while i<len(bars)-1:
        ts,o,h,l,c,v=bars[i]
        prior=bars[i-3][4]
        momentum=(c/prior-1)*10000
        if abs(momentum)<20:
            i+=1;continue
        direction=1 if momentum>0 else -1
        entry=bars[i+1][1]*(1+direction*slippage_bps/10000)
        stop=entry*(1-direction*stop_bps/10000)
        target=entry*(1+direction*target_bps/10000)
        exit_price=None
        j=i+1
        while j<len(bars) and j<=i+15:
            _,bo,bh,bl,bc,_=bars[j]
            # Gap at next candle open: stop cannot be filled at a better price than open.
            hit_stop=bl<=stop if direction==1 else bh>=stop
            hit_target=bh>=target if direction==1 else bl<=target
            if hit_stop:
                exit_price=min(stop,bo) if direction==1 else max(stop,bo)
            elif hit_target:
                exit_price=target
            elif j==min(i+15,len(bars)-1):
                exit_price=bc
            if exit_price is not None:break
            j+=1
        if exit_price is None:break
        exit_price*=1-direction*slippage_bps/10000
        net=direction*(exit_price/entry-1)*10000-fee_bps*(1+exit_price/entry)
        equity=max(0,equity+equity*.1*net/10000)
        peak=max(peak,equity);worst=max(worst,(peak-equity)/peak*100)
        wins+=net>0;trades+=1;i=j+1
    return {"trades":trades,"net_pct":round((equity/1000-1)*100,4),"win_rate_pct":round(wins/trades*100,2) if trades else None,"max_drawdown_pct":round(worst,4),"capital":1000,"allocation_pct":10,"warnings":["OHLC_REPLAY_ONLY","STOP_FIRST_ON_INTRABAR_AMBIGUITY","SIMULATED_NOT_REAL_FILLS","NO_ORDERBOOK_REPLAY"]}

async def market_positioning(symbol):
    """Public context only; account ratios measure holders, not position notional."""
    if not symbol.isalnum() or not symbol.endswith("USDT"):raise ValueError("Invalid symbol")
    result={"symbol":symbol,"open_interest":None,"long_short_ratio":None,"errors":[]}
    async with httpx.AsyncClient(timeout=12) as client:
        for field,endpoint,params in (
            ("open_interest","/v5/market/open-interest",{"category":"linear","symbol":symbol,"intervalTime":"5min","limit":2}),
            ("long_short_ratio","/v5/market/account-ratio",{"category":"linear","symbol":symbol,"period":"5min","limit":2}),
        ):
            try:
                resp=await client.get(BASE+endpoint,params=params);resp.raise_for_status()
                data=resp.json()
                if data.get("retCode")!=0:raise ValueError("market data rejected")
                result[field]=(data.get("result",{}).get("list") or [])[:2]
            except (httpx.HTTPError,ValueError,KeyError,TypeError) as e:
                result["errors"].append(field+":"+type(e).__name__)
    return result
