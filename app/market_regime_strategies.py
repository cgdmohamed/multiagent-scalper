"""Research-only candle strategies. Only completed 1m candles can trigger."""
from datetime import datetime,timezone
from .technical_indicators import _ema

NAMES=("EMA_PULLBACK_9_21","SESSION_VWAP_PULLBACK","VOLUME_RANGE_BREAKOUT","RSI_RANGE_REVERSAL")

def evaluate(bars,technical):
    bars=list(bars)
    if len(bars)<45 or not technical.get("ready"):return {},{"state":"NOT_READY"}
    # Reject gaps: indicators based on old disconnected candles would be misleading.
    if any(b[0]-a[0]!=60000 for a,b in zip(bars[-45:],bars[-44:])):
        return {},{"state":"GAPPED_CANDLES"}
    closes=[b[3] for b in bars]
    previous,current=bars[-2],bars[-1]
    ts,high,low,close=current
    prev_close=previous[3]
    ema9=_ema(closes,9);ema21=_ema(closes,21)
    atr_bps=sum(b[1]-b[2] for b in bars[-14:])/14/close*10000
    adx=technical["adx14"]
    trend=adx>=23 and atr_bps>=5
    ranging=adx<=19 and atr_bps>=4
    signals={}
    if trend and abs(ema9/ema21-1)*10000>=3:
        if ema9>ema21 and previous[2]<=ema9*1.001 and close>ema9 and close>prev_close and low<=ema9*1.001:
            signals["EMA_PULLBACK_9_21"]="LONG"
        elif ema9<ema21 and previous[1]>=ema9*.999 and close<ema9 and close<prev_close and high>=ema9*.999:
            signals["EMA_PULLBACK_9_21"]="SHORT"
    # UTC-day VWAP anchored at 00:00 UTC; proxy via typical price*volume.
    start=ts-ts%86400000
    session=[b for b in bars if b[0]>=start]
    volume=sum(b[4] for b in session)
    vwap=sum(((b[1]+b[2]+b[3])/3)*b[4] for b in session)/volume if volume>0 else None
    if trend and vwap and len(session)>=20:
        if ema9>ema21 and low<=vwap*1.001 and close>vwap and close>prev_close:
            signals["SESSION_VWAP_PULLBACK"]="LONG"
        elif ema9<ema21 and high>=vwap*.999 and close<vwap and close<prev_close:
            signals["SESSION_VWAP_PULLBACK"]="SHORT"
    reference=bars[-21:-1]
    top=max(b[1] for b in reference)
    bottom=min(b[2] for b in reference)
    widths=[(b[1]-b[2])/b[3]*10000 for b in reference]
    baseline=sum(widths)/len(widths)
    avg_volume=sum(b[4] for b in reference)/len(reference)
    # Break a relatively narrow range, with volume > 2x prior baseline.
    if baseline<35 and avg_volume>0 and current[4]>=2*avg_volume and atr_bps>=5:
        if close>top and prev_close<=top:signals["VOLUME_RANGE_BREAKOUT"]="LONG"
        elif close<bottom and prev_close>=bottom:signals["VOLUME_RANGE_BREAKOUT"]="SHORT"
    rsi=technical["rsi14"]
    support=min(b[2] for b in bars[-21:-1])
    resistance=max(b[1] for b in bars[-21:-1])
    if ranging:
        if rsi<=30 and low<=support*1.002 and close>low and close>prev_close:
            signals["RSI_RANGE_REVERSAL"]="LONG"
        elif rsi>=70 and high>=resistance*.998 and close<high and close<prev_close:
            signals["RSI_RANGE_REVERSAL"]="SHORT"
    return signals,{"state":"READY","regime":"TRENDING" if trend else "RANGING" if ranging else "MIXED",
                    "session_vwap_proxy":vwap,"ema9":ema9,"ema21":ema21,"bar_at_ms":ts}
