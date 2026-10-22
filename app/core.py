"""Safety-first dry-run research prototype. No live orders are supported."""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from collections import deque
from datetime import datetime, timezone
from typing import Literal
import math
import uuid
from .orders import OrderManager, OrderIntent, RoutingError
from .discovery import PairCandidate

SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")

def utcnow(): return datetime.now(timezone.utc).isoformat()

@dataclass
class Book:
    symbol: str
    bid: float
    ask: float
    bid_depth: float
    ask_depth: float
    exchange_ms: int
    received_ms: int
    update_id: int

    @property
    def mid(self): return (self.bid + self.ask) / 2
    @property
    def spread_bps(self): return (self.ask - self.bid) / self.mid * 10000
    @property
    def imbalance(self):
        total = self.bid_depth + self.ask_depth
        return (self.bid_depth - self.ask_depth) / total if total else 0.0

@dataclass
class AgentOpinion:
    agent_id: str
    action: Literal['BUY','HOLD','VETO']
    confidence: float
    evidence: list[str]
    reason: str
    model_version: str = "rules-v0.1"

@dataclass
class Decision:
    decision_id: str
    symbol: str
    created_at: str
    snapshot_id: str
    opinions: list[AgentOpinion]
    verdict: str
    reasons: list[str]
    market: dict

@dataclass
class Position:
    symbol: str
    qty: float
    entry: float
    fee_paid: float
    stop: float
    target: float
    opened_at_ms: int

@dataclass
class Settings:
    initial_cash: float = 1000.0
    taker_fee_bps: float = 10.0 # conservative placeholder, replace with actual account fees
    slippage_bps_per_side: float = 2.0
    max_spread_bps: float = 5.0
    max_book_age_ms: int = 2500
    min_notional: float = 10.0
    risk_per_trade: float = 0.0025
    daily_loss_limit: float = 0.02
    drawdown_limit: float = 0.08
    max_positions: int = 2
    stop_bps: float = 45.0
    target_bps: float = 100.0
    minimum_edge_bps: float = 0.0
    max_hold_ms: int = 15 * 60 * 1000
    min_interval_ms: int = 30000
    max_allocation_fraction: float = 0.20
    max_total_allocation_fraction: float = 0.40

class PaperEngine:
    def __init__(self, settings=None):
        self.cfg = settings or Settings()
        self.cash = self.cfg.initial_cash
        self.positions: dict[str,Position] = {}
        self.books: dict[str,Book] = {}
        self.history = {s: deque(maxlen=45) for s in SYMBOLS}
        # Closed exchange candles only; orderbook update frequency does not define momentum.
        self.candles: dict[str, dict[str, deque]] = {}
        self.candidates: list[PairCandidate] = []
        self.candidate_rules: dict[str,PairCandidate] = {}
        self.decisions: deque[Decision] = deque(maxlen=500)
        self.trades: deque[dict] = deque(maxlen=500)
        self.peak_equity = self.cfg.initial_cash
        self.day = None
        self.day_start_equity = self.cfg.initial_cash
        self.halted = False
        self.operator_paused = False
        self.last_eval: dict[str,int] = {}
        self.last_error: str | None = None
        self.feed_connected = False
        self.order_manager = OrderManager()

    def set_candidates(self, candidates: list[PairCandidate]):
        self.candidates = list(candidates)
        self.candidate_rules = {p.symbol:p for p in candidates}
        for p in candidates: self.history.setdefault(p.symbol,deque(maxlen=45))

    def equity(self):
        marked = sum(p.qty * (self.books[s].bid if s in self.books else p.entry) for s,p in self.positions.items())
        return self.cash + marked

    def _day_roll(self, ms):
        day = datetime.fromtimestamp(ms/1000, timezone.utc).date().isoformat()
        if self.day != day:
            self.day = day
            self.day_start_equity = self.equity()

    def gates(self, book: Book, now_ms: int):
        self._day_roll(now_ms)
        equity = self.equity()
        self.peak_equity = max(self.peak_equity, equity)
        if equity <= self.peak_equity * (1-self.cfg.drawdown_limit):
            self.halted = True
        if equity <= self.day_start_equity * (1-self.cfg.daily_loss_limit):
            self.halted = True
        failures = []
        if self.halted: failures.append("CIRCUIT_BREAKER")
        if self.operator_paused: failures.append("OPERATOR_PAUSED")
        if not (book.bid > 0 and book.ask > book.bid): failures.append("INVALID_BOOK")
        if now_ms - book.received_ms > self.cfg.max_book_age_ms or book.received_ms > now_ms+1000: failures.append("STALE_BOOK")
        if book.spread_bps > self.cfg.max_spread_bps: failures.append("SPREAD_TOO_WIDE")
        if book.symbol in self.positions: failures.append("ALREADY_IN_POSITION")
        if len(self.positions) >= self.cfg.max_positions: failures.append("MAX_POSITIONS")
        if book.symbol not in self.candidate_rules: failures.append("NOT_RANKED_CANDIDATE")
        if len(self.history.get(book.symbol,())) < 6: failures.append("INSUFFICIENT_HISTORY")
        return failures

    def on_candle(self, symbol: str, interval: str, start: int, close: float):
        if interval not in ("1", "3") or not math.isfinite(close) or close <= 0:
            return
        bars = self.candles.setdefault(symbol, {}).setdefault(interval, deque(maxlen=100))
        # Ignore replayed/older bars; replace an identical finalized timestamp.
        if bars and start < bars[-1][0]:
            return
        if bars and start == bars[-1][0]:
            bars[-1] = (start, close)
        else:
            bars.append((start, close))

    def candle_momentum(self, symbol: str):
        bars = self.candles.get(symbol, {})
        one, three = list(bars.get("1", [])), list(bars.get("3", []))
        if len(one) < 4 or len(three) < 3:
            return None, None
        return (one[-1][1]/one[-4][1]-1)*10000, (three[-1][1]/three[-3][1]-1)*10000

    def agents(self, book: Book):
        momentum, trend3 = self.candle_momentum(book.symbol)
        # Absence of confirmed exchange bars is a no-trade condition.
        momentum = momentum if momentum is not None else 0.0
        market = AgentOpinion("market", "BUY" if momentum > 1.0 and trend3 is not None and trend3 > 0 else "HOLD", min(100,abs(momentum)*4), [f"closed_1m_momentum_bps={momentum:.3f}",f"closed_3m_trend_bps={trend3 if trend3 is not None else 'N/A'}"], "Requires positive 1m momentum and 3m trend from CLOSED candles")
        quant = AgentOpinion("quant", "BUY" if book.imbalance > .18 else "HOLD", min(100,abs(book.imbalance)*100), [f"depth_imbalance={book.imbalance:.4f}"], "Bid-side book depth exceeds ask side")
        sentiment = AgentOpinion("sentiment", "HOLD", 0, ["NO_NEWS_FEED"], "Not implemented; abstains rather than fabricating sentiment")
        adversary = AgentOpinion("devils_advocate", "VETO" if book.imbalance < .10 or momentum < 0 or trend3 is None or trend3 < 0 else "HOLD", 100, [f"imbalance={book.imbalance:.4f}",f"momentum_bps={momentum:.3f}"], "Rejects weak liquidity or negative momentum")
        return [market,quant,sentiment,adversary], momentum

    def evaluate(self, book:Book, now_ms:int):
        if now_ms-self.last_eval.get(book.symbol,0) < self.cfg.min_interval_ms:
            return None
        self.last_eval[book.symbol] = now_ms
        opinions,momentum = self.agents(book)
        reasons=self.gates(book,now_ms)
        m1, m3 = self.candle_momentum(book.symbol)
        if m1 is None: reasons.append("CANDLE_HISTORY_NOT_READY")
        if opinions[0].action != "BUY": reasons.append("MARKET_NOT_CONFIRMED")
        if opinions[1].action != "BUY": reasons.append("QUANT_NOT_CONFIRMED")
        if opinions[3].action == "VETO": reasons.append("ADVERSARY_VETO")
        # A candidate's expected edge is a *testable hypothesis*, not an ML forecast.
        estimated_gross_edge_bps = min(45.0, max(0.0, momentum*0.8 + book.imbalance*25.0))
        roundtrip_cost_bps = 2*(self.cfg.taker_fee_bps+self.cfg.slippage_bps_per_side)+book.spread_bps
        if estimated_gross_edge_bps <= roundtrip_cost_bps+self.cfg.minimum_edge_bps:
            reasons.append("COST_EXCEEDS_HYPOTHETICAL_EDGE")
        metrics={"mid":book.mid,"spread_bps":book.spread_bps,"imbalance":book.imbalance,
                 "momentum_bps":momentum,"trend_3m_bps":m3,"estimated_edge_bps":estimated_gross_edge_bps,
                 "roundtrip_cost_bps":roundtrip_cost_bps}
        decision=Decision(str(uuid.uuid4()),book.symbol,utcnow(),f"{book.symbol}:{book.update_id}",opinions,"SKIP" if reasons else "APPROVE",reasons,metrics)
        self.decisions.appendleft(decision)
        if not reasons:
            try:
                self._enter(book,now_ms,decision.decision_id)
            except RoutingError as exc:
                decision.verdict="SKIP"
                decision.reasons.append(str(exc))
        return decision

    def _enter(self, book:Book, now_ms:int, decision_id:str):
        slip=self.cfg.slippage_bps_per_side/10000
        entry=book.ask*(1+slip)
        stop=entry*(1-self.cfg.stop_bps/10000)
        target=entry*(1+self.cfg.target_bps/10000)
        equity=self.equity()
        risk_budget=equity*self.cfg.risk_per_trade
        # Conservative loss budget includes estimated entry + exit fees/slippage.
        total_cost_per_unit = (entry-stop) + (entry+stop)*self.cfg.taker_fee_bps/10000 + stop*self.cfg.slippage_bps_per_side/10000
        max_alloc = equity*self.cfg.max_allocation_fraction
        allocated = sum(p.qty*p.entry for p in self.positions.values())
        remaining_portfolio = max(0,equity*self.cfg.max_total_allocation_fraction-allocated)
        qty=min(risk_budget/total_cost_per_unit, max_alloc/entry, remaining_portfolio/entry, self.cash/(entry*(1+self.cfg.taker_fee_bps/10000)))
        cost=qty*entry
        fee=cost*self.cfg.taker_fee_bps/10000
        rule=self.candidate_rules.get(book.symbol)
        minimum=max(self.cfg.min_notional,rule.min_notional if rule else 0)
        if cost < minimum or cost+fee>self.cash: raise RoutingError("INSUFFICIENT_NOTIONAL_OR_CASH")
        self.order_manager.submit(OrderIntent(decision_id,book.symbol,"BUY",qty,entry,f"{book.symbol}:{book.update_id}"))
        self.cash-=cost+fee
        self.positions[book.symbol]=Position(book.symbol,qty,entry,fee,stop,target,now_ms)
        self.trades.appendleft({"event":"BUY","symbol":book.symbol,"qty":qty,"price":entry,"fee":fee,"decision_id":decision_id,"timestamp":utcnow()})

    def _exit(self, book: Book, now_ms:int):
        p=self.positions.get(book.symbol)
        if not p: return
        price=book.bid*(1-self.cfg.slippage_bps_per_side/10000)
        reason=("STOP" if price<=p.stop else "TARGET" if price>=p.target else "TIMEOUT" if now_ms-p.opened_at_ms>=self.cfg.max_hold_ms else None)
        if not reason: return
        fee=price*p.qty*self.cfg.taker_fee_bps/10000
        self.cash += price*p.qty-fee
        pnl=(price-p.entry)*p.qty-fee-p.fee_paid
        self.trades.appendleft({"event":"SELL","symbol":book.symbol,"qty":p.qty,"price":price,"fee":fee,"pnl":pnl,"reason":reason,"timestamp":utcnow()})
        del self.positions[book.symbol]
        self._day_roll(now_ms)
        equity=self.equity()
        if equity<=self.peak_equity*(1-self.cfg.drawdown_limit) or equity<=self.day_start_equity*(1-self.cfg.daily_loss_limit): self.halted=True

    def on_book(self, book:Book, now_ms:int):
        self.books[book.symbol]=book
        self.history.setdefault(book.symbol,deque(maxlen=45)).append(book.mid)
        # Never simulate fills against stale, invalid, or crossed books.
        if 0<=now_ms-book.received_ms<=self.cfg.max_book_age_ms and book.bid>0 and book.ask>book.bid:
            self._exit(book,now_ms)
            return self.evaluate(book,now_ms)
        return None

    def status(self):
        return {"mode":"PAPER_ONLY","candle_readiness":{s:{"1m":len(v.get("1",())),"3m":len(v.get("3",()))} for s,v in self.candles.items()},"order_router":"PAPER_ONLY","router_halted":self.order_manager.halted,"feed_connected":self.feed_connected,"cash":self.cash,"equity":self.equity(),"peak_equity":self.peak_equity,"halted":self.halted,"positions":{k:asdict(v) for k,v in self.positions.items()},"ranked_pairs":[asdict(x) for x in self.candidates],"books":{k:asdict(v) for k,v in self.books.items()},"decisions":len(self.decisions),"trades":len(self.trades),"last_error":self.last_error}
