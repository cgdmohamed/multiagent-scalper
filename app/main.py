import asyncio
import hashlib
import hmac
import secrets
import json
import logging
import os
import sqlite3
import time
from dataclasses import asdict
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import FileResponse
from .ai import ShadowAgents
from .news import NewsMonitor
import websockets
import httpx
from .discovery import fetch_candidates, is_meme
from .core import Book, SYMBOLS
from .futures import FuturesPaperEngine, FuturesPosition
from .performance import report as performance_report, cooldown_study, account_audit
from .radar import OpportunityRadar
from .reconciliation import analyze as analyze_legacy
from .strategy_lab import StrategyLab

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)
engine = FuturesPaperEngine()
news = NewsMonitor(interval=int(os.getenv("NEWS_POLL_SECONDS", "180")))
shadow = ShadowAgents(max_reviews=int(os.getenv("AI_MAX_REVIEWS_PER_RUN", "20")), news_monitor=news)
shadow_reviews = []
shadow_tasks = set()
radar = OpportunityRadar()
lab = StrategyLab()
engine.research_only = True
SESSION_STARTED_AT = time.strftime("%Y-%m-%dT%H:%M:%SZ",time.gmtime())
PORTFOLIO_RECOVERY = "FRESH_NO_HISTORY"

def record_shadow(review):
    shadow_reviews.insert(0,review)
    del shadow_reviews[100:]
    persist("shadow_review",review)

DB_PATH = Path(os.getenv("DB_PATH", "/data/events.sqlite3"))
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "")
SESSION_LIFETIME = 7*24*3600
MANUALLY_PAUSED = False
BOT_STOPPED = False
BOT_TASKS = {}
BOT_LOCK = asyncio.Lock()


def auth_cookie_value():
    issued=str(int(time.time()))
    nonce=secrets.token_urlsafe(16)
    body=f"{issued}.{nonce}"
    mac=hmac.new(ADMIN_TOKEN.encode(),("scalper-session:"+body).encode(),hashlib.sha256).hexdigest()
    return body+"."+mac


def cookie_valid(value):
    if not ADMIN_TOKEN or not value:return False
    try:
        issued,nonce,signature=value.split(".")
        age=int(time.time())-int(issued)
        if not 0<=age<=SESSION_LIFETIME or not nonce or len(nonce)>64:return False
        expected=hmac.new(ADMIN_TOKEN.encode(),f"scalper-session:{issued}.{nonce}".encode(),hashlib.sha256).hexdigest()
        return hmac.compare_digest(signature,expected)
    except (ValueError,AttributeError):
        return False


def save_operator_pause(paused):
    DB_PATH.parent.mkdir(parents=True,exist_ok=True)
    with sqlite3.connect(DB_PATH) as db:
        db.execute("CREATE TABLE IF NOT EXISTS operator_settings (name TEXT PRIMARY KEY, value TEXT NOT NULL)")
        db.execute("INSERT INTO operator_settings(name,value) VALUES ('paused',?) ON CONFLICT(name) DO UPDATE SET value=excluded.value",("1" if paused else "0",))


def restore_operator_pause():
    global MANUALLY_PAUSED, BOT_STOPPED
    if not DB_PATH.exists():return
    with sqlite3.connect(DB_PATH) as db:
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='operator_settings' AND type='table'").fetchone():
            row=db.execute("SELECT value FROM operator_settings WHERE name='paused'").fetchone()
            MANUALLY_PAUSED=bool(row and row[0]=="1")
            stopped=db.execute("SELECT value FROM operator_settings WHERE name='stopped'").fetchone()
            BOT_STOPPED=bool(stopped and stopped[0]=="1")
    engine.operator_paused=MANUALLY_PAUSED or BOT_STOPPED


def persist(kind, payload):
    DB_PATH.parent.mkdir(parents=True,exist_ok=True)
    with sqlite3.connect(DB_PATH) as db:
        db.execute("CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT, logged_at TEXT DEFAULT CURRENT_TIMESTAMP, payload TEXT)")
        db.execute("INSERT INTO events (kind,payload) VALUES (?,?)",(kind,json.dumps(payload)))


def save_trade_batch(trades):
    """Atomic trade ledger + portfolio state checkpoint in the same SQLite transaction."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    state = {
        "cash": engine.cash, "positions": {k:asdict(v) for k,v in engine.positions.items()},
        "peak_equity": engine.peak_equity, "day": engine.day,
        "day_start_equity": engine.day_start_equity, "halted": engine.halted,
        "order_seen": list(engine.order_manager.seen),
        "last_stops":engine.last_stops,"session_closes":list(engine.session_closes),"performance_halted":engine.performance_halted,
    }
    with sqlite3.connect(DB_PATH) as db:
        db.execute("CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT, logged_at TEXT DEFAULT CURRENT_TIMESTAMP, payload TEXT)")
        for trade in trades:
            db.execute("INSERT INTO events (kind,payload) VALUES (?,?)",("trade",json.dumps(trade)))
        db.execute("INSERT INTO events (kind,payload) VALUES (?,?)",("engine_state",json.dumps(state)))


def restore_portfolio():
    """Fail closed on uncheckpointed legacy trades; never silently reset a paper portfolio."""
    global PORTFOLIO_RECOVERY
    if not DB_PATH.exists(): return
    with sqlite3.connect(DB_PATH) as db:
        table=db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='events'").fetchone()
        if not table:return
        row=db.execute("SELECT payload FROM events WHERE kind='engine_state' ORDER BY id DESC LIMIT 1").fetchone()
        existing=db.execute("SELECT 1 FROM events WHERE kind='trade' LIMIT 1").fetchone()
        if row is None:
            if existing:
                PORTFOLIO_RECOVERY="UNRECONCILED_LEGACY_HISTORY"
                engine.halted=True
                engine.last_error="LEGACY_TRADES_WITHOUT_CHECKPOINT: historical events preserved; portfolio halted until reconciliation"
            return
        try:
            data=json.loads(row[0])
            positions={k:FuturesPosition(**v) for k,v in data["positions"].items()}
            if not isinstance(data["cash"],(int,float)) or data["cash"]<0:
                raise ValueError("invalid saved cash")
            engine.cash=float(data["cash"])
            PORTFOLIO_RECOVERY="NEW_PAPER_SESSION_RESTORED" if data.get("new_session") else "CHECKPOINT_RESTORED"
            engine.positions=positions
            engine.peak_equity=float(data["peak_equity"])
            engine.day=data["day"]
            engine.day_start_equity=float(data["day_start_equity"])
            engine.halted=bool(data["halted"])
            engine.order_manager.seen=set(data.get("order_seen",[]))
            engine.last_stops={k:int(v) for k,v in data.get("last_stops",{}).items()}
            from collections import deque
            engine.session_closes=deque(data.get("session_closes",[]),maxlen=200)
            engine.performance_halted=bool(data.get("performance_halted",False))
            engine.halted=engine.halted or engine.performance_halted
            rows=db.execute("SELECT payload FROM events WHERE kind='trade' ORDER BY id DESC LIMIT 500").fetchall()
            from collections import deque
            engine.trades=deque((json.loads(t[0]) for t in rows),maxlen=500)
            # Keep checkpointed positions even if they are not in current discovery.
            engine.order_manager.allowed_symbols.update(positions)
            engine.last_error="Restored checkpointed paper portfolio; funding and liquidation still not modeled"
        except (KeyError,ValueError,TypeError) as exc:
            PORTFOLIO_RECOVERY="CHECKPOINT_INVALID"
            engine.halted=True
            engine.last_error=f"CORRUPT_CHECKPOINT: {type(exc).__name__}; trading halted"


async def prime_candles(client, symbols):
    # REST history is required because 3m confirmations arrive slower than
    # the five-minute candidate rotation. Exclude any still-open candle.
    now_ms = int(time.time() * 1000)
    async def load(symbol, interval):
        resp = await client.get(
            "https://api.bybit.com/v5/market/kline",
            params={"category":"linear","symbol":symbol,"interval":interval,"limit":20},
            timeout=12.0,
        )
        resp.raise_for_status()
        payload=resp.json()
        if payload.get("retCode") != 0:
            raise RuntimeError(f"Kline API retCode={payload.get('retCode')}")
        duration=int(interval)*60000
        for bar in sorted(payload.get("result",{}).get("list",[]), key=lambda b:int(b[0])):
            start=int(bar[0])
            if start+duration <= now_ms:
                engine.on_candle(symbol,interval,start,float(bar[4]))
    for symbol in symbols:
        for interval in ("1","3"):
            try:
                await load(symbol,interval)
            except Exception as exc:
                logger.warning("Candle preload failed for %s %sm: %s",symbol,interval,exc)

def subscription_batches(symbols, batch_size=10):
    topics=[topic for symbol in symbols for topic in
            (f"orderbook.50.{symbol}", f"kline.1.{symbol}", f"kline.3.{symbol}")]
    return [topics[i:i+batch_size] for i in range(0,len(topics),batch_size)]


async def market_stream():
    url = "wss://stream.bybit.com/v5/public/linear"
    # Refresh candidates between socket sessions. Always retain open positions.
    while True:
        try:
            async with httpx.AsyncClient() as client:
                ranked = await fetch_candidates(client)
            if not ranked:
                raise RuntimeError("No eligible pairs: fail closed")
            engine.set_candidates(ranked)
            engine.order_manager.allowed_symbols.update(p.symbol for p in ranked)
            watched = sorted(set(p.symbol for p in ranked) | set(engine.positions))
            async with httpx.AsyncClient() as candle_client:
                await prime_candles(candle_client, watched)
            async with websockets.connect(url, ping_interval=20, ping_timeout=15, max_size=2**22) as ws:
                # Bybit Spot permits at most 10 args PER subscription request.
                for index, batch in enumerate(subscription_batches(watched)):
                    await ws.send(json.dumps({"op":"subscribe", "req_id":f"scalper-{index}",
                                              "args":batch}))
                engine.feed_connected = True
                engine.last_error = None
                logger.info("Bybit spot candidates: %s", watched)
                depth = {}
                refresh_at = time.monotonic()+300
                while time.monotonic() < refresh_at:
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
                    except asyncio.TimeoutError:
                        continue
                    event = json.loads(raw)
                    if event.get("op") == "subscribe":
                        if event.get("success") is False:
                            raise RuntimeError(f"Bybit subscription rejected: {event.get('ret_msg')}")
                        logger.info("Bybit subscription acknowledgement: %s", event.get("req_id"))
                        continue
                    topic = event.get("topic", "")
                    if topic.startswith("kline."):
                        symbol = topic.rsplit(".", 1)[-1]
                        if symbol in watched:
                            for bar in event.get("data", []):
                                if bar.get("confirm") is True:
                                    engine.on_candle(symbol, str(bar.get("interval")), int(bar.get("start")), float(bar.get("close")))
                        continue
                    if not topic.startswith("orderbook.50."): continue
                    data = event.get("data", {})
                    symbol = data.get("s")
                    if symbol not in watched: continue
                    if event.get("type")=="snapshot" or data.get("u")==1:
                        depth[symbol] = ({}, {})
                    elif symbol not in depth:
                        continue
                    bids, asks = depth[symbol]
                    for price,qty in data.get("b",[]):
                        price,qty=float(price),float(qty)
                        if qty: bids[price]=qty
                        else: bids.pop(price,None)
                    for price,qty in data.get("a",[]):
                        price,qty=float(price),float(qty)
                        if qty: asks[price]=qty
                        else: asks.pop(price,None)
                    if not bids or not asks: continue
                    bid_levels=sorted(bids, reverse=True)[:50]
                    ask_levels=sorted(asks)[:50]
                    depth[symbol]=({p:bids[p] for p in bid_levels},{p:asks[p] for p in ask_levels})
                    bid=max(depth[symbol][0]); ask=min(depth[symbol][1])
                    now_ms=int(time.time()*1000)
                    exchange_ms=int(event.get("ts") or now_ms)
                    if abs(exchange_ms-now_ms)>5000: continue
                    book=Book(symbol,bid,ask,sum(depth[symbol][0].values()),sum(depth[symbol][1].values()),exchange_ms,now_ms,int(data.get("u") or 0))
                    before=len(engine.trades)
                    decision=engine.on_book(book,now_ms)
                    m1,m3=engine.candle_momentum(book.symbol)
                    lab.observe(book,m1,m3)
                    if decision:
                        persist("decision",asdict(decision))
                        # Only a bounded sample is sent to optional shadow reviewers.
                        if (not engine.research_only and decision.verdict=='APPROVE' and shadow.enabled and shadow.reviews < shadow.max_reviews and len(shadow_tasks) < 2):
                            task = asyncio.create_task(shadow.review(decision,record_shadow))
                            shadow_tasks.add(task)
                            task.add_done_callback(shadow_tasks.discard)
                    if len(engine.trades)>before:
                        save_trade_batch(list(engine.trades)[:len(engine.trades)-before][::-1])
        except asyncio.CancelledError: raise
        except Exception as exc:
            engine.last_error = f"{type(exc).__name__}: {str(exc)[:180]}"
            logger.warning("Market feed failed: %s",engine.last_error)
        finally:
            engine.feed_connected=False
        await asyncio.sleep(5)


async def radar_stream():
    """Independent bounded public-trade feed across up to 20 liquid markets."""
    while True:
        try:
            async with httpx.AsyncClient() as client:
                candidates=await fetch_candidates(client,top_n=50,min_turnover=500_000,max_spread_bps=25,radar_mode=True,meme_slots=15)
            symbols=[c.symbol for c in candidates]
            radar.set_watchlist(symbols)
            if not symbols:raise RuntimeError("No radar instruments")
            async with websockets.connect("wss://stream.bybit.com/v5/public/linear",
                                          ping_interval=20,ping_timeout=15,max_size=2**22) as ws:
                topics=[f"publicTrade.{symbol}" for symbol in symbols]
                for i in range(0,len(topics),10):
                    await ws.send(json.dumps({"op":"subscribe","args":topics[i:i+10]}))
                until=time.monotonic()+300
                while time.monotonic()<until:
                    try:message=json.loads(await asyncio.wait_for(ws.recv(),timeout=2))
                    except asyncio.TimeoutError:continue
                    if message.get("op")=="subscribe":
                        if message.get("success") is False:raise RuntimeError("Radar subscription rejected")
                        continue
                    if not message.get("topic","").startswith("publicTrade."):continue
                    symbol=message["topic"].split(".",1)[1]
                    rows=message.get("data",[])
                    before_alerts=radar.count
                    radar.ingest(symbol,rows)
                    if radar.count>before_alerts:
                        persist("radar_alert",radar.alerts[0].copy())
                    if rows:
                        try:radar.mark(symbol,float(rows[-1]["p"]))
                        except (ValueError,KeyError,TypeError):pass
        except asyncio.CancelledError:raise
        except Exception as exc:logger.warning("Radar reconnecting: %s",str(exc)[:150])
        await asyncio.sleep(5)


def persist_bot_stopped(stopped):
    DB_PATH.parent.mkdir(parents=True,exist_ok=True)
    with sqlite3.connect(DB_PATH) as db:
        db.execute("CREATE TABLE IF NOT EXISTS operator_settings (name TEXT PRIMARY KEY, value TEXT NOT NULL)")
        db.execute("INSERT INTO operator_settings(name,value) VALUES ('stopped',?) ON CONFLICT(name) DO UPDATE SET value=excluded.value",("1" if stopped else "0",))


def launch_bot_tasks():
    if BOT_STOPPED:return
    for name,fn in (("market",market_stream),("news",news.loop),("radar",radar_stream)):
        if name not in BOT_TASKS or BOT_TASKS[name].done():
            BOT_TASKS[name]=asyncio.create_task(fn())


async def shutdown_bot_tasks():
    tasks=list(BOT_TASKS.values())+list(shadow_tasks)
    for task in tasks:task.cancel()
    if tasks:
        done,pending=await asyncio.wait(tasks,timeout=5)
        if pending:
            logger.warning("Stop requested; %d worker(s) still cancelling",len(pending))
            # Fail closed: keep worker references and deny new entries until they finish.
            for task in pending:task.add_done_callback(lambda _: None)
    BOT_TASKS.clear()
    engine.feed_connected=False


@asynccontextmanager
async def lifespan(app):
    restore_portfolio()
    restore_operator_pause()
    launch_bot_tasks()
    try: yield
    finally:
        await shutdown_bot_tasks()


app=FastAPI(title="Bybit Multi-Agent Scalping Research MVP", lifespan=lifespan)


@app.middleware("http")
async def browser_session_auth(request: Request, call_next):
    """Cookie auth requires a non-simple CSRF header for mutations.

    Do not compare Origin with the internal reverse-proxy Host: Coolify may
    forward a different host. Explicit token login always stays independent
    of an already-present browser cookie.
    """
    cookie=request.cookies.get("scalper_session")
    has_explicit_token=bool(request.headers.get("x-admin-token"))
    if cookie_valid(cookie) and not has_explicit_token:
        if request.method not in ("GET","HEAD","OPTIONS"):
            if request.headers.get("x-scalper-csrf") != "1":
                return Response(status_code=403,content="Missing CSRF protection header")
            site=request.headers.get("sec-fetch-site")
            if site in ("cross-site","same-site"):
                return Response(status_code=403,content="Cross-origin request rejected")
        headers=list(request.scope["headers"])
        headers.append((b"x-admin-token",ADMIN_TOKEN.encode()))
        request.scope["headers"]=headers
    response=await call_next(request)
    if request.url.path.startswith(("/auth/","/control/")):
        response.headers["Cache-Control"]="no-store"
    return response


@app.post("/auth/login")
def browser_login(response: Response, x_admin_token: str | None=Header(default=None)):
    secure(x_admin_token)
    response.set_cookie("scalper_session",auth_cookie_value(),max_age=SESSION_LIFETIME,
                        httponly=True,secure=True,samesite="strict",path="/")
    response.headers["Cache-Control"]="no-store"
    return {"authenticated":True,"session_days":7}


@app.get("/auth/session")
def browser_session(x_admin_token: str | None=Header(default=None)):
    secure(x_admin_token)
    return {"authenticated":True,"session_days":7}


@app.post("/auth/logout")
def browser_logout(response:Response,x_admin_token: str | None=Header(default=None)):
    secure(x_admin_token)
    response.delete_cookie("scalper_session",path="/",secure=True,samesite="strict",httponly=True)
    return {"authenticated":False}


@app.post("/control/stop")
async def fully_stop_bot(x_admin_token: str | None=Header(default=None)):
    global BOT_STOPPED
    secure(x_admin_token)
    async with BOT_LOCK:
        if engine.positions:
            raise HTTPException(409,"Cannot stop all monitoring with open paper positions; use Pause until flat")
        BOT_STOPPED=True
        engine.operator_paused=True
        persist_bot_stopped(True)
        await shutdown_bot_tasks()
        persist("operator_control",{"action":"STOP","mode":"PAPER_ONLY"})
        return {"bot_stopped":True,"running_tasks":0,"dashboard_available":True}


@app.post("/control/start")
async def fully_start_bot(x_admin_token: str | None=Header(default=None)):
    global BOT_STOPPED
    secure(x_admin_token)
    async with BOT_LOCK:
        BOT_STOPPED=False
        persist_bot_stopped(False)
        engine.operator_paused=MANUALLY_PAUSED
        launch_bot_tasks()
        persist("operator_control",{"action":"START","mode":"PAPER_ONLY"})
        return {"bot_stopped":False,"operator_paused":MANUALLY_PAUSED,"risk_halted":engine.halted}


@app.post("/control/pause")
def pause_new_entries(x_admin_token: str | None=Header(default=None)):
    global MANUALLY_PAUSED
    secure(x_admin_token)
    save_operator_pause(True)
    MANUALLY_PAUSED=True
    engine.operator_paused=True
    return {"operator_paused":True,"risk_halted":engine.halted,"open_positions_unaffected":True}


@app.post("/control/run")
def resume_new_entries(x_admin_token: str | None=Header(default=None)):
    global MANUALLY_PAUSED
    secure(x_admin_token)
    save_operator_pause(False)
    MANUALLY_PAUSED=False
    engine.operator_paused=BOT_STOPPED
    return {"operator_paused":False,"risk_halted":engine.halted,"note":"Risk circuit breaker is never overridden"}



def secure(x_admin_token: str | None):
    # Fail closed when no admin token is configured.
    if not ADMIN_TOKEN or x_admin_token != ADMIN_TOKEN:
        raise HTTPException(403,"Unauthorized")

@app.get("/health")
def health(): return {"ok":True,"mode":"FUTURES_PAPER_ONLY","feed_connected":engine.feed_connected,"ranked_pairs":len(engine.candidates),"decisions":len(engine.decisions)}

@app.get("/status")
def status(x_admin_token: str | None=Header(default=None)):
    secure(x_admin_token)
    current=engine.status()
    current["research_only"]=engine.research_only
    current["bot_state"]="STOPPED" if BOT_STOPPED else "PAUSED" if MANUALLY_PAUSED else "RISK_HALTED" if engine.halted else "RUNNING"
    current["operator_paused"]=MANUALLY_PAUSED
    current["bot_stopped"]=BOT_STOPPED
    current["background_tasks"]={name:not task.done() for name,task in BOT_TASKS.items()}
    current["portfolio_recovery"]=PORTFOLIO_RECOVERY
    current["halt_diagnostic"]="LEGACY_HISTORY_REQUIRES_RECONCILIATION" if PORTFOLIO_RECOVERY=="UNRECONCILED_LEGACY_HISTORY" else "CHECKPOINT_INVALID" if PORTFOLIO_RECOVERY=="CHECKPOINT_INVALID" else "RISK_LIMIT_OR_RESTORED_HALT" if engine.halted else "NONE"
    return current

@app.get("/decisions")
def decisions(x_admin_token: str | None=Header(default=None)):
    secure(x_admin_token)
    return [asdict(d) for d in engine.decisions]

@app.get("/trades")
def trades(x_admin_token: str | None=Header(default=None)):
    secure(x_admin_token)
    return list(engine.trades)

@app.get("/performance")
def performance(x_admin_token: str | None=Header(default=None)):
    secure(x_admin_token)
    if not DB_PATH.exists():
        return performance_report([])
    with sqlite3.connect(DB_PATH) as db:
        has_table=db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='events'").fetchone()
        rows=db.execute("SELECT payload FROM events WHERE kind='trade' ORDER BY id").fetchall() if has_table else []
    return performance_report([json.loads(r[0]) for r in rows])

def load_historical_trades():
    if not DB_PATH.exists():return []
    with sqlite3.connect(DB_PATH) as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='events'").fetchone():return []
        return [json.loads(r[0]) for r in db.execute("SELECT payload FROM events WHERE kind='trade' ORDER BY id")]


@app.get("/accounting/audit")
def accounting_audit(x_admin_token: str | None=Header(default=None)):
    secure(x_admin_token)
    trades=load_historical_trades()
    audit=account_audit(trades,engine.cash,engine.positions,engine.cfg.initial_cash)
    audit.update({"recovery_status":PORTFOLIO_RECOVERY,"halted":engine.halted,
                  "session_started_at":SESSION_STARTED_AT,
                  "current_session_realized_pnl":sum(float(t.get("pnl",0)) for t in engine.trades if t.get("event")=="CLOSE" and t.get("timestamp","")>=SESSION_STARTED_AT),
                  "reconciliation":"UNVERIFIED" if PORTFOLIO_RECOVERY!="CHECKPOINT_RESTORED" else "RESTORED_CHECKPOINT"})
    return audit


@app.get("/performance/cooldown-study")
def cooldown_analysis(x_admin_token: str | None=Header(default=None)):
    secure(x_admin_token)
    return cooldown_study(load_historical_trades())


@app.get("/reconciliation")
def reconciliation(x_admin_token: str | None=Header(default=None)):
    secure(x_admin_token)
    result=analyze_legacy(load_historical_trades())
    result["recovery_status"]=PORTFOLIO_RECOVERY
    result["trading_halted"]=engine.halted
    return result


@app.post("/paper/new-session")
def start_fresh_paper_session(confirmation: str, x_admin_token: str | None=Header(default=None)):
    """Explicit operator choice; never infer an account balance from legacy events."""
    global PORTFOLIO_RECOVERY
    secure(x_admin_token)
    if confirmation != "START_NEW_PAPER_SESSION_KEEP_HISTORY":
        raise HTTPException(400,"Exact acknowledgement required")
    if PORTFOLIO_RECOVERY not in ("UNRECONCILED_LEGACY_HISTORY","CHECKPOINT_INVALID"):
        raise HTTPException(409,"New session is only permitted for an unreconciled or invalid legacy wallet")
    if engine.positions:
        raise HTTPException(409,"Positions are still tracked; cannot start a fresh paper session")
    if not engine.halted:
        raise HTTPException(409,"Engine must be halted before creating a new paper session")
    state={"cash":engine.cfg.initial_cash,"positions":{},"peak_equity":engine.cfg.initial_cash,
           "day":None,"day_start_equity":engine.cfg.initial_cash,"halted":False,
           "order_seen":[],"new_session":True}
    DB_PATH.parent.mkdir(parents=True,exist_ok=True)
    with sqlite3.connect(DB_PATH) as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT, logged_at TEXT DEFAULT CURRENT_TIMESTAMP, payload TEXT)")
        existing=db.execute("SELECT 1 FROM events WHERE kind='paper_session_start' LIMIT 1").fetchone()
        if existing:
            raise HTTPException(409,"A fresh session has already been created; inspect checkpoints")
        db.execute("INSERT INTO events (kind,payload) VALUES (?,?)",("paper_session_start",json.dumps({"mode":"PAPER_ONLY","legacy_history_preserved":True,"initial_cash":engine.cfg.initial_cash})))
        db.execute("INSERT INTO events (kind,payload) VALUES (?,?)",("engine_state",json.dumps(state)))
    engine.cash=engine.cfg.initial_cash
    engine.positions.clear()
    engine.trades.clear()
    engine.order_manager.seen.clear()
    engine.peak_equity=engine.cfg.initial_cash
    engine.day=None
    engine.day_start_equity=engine.cfg.initial_cash
    engine.halted=False
    engine.performance_halted=False
    engine.session_closes.clear()
    engine.last_stops.clear()
    engine.last_error=None
    PORTFOLIO_RECOVERY="NEW_PAPER_SESSION"
    return {"status":"NEW_PAPER_SESSION_STARTED","starting_cash":engine.cfg.initial_cash,
            "legacy_history_preserved":True,"execution_mode":"PAPER_ONLY"}


@app.get("/strategy-lab")
def strategy_lab_status(x_admin_token: str | None=Header(default=None)):
    secure(x_admin_token)
    return lab.report()

@app.get("/events")
def events(x_admin_token: str | None=Header(default=None), limit:int=50,
           before_id:int | None=None, kind:str | None=None,
           symbol:str | None=None, date_from:str | None=None, date_to:str | None=None):
    secure(x_admin_token)
    allowed={"trade","decision","shadow_review","radar_alert","engine_state","paper_session_start","operator_control"}
    if kind and kind not in allowed: raise HTTPException(400,"Invalid event kind")
    if before_id is not None and before_id<1: raise HTTPException(400,"Invalid cursor")
    if symbol and (len(symbol)>32 or not symbol.isalnum()): raise HTTPException(400,"Invalid symbol")
    for value in (date_from,date_to):
        if value and (len(value)!=10 or value[4]!='-' or value[7]!='-'):
            raise HTTPException(400,"Date format must be YYYY-MM-DD")
    if not DB_PATH.exists():return []
    conditions=[]; params=[]
    if kind:conditions.append("kind=?");params.append(kind)
    if before_id is not None:conditions.append("id<?");params.append(before_id)
    if date_from:conditions.append("logged_at>=?");params.append(date_from+" 00:00:00")
    if date_to:conditions.append("logged_at<?");params.append(date_to+" 23:59:59.999")
    if symbol:conditions.append("json_extract(payload, '$.symbol')=?");params.append(symbol.upper())
    where=(" WHERE "+" AND ".join(conditions)) if conditions else ""
    with sqlite3.connect(DB_PATH) as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='events'").fetchone():return []
        rows=db.execute("SELECT id,kind,logged_at,payload FROM events"+where+" ORDER BY id DESC LIMIT ?",(*params,min(max(limit,1),100))).fetchall()
    return [{"id":r[0],"kind":r[1],"logged_at":r[2],"payload":json.loads(r[3])} for r in rows]

@app.get("/dashboard", include_in_schema=False)
def dashboard():
    return FileResponse(Path(__file__).parent / "static" / "index.html",headers={"Cache-Control":"no-store"})

@app.get("/ai/status")
def ai_status(x_admin_token: str | None=Header(default=None)):
    secure(x_admin_token)
    return {"enabled":shadow.enabled,"mode":"SHADOW_ONLY","model":shadow.model if shadow.enabled else None,
            "reviews_started":shadow.reviews,"max_reviews_per_run":shadow.max_reviews,
            "recent_reviews":shadow_reviews[:30],"orders_controlled_by_ai":False,
            "chief_model":shadow.chief_model if shadow.enabled else None,
            "agent_errors":shadow.agent_errors,"agent_successes":shadow.agent_successes,"blocked_roles":shadow.blocked_roles}

@app.get("/radar/status")
def radar_status(x_admin_token: str | None=Header(default=None)):
    secure(x_admin_token)
    state=radar.status()
    state['meme_watchlist']=[symbol for symbol in radar.watchlist if is_meme(symbol)]
    return state

@app.get("/news/status")
def news_status(x_admin_token: str | None=Header(default=None)):
    secure(x_admin_token)
    return news.status()
