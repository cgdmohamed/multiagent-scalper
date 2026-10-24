"""Isolated experimental paper ledger. Public quotes only; no exchange orders."""
import json
import sqlite3
import time
from pathlib import Path

class ExperimentalPaper:
    def __init__(self,path,initial=1000.):
        self.path=Path(path);self.initial=float(initial)
        self.enabled=False;self.cash=self.initial;self.position=None
        self.day_start=self.initial;self.day=None;self.peak=self.initial
        self.halted=False;self.trades=[];self.last_signal=set()
        self.strategy="EXECUTED_CVD_CONFIRM"
        self._restore()

    def _db(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        db=sqlite3.connect(self.path,timeout=10)
        db.execute("CREATE TABLE IF NOT EXISTS experimental_paper (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        return db

    def _save(self):
        obj={k:getattr(self,k) for k in ("enabled","cash","position","day_start","day",
             "peak","halted","trades","strategy")}
        with self._db() as db:
            db.execute("INSERT INTO experimental_paper(key,value) VALUES ('state',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(json.dumps(obj),))

    def _restore(self):
        with self._db() as db:
            row=db.execute("SELECT value FROM experimental_paper WHERE key='state'").fetchone()
        if row:
            obj=json.loads(row[0])
            for k in ("enabled","cash","position","day_start","day","peak","halted","trades","strategy"):
                if k in obj:setattr(self,k,obj[k])
        # Restart never silently resumes new entry authority.
        self.enabled=False
        self._save()

    def control(self,enable):
        if enable and self.halted:raise ValueError("PAPER_RISK_HALTED")
        self.enabled=bool(enable);self._save();return self.status()

    def status(self):
        return {"mode":"EXPERIMENTAL_PAPER_ONLY","enabled":self.enabled,
                "cash":round(self.cash,6),"equity_estimate":round(self.cash+(self.position or {}).get("margin",0),6),
                "position":self.position,"halted":self.halted,"peak_equity":self.peak,
                "strategy":self.strategy,"risk_per_trade_fraction":.001,"daily_loss_fraction":.005,
                "max_drawdown_fraction":.02,"recent_trades":self.trades[-30:],
                "note":"Unrealized PnL excluded unless latest public quote available; not exchange fills."}

    def on_quote(self,book,now_ms,signals,feed_ready=True):
        if not self.enabled:return
        if not feed_ready:return
        day=time.strftime("%Y-%m-%d",time.gmtime(now_ms/1000))
        if self.day!=day:
            self.day=day;self.day_start=self.cash+(self.position or {}).get("margin",0)
        if self.position:
            p=self.position
            if book.symbol!=p["symbol"]:return
            direction=p["direction"];exit_raw=book.bid if direction=="LONG" else book.ask
            exit_price=exit_raw*(1-.0002 if direction=="LONG" else 1+.0002)
            unreal=(exit_price-p["entry"])*(1 if direction=="LONG" else -1)*p["qty"]
            equity=self.cash+p["margin"]+unreal
            self.peak=max(self.peak,equity)
            reason=("STOP" if (exit_price<=p["stop"] if direction=="LONG" else exit_price>=p["stop"])
                    else "TARGET" if (exit_price>=p["target"] if direction=="LONG" else exit_price<=p["target"])
                    else "TIMEOUT" if now_ms-p["opened_ms"]>=15*60000 else None)
            if equity<=self.day_start*.995 or equity<=self.peak*.98:
                reason=reason or "RISK_EXIT";self.halted=True;self.enabled=False
            if reason:
                fee=exit_price*p["qty"]*.001
                pnl=unreal-fee-p["entry_fee"]
                self.cash+=p["margin"]+unreal-fee
                self.trades.append({"type":"CLOSE","symbol":book.symbol,"pnl":round(pnl,6),
                    "price":exit_price,"reason":reason,"at_ms":now_ms})
                self.position=None
                if self.cash<=self.day_start*.995 or self.cash<=self.peak*.98:
                    self.halted=True;self.enabled=False
                self._save()
            return
        if self.halted or book.spread_bps>3 or now_ms-book.received_ms>3000:return
        if self.cash<=self.day_start*.995 or self.cash<=self.peak*.98:
            self.halted=True;self.enabled=False;self._save();return
        for signal in signals:
            if signal.get("strategy")!=self.strategy or signal.get("symbol")!=book.symbol:continue
            key=signal.get("id")
            if not key or key in self.last_signal:continue
            self.last_signal.add(key)
            if len(self.last_signal)>3000:self.last_signal.clear();self.last_signal.add(key)
            direction=signal.get("direction")
            if direction not in ("LONG","SHORT"):continue
            # Half-spread implied in ask/bid, modeled 2bps adverse slippage and 10bps per-side fee.
            entry=(book.ask*1.0002 if direction=="LONG" else book.bid*.9998)
            stop=entry*(.9955 if direction=="LONG" else 1.0045)
            target=entry*(1.01 if direction=="LONG" else .99)
            # Cap loss including roundtrip fees to 0.1% of equity; cap allocation at 10%.
            per_unit=abs(entry-stop)+entry*.0024
            budget=self.cash*.001
            notional=min(self.cash*.1,budget*entry/per_unit)
            if notional<5:continue
            qty=notional/entry;fee=notional*.001
            self.position={"symbol":book.symbol,"direction":direction,"entry":entry,"stop":stop,
                           "target":target,"qty":qty,"margin":notional,"entry_fee":fee,
                           "opened_ms":now_ms,"signal_id":key}
            self.cash-=notional+fee
            self.trades.append({"type":"OPEN","symbol":book.symbol,"direction":direction,
                                "price":entry,"fee":fee,"at_ms":now_ms,"signal_id":key})
            self._save();return
