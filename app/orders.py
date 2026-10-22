"""Central order router. This release intentionally has no external execution adapter."""
from __future__ import annotations
from dataclasses import dataclass
from collections import deque
from threading import RLock
import math
import time

class RoutingError(RuntimeError): pass

@dataclass(frozen=True)
class OrderIntent:
    decision_id: str
    symbol: str
    side: str
    quantity: float
    reference_price: float
    snapshot_id: str

class SlidingWindowLimiter:
    """Conservative local limiter; for one process, not distributed by UID/IP."""
    def __init__(self, max_calls=3, window_seconds=1.0, clock=time.monotonic):
        self.max_calls=max_calls; self.window_seconds=window_seconds; self.clock=clock
        self._events=deque(); self._lock=RLock()

    def acquire(self):
        with self._lock:
            now=self.clock()
            while self._events and now-self._events[0]>=self.window_seconds:
                self._events.popleft()
            if len(self._events)>=self.max_calls: return False
            self._events.append(now)
            return True

class OrderManager:
    """Paper-only intent registration. No bybit order API or credentials accepted."""
    def __init__(self, mode='PAPER', limiter=None, allowed_symbols=None):
        if mode!='PAPER': raise RoutingError('Only PAPER is implemented; DEMO/LIVE have no adapter')
        self.mode=mode
        self.allowed_symbols=set(allowed_symbols or ('BTCUSDT','ETHUSDT','SOLUSDT'))
        self.limiter=limiter or SlidingWindowLimiter()
        self.seen=set(); self.audit=[]; self._lock=RLock()
        self.halted=False

    def submit(self, intent:OrderIntent):
        with self._lock:
            if self.halted: raise RoutingError('KILL_SWITCH')
            if intent.decision_id in self.seen: raise RoutingError('DUPLICATE_DECISION')
            if intent.symbol not in self.allowed_symbols: raise RoutingError('UNSUPPORTED_SYMBOL')
            if intent.side not in ('BUY','SELL'): raise RoutingError('INVALID_SIDE')
            if not (0 < math.isfinite(intent.quantity) and math.isfinite(intent.reference_price) and intent.quantity > 0 and intent.reference_price > 0):
                raise RoutingError('INVALID_ORDER_VALUES')
            if not intent.snapshot_id: raise RoutingError('MISSING_SNAPSHOT')
            if not self.limiter.acquire(): raise RoutingError('LOCAL_RATE_LIMIT')
            self.seen.add(intent.decision_id)
            event={'event':'PAPER_INTENT_ACCEPTED','decision_id':intent.decision_id,'symbol':intent.symbol,'side':intent.side,'quantity':intent.quantity,'snapshot_id':intent.snapshot_id}
            self.audit.append(event)
            return event

    def kill(self):
        with self._lock: self.halted=True
