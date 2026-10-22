"""USDT linear perpetual PAPER simulator. No private exchange endpoints."""
from dataclasses import dataclass, asdict
from collections import deque
import time
import math
import uuid
from .core import PaperEngine, Settings, AgentOpinion, Decision, utcnow
from .orders import OrderIntent, RoutingError

@dataclass
class FuturesPosition:
    symbol: str
    direction: str
    qty: float
    entry: float
    margin: float
    entry_fee: float
    stop: float
    target: float
    opened_at_ms: int

class FuturesPaperEngine(PaperEngine):
    def __init__(self, settings=None):
        super().__init__(settings or Settings())
        self.funding_paid = 0.0
        self.last_stops = {}
        self.session_closes = deque(maxlen=200)
        self.performance_halted = False

    def equity(self):
        result = self.cash
        for symbol, p in self.positions.items():
            book = self.books.get(symbol)
            mark = (book.bid if p.direction == "LONG" else book.ask) if book else p.entry
            delta = (mark-p.entry) if p.direction == "LONG" else (p.entry-mark)
            result += p.margin + delta*p.qty
        return result

    def agents(self, book):
        one, three = self.candle_momentum(book.symbol)
        if one is None or three is None: return [
            AgentOpinion("market","HOLD",0,[],"Closed candle history unavailable"),
            AgentOpinion("quant","HOLD",0,[],"No synchronized trend"),
            AgentOpinion("sentiment","HOLD",0,[],"Research-only"),
            AgentOpinion("devils_advocate","VETO",100,[],"Insufficient data")],0.0
        direction = "LONG" if one > 1 and three > 0 else "SHORT" if one < -1 and three < 0 else None
        imbalance = book.imbalance
        confirmed = bool(direction and (imbalance > .18 if direction=="LONG" else imbalance < -.18))
        veto = (direction is None or (imbalance < .10 if direction=="LONG" else imbalance > -.10))
        return [
            AgentOpinion("market","BUY" if direction=="LONG" else "SELL" if direction=="SHORT" else "HOLD",min(100,abs(one)*4),[f"closed_1m_bps={one:.2f}",f"closed_3m_bps={three:.2f}"],"Trend alignment"),
            AgentOpinion("quant","BUY" if confirmed and direction=="LONG" else "SELL" if confirmed else "HOLD",min(100,abs(imbalance)*100),[f"imbalance={imbalance:.3f}"],"Directional orderbook support"),
            AgentOpinion("sentiment","HOLD",0,["SHADOW_ONLY"],"No execution authority"),
            AgentOpinion("devils_advocate","VETO" if veto else "HOLD",100,[], "Reject weak directional signal")
        ],one

    def evaluate(self,book,now_ms):
        if now_ms-self.last_eval.get(book.symbol,0)<self.cfg.min_interval_ms:return None
        self.last_eval[book.symbol]=now_ms
        votes,momentum=self.agents(book)
        if self.performance_halted:
            self.halted=True
        # Closed candles replace the obsolete six-tick entry warm-up.
        reasons=[r for r in self.gates(book,now_ms) if r != "INSUFFICIENT_HISTORY"]
        if now_ms-self.last_stops.get(book.symbol,-10**15)<5*60*1000:reasons.append("STOP_COOLDOWN_5M")
        if self.performance_halted:reasons.append("PERFORMANCE_CIRCUIT_BREAKER")
        m1,m3=self.candle_momentum(book.symbol)
        direction="LONG" if votes[0].action=="BUY" else "SHORT" if votes[0].action=="SELL" else None
        if m1 is None:reasons.append("CANDLE_HISTORY_NOT_READY")
        if direction is None:reasons.append("TREND_TIMEFRAMES_CONFLICT" if m1 is not None and m3 is not None and m1*m3<0 else "MARKET_NOT_CONFIRMED")
        if direction is not None and votes[1].action!=votes[0].action:reasons.append("QUANT_NOT_CONFIRMED")
        if votes[3].action=="VETO":reasons.append("ADVERSARY_VETO")
        edge=min(45.,max(0.,abs(momentum)*.8+abs(book.imbalance)*25.))
        cost=2*(self.cfg.taker_fee_bps+self.cfg.slippage_bps_per_side)+book.spread_bps
        if edge<=cost+self.cfg.minimum_edge_bps:reasons.append("COST_EXCEEDS_HYPOTHETICAL_EDGE")
        decision=Decision(str(uuid.uuid4()),book.symbol,utcnow(),f"{book.symbol}:{book.update_id}",votes,"SKIP" if reasons else "APPROVE",reasons,
            {"direction":direction,"mid":book.mid,"spread_bps":book.spread_bps,"imbalance":book.imbalance,
             "momentum_bps":momentum,"trend_3m_bps":m3,"estimated_edge_bps":edge,"roundtrip_cost_bps":cost,"required_imbalance":(.18 if direction=="LONG" else -.18 if direction=="SHORT" else None)})
        self.decisions.appendleft(decision)
        if not reasons:
            try:self._enter(book,now_ms,decision.decision_id,direction)
            except RoutingError as exc:decision.verdict="SKIP";decision.reasons.append(str(exc))
        return decision

    def _enter(self,book,now_ms,decision_id,direction):
        if direction not in ("LONG","SHORT"):raise RoutingError("INVALID_DIRECTION")
        # Isolated 1x paper margin, no leverage. Include fees in risk sizing.
        slip=self.cfg.slippage_bps_per_side/10000
        entry=(book.ask*(1+slip) if direction=="LONG" else book.bid*(1-slip))
        stop=entry*(1-self.cfg.stop_bps/10000 if direction=="LONG" else 1+self.cfg.stop_bps/10000)
        target=entry*(1+self.cfg.target_bps/10000 if direction=="LONG" else 1-self.cfg.target_bps/10000)
        eq=self.equity()
        per_unit=abs(entry-stop)+(entry+stop)*(self.cfg.taker_fee_bps+self.cfg.slippage_bps_per_side)/10000
        used=sum(p.margin for p in self.positions.values())
        maximum=min(eq*self.cfg.risk_per_trade/per_unit,eq*self.cfg.max_allocation_fraction/entry,
                    max(0,eq*self.cfg.max_total_allocation_fraction-used)/entry,
                    self.cash/(entry*(1+self.cfg.taker_fee_bps/10000)))
        step=self.candidate_rules[book.symbol].qty_step
        qty=math.floor((maximum+1e-12)/step)*step
        margin=qty*entry;fee=margin*self.cfg.taker_fee_bps/10000
        if margin<max(self.cfg.min_notional,self.candidate_rules[book.symbol].min_notional) or margin+fee>self.cash:
            raise RoutingError("INSUFFICIENT_NOTIONAL_OR_CASH")
        self.order_manager.submit(OrderIntent(decision_id,book.symbol,"BUY" if direction=="LONG" else "SELL",qty,entry,f"{book.symbol}:{book.update_id}"))
        self.cash-=margin+fee
        self.positions[book.symbol]=FuturesPosition(book.symbol,direction,qty,entry,margin,fee,stop,target,now_ms)
        self.trades.appendleft({"event":"OPEN","direction":direction,"symbol":book.symbol,"qty":qty,"price":entry,"fee":fee,"decision_id":decision_id,"timestamp":utcnow()})

    def _exit(self,book,now_ms):
        p=self.positions.get(book.symbol)
        if p is None:return
        slip=self.cfg.slippage_bps_per_side/10000
        price=book.bid*(1-slip) if p.direction=="LONG" else book.ask*(1+slip)
        stopped=price<=p.stop if p.direction=="LONG" else price>=p.stop
        targeted=price>=p.target if p.direction=="LONG" else price<=p.target
        reason="STOP" if stopped else "TARGET" if targeted else "TIMEOUT" if now_ms-p.opened_at_ms>=self.cfg.max_hold_ms else None
        if reason is None:return
        fee=price*p.qty*self.cfg.taker_fee_bps/10000
        realized=((price-p.entry) if p.direction=="LONG" else (p.entry-price))*p.qty-fee-p.entry_fee
        self.cash+=p.margin+(((price-p.entry) if p.direction=="LONG" else (p.entry-price))*p.qty)-fee
        self.trades.appendleft({"event":"CLOSE","direction":p.direction,"symbol":book.symbol,"qty":p.qty,"price":price,"fee":fee,"pnl":realized,"reason":reason,"reduce_only":True,"timestamp":utcnow()})
        del self.positions[book.symbol]
        if reason=="STOP":self.last_stops[book.symbol]=now_ms
        self.session_closes.append(realized)
        if len(self.session_closes)>=10 and sum(self.session_closes)<=-0.005*self.cfg.initial_cash:
            self.performance_halted=True
            self.halted=True
        self._day_roll(now_ms)
        eq=self.equity()
        if eq<=self.peak_equity*(1-self.cfg.drawdown_limit) or eq<=self.day_start_equity*(1-self.cfg.daily_loss_limit):self.halted=True

    def position_analytics(self):
        """Estimated exit-marked P&L, not exchange liquidation or funding accounting."""
        out={}
        for symbol,p in self.positions.items():
            book=self.books.get(symbol)
            price=(book.bid if p.direction=="LONG" else book.ask) if book else p.entry
            exit_price=price*(1-self.cfg.slippage_bps_per_side/10000 if p.direction=="LONG" else 1+self.cfg.slippage_bps_per_side/10000)
            gross=((exit_price-p.entry) if p.direction=="LONG" else (p.entry-exit_price))*p.qty
            estimated_exit_fee=exit_price*p.qty*self.cfg.taker_fee_bps/10000
            position_progress=max(0.,min(100.,(exit_price-p.stop)/(p.target-p.stop)*100)) if p.direction=="LONG" else max(0.,min(100.,(p.stop-exit_price)/(p.stop-p.target)*100))
            age_ms=max(0,int(time.time()*1000)-(book.received_ms if book else 0)) if book else None
            fresh=bool(book and self.feed_connected and age_ms<=5000)
            out[symbol]={"price_fresh":fresh,"price_age_ms":age_ms,"last_price":price if fresh else None,
                         "stop_target_progress_pct":round(position_progress,2) if fresh else None,
                         "distance_to_stop_pct":round(abs(exit_price-p.stop)/p.entry*100,3) if fresh else None,
                         "distance_to_target_pct":round(abs(p.target-exit_price)/p.entry*100,3) if fresh else None,
                         "mark_price":price,"estimated_exit_price":exit_price,
                         "unrealized_pnl":gross-p.entry_fee-estimated_exit_fee,
                         "gross_unrealized_pnl":gross,"estimated_exit_fee":estimated_exit_fee,
                         "entry_fee":p.entry_fee,
                         "mark_source":"orderbook_bid_ask" if book else "entry_fallback"}
        return out

    def status(self):
        value=super().status()
        closed=[t for t in self.trades if t.get("event")=="CLOSE"]
        analytics=self.position_analytics()
        value.update({"realized_pnl":sum(t.get("pnl",0) for t in closed),
                      "unrealized_pnl":sum(p["unrealized_pnl"] for p in analytics.values()),
                      "position_analytics":analytics,
                      "closed_trades":len(closed),
                      "performance_halted":self.performance_halted,
                      "session_closed_count":len(self.session_closes),
                      "session_closed_pnl":round(sum(self.session_closes),6),
                      "accounting_note":"Exit-marked PnL incl estimated fees/slippage; no funding or liquidation simulation"})
        value.update({"mode":"FUTURES_PAPER_ONLY","market":"BYBIT_LINEAR_USDT_PERPETUAL","leverage":1,
                      "funding_model":"NOT_IMPLEMENTED","liquidation_model":"NOT_IMPLEMENTED",
                      "positions":{symbol:asdict(pos) for symbol,pos in self.positions.items()}})
        return value
