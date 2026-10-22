import asyncio
import json
import logging
import os
import sqlite3
import time
from dataclasses import asdict
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from .ai import ShadowAgents
from .news import NewsMonitor
import websockets
import httpx
from .discovery import fetch_candidates, is_meme
from .core import Book, SYMBOLS
from .futures import FuturesPaperEngine, FuturesPosition
from .performance import report as performance_report
from .radar import OpportunityRadar

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)
engine = FuturesPaperEngine()
news = NewsMonitor(interval=int(os.getenv("NEWS_POLL_SECONDS", "180")))
shadow = ShadowAgents(max_reviews=int(os.getenv("AI_MAX_REVIEWS_PER_RUN", "20")), news_monitor=news)
shadow_reviews = []
shadow_tasks = set()
radar = OpportunityRadar()

def record_shadow(review):
    shadow_reviews.insert(0,review)
    del shadow_reviews[100:]
    persist("shadow_review",review)

DB_PATH = Path(os.getenv("DB_PATH", "/data/events.sqlite3"))
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "")


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
    }
    with sqlite3.connect(DB_PATH) as db:
        db.execute("CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT, logged_at TEXT DEFAULT CURRENT_TIMESTAMP, payload TEXT)")
        for trade in trades:
            db.execute("INSERT INTO events (kind,payload) VALUES (?,?)",("trade",json.dumps(trade)))
        db.execute("INSERT INTO events (kind,payload) VALUES (?,?)",("engine_state",json.dumps(state)))


def restore_portfolio():
    """Fail closed on uncheckpointed legacy trades; never silently reset a paper portfolio."""
    if not DB_PATH.exists(): return
    with sqlite3.connect(DB_PATH) as db:
        table=db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='events'").fetchone()
        if not table:return
        row=db.execute("SELECT payload FROM events WHERE kind='engine_state' ORDER BY id DESC LIMIT 1").fetchone()
        existing=db.execute("SELECT 1 FROM events WHERE kind='trade' LIMIT 1").fetchone()
        if row is None:
            if existing:
                engine.halted=True
                engine.last_error="LEGACY_TRADES_WITHOUT_CHECKPOINT: historical events preserved; portfolio halted until reconciliation"
            return
        try:
            data=json.loads(row[0])
            positions={k:FuturesPosition(**v) for k,v in data["positions"].items()}
            if not isinstance(data["cash"],(int,float)) or data["cash"]<0:
                raise ValueError("invalid saved cash")
            engine.cash=float(data["cash"])
            engine.positions=positions
            engine.peak_equity=float(data["peak_equity"])
            engine.day=data["day"]
            engine.day_start_equity=float(data["day_start_equity"])
            engine.halted=bool(data["halted"])
            engine.order_manager.seen=set(data.get("order_seen",[]))
            rows=db.execute("SELECT payload FROM events WHERE kind='trade' ORDER BY id DESC LIMIT 500").fetchall()
            from collections import deque
            engine.trades=deque((json.loads(t[0]) for t in rows),maxlen=500)
            # Keep checkpointed positions even if they are not in current discovery.
            engine.order_manager.allowed_symbols.update(positions)
            engine.last_error="Restored checkpointed paper portfolio; funding and liquidation still not modeled"
        except (KeyError,ValueError,TypeError) as exc:
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
                    if decision:
                        persist("decision",asdict(decision))
                        # Only a bounded sample is sent to optional shadow reviewers.
                        if shadow.enabled and shadow.reviews < shadow.max_reviews and len(shadow_tasks) < 2:
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


@asynccontextmanager
async def lifespan(app):
    restore_portfolio()
    task=asyncio.create_task(market_stream())
    news_task=asyncio.create_task(news.loop())
    radar_task=asyncio.create_task(radar_stream())
    try: yield
    finally:
        task.cancel()
        news_task.cancel()
        radar_task.cancel()
        for review_task in list(shadow_tasks): review_task.cancel()
        try: await task
        except asyncio.CancelledError: pass
        try: await news_task
        except asyncio.CancelledError: pass
        try: await radar_task
        except asyncio.CancelledError: pass

app=FastAPI(title="Bybit Multi-Agent Scalping Research MVP", lifespan=lifespan)


def secure(x_admin_token: str | None):
    # Fail closed when no admin token is configured.
    if not ADMIN_TOKEN or x_admin_token != ADMIN_TOKEN:
        raise HTTPException(403,"Unauthorized")

@app.get("/health")
def health(): return {"ok":True,"mode":"FUTURES_PAPER_ONLY","feed_connected":engine.feed_connected,"ranked_pairs":len(engine.candidates),"decisions":len(engine.decisions)}

@app.get("/status")
def status(x_admin_token: str | None=Header(default=None)):
    secure(x_admin_token)
    return engine.status()

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
    with sqlite3.connect(DB_PATH) as db:
        rows=db.execute("SELECT payload FROM events WHERE kind='trade' ORDER BY id").fetchall() if DB_PATH.exists() else []
    return performance_report([json.loads(r[0]) for r in rows])

@app.get("/events")
def events(x_admin_token: str | None=Header(default=None), limit:int=100):
    secure(x_admin_token)
    with sqlite3.connect(DB_PATH) as db:
        rows=db.execute("SELECT id,kind,logged_at,payload FROM events ORDER BY id DESC LIMIT ?",(min(max(limit,1),500),)).fetchall()
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
