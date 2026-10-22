"""Closed-bar technical indicators, no external trading authority."""
import math

def _ema(values,period):
    if len(values)<period:return None
    alpha=2/(period+1)
    x=sum(values[:period])/period
    for v in values[period:]:x=alpha*v+(1-alpha)*x
    return x

def snapshot(candles):
    bars=list(candles)
    closes=[b[3] for b in bars]
    if len(bars)<35:return {"ready":False,"reason":"INSUFFICIENT_CLOSED_BARS"}
    delta=[closes[i]-closes[i-1] for i in range(1,len(closes))]
    up=sum(max(d,0) for d in delta[-14:])/14
    down=sum(max(-d,0) for d in delta[-14:])/14
    rsi=100 if down==0 else 100-100/(1+up/down)
    # MACD(12,26,9) calculated from entire closed price series.
    fast=[];slow=[]
    for i in range(26,len(closes)+1):
        fast.append(_ema(closes[:i],12))
        slow.append(_ema(closes[:i],26))
    macd_series=[a-b for a,b in zip(fast,slow)]
    macd=macd_series[-1]
    signal=_ema(macd_series,9)
    # Wilder directional movement / ADX(14), seeded after sufficient bars.
    trs=[];plus=[];minus=[]
    for prev,cur in zip(bars,bars[1:]):
        _,ph,pl,pc=prev
        _,h,l,c=cur
        hi=h-ph;lo=pl-l
        plus.append(hi if hi>lo and hi>0 else 0)
        minus.append(lo if lo>hi and lo>0 else 0)
        trs.append(max(h-l,abs(h-pc),abs(l-pc)))
    if len(trs)<28:return {"ready":False,"reason":"ADX_WARMUP"}
    def smooth(series):
        x=sum(series[:14])
        out=[]
        for value in series[14:]:
            x=x-x/14+value
            out.append(x)
        return out
    atrs=smooth(trs);pdm=smooth(plus);mdm=smooth(minus)
    dx=[]
    for tr,p,m in zip(atrs,pdm,mdm):
        pdi=100*p/tr if tr>0 else 0
        mdi=100*m/tr if tr>0 else 0
        dx.append(100*abs(pdi-mdi)/(pdi+mdi) if pdi+mdi else 0)
    if len(dx)<14 or signal is None:return {"ready":False,"reason":"ADX_OR_MACD_WARMUP"}
    adx=sum(dx[:14])/14
    for d in dx[14:]:adx=(adx*13+d)/14
    pdi=100*pdm[-1]/atrs[-1] if atrs[-1]>0 else 0
    mdi=100*mdm[-1]/atrs[-1] if atrs[-1]>0 else 0
    values=(rsi,macd,signal,adx,pdi,mdi)
    if not all(math.isfinite(v) for v in values):return {"ready":False,"reason":"INVALID_TECHNICAL_VALUES"}
    return {"ready":True,"rsi14":round(rsi,3),"macd":round(macd,8),"macd_signal":round(signal,8),
            "macd_hist":round(macd-signal,8),"adx14":round(adx,3),"plus_di":round(pdi,3),"minus_di":round(mdi,3)}
