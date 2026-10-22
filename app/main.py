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
from .discovery import fetch_candidates
from .core import PaperEngine, Book, SYMBOLS

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)
engine = PaperEngine()
news = NewsMonitor(interval=int(os.getenv("NEWS_POLL_SECONDS", "180")))
shadow = ShadowAgents(max_reviews=int(os.getenv("AI_MAX_REVIEWS_PER_RUN", "20")), news_monitor=news)
shadow_reviews = []
shadow_tasks = set()

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


async def market_stream():
    url = "wss://stream.bybit.com/v5/public/spot"
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
            async with websockets.connect(url, ping_interval=20, ping_timeout=15, max_size=2**22) as ws:
                await ws.send(json.dumps({"op":"subscribe","args":[topic for symbol in watched for topic in (f"orderbook.50.{symbol}", f"kline.1.{symbol}", f"kline.3.{symbol}")]}))
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
                        for trade in list(engine.trades)[:len(engine.trades)-before][::-1]:persist("trade",trade)
        except asyncio.CancelledError: raise
        except Exception as exc:
            engine.last_error = f"{type(exc).__name__}: {str(exc)[:180]}"
            logger.warning("Market feed failed: %s",engine.last_error)
        finally:
            engine.feed_connected=False
        await asyncio.sleep(5)


@asynccontextmanager
async def lifespan(app):
    task=asyncio.create_task(market_stream())
    news_task=asyncio.create_task(news.loop())
    try: yield
    finally:
        task.cancel()
        news_task.cancel()
        for review_task in list(shadow_tasks): review_task.cancel()
        try: await task
        except asyncio.CancelledError: pass
        try: await news_task
        except asyncio.CancelledError: pass

app=FastAPI(title="Bybit Multi-Agent Scalping Research MVP", lifespan=lifespan)


def secure(x_admin_token: str | None):
    # Fail closed when no admin token is configured.
    if not ADMIN_TOKEN or x_admin_token != ADMIN_TOKEN:
        raise HTTPException(403,"Unauthorized")

@app.get("/health")
def health(): return {"ok":True,"mode":"PAPER_ONLY","feed_connected":engine.feed_connected}

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
            "recent_reviews":shadow_reviews[:30],"orders_controlled_by_ai":False}

@app.get("/news/status")
def news_status(x_admin_token: str | None=Header(default=None)):
    secure(x_admin_token)
    return news.status()
