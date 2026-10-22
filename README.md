# Bybit Multi-Agent Scalping — Research MVP v0.1

**Status: experimental, PAPER-ONLY, no authenticated Bybit exchange API and no real exchange orders.** This is an executable foundation, *not* the approved full production architecture.

## Included
- Bybit public Spot WebSocket orderbook depth 50, BTCUSDT/ETHUSDT/SOLUSDT
- Reconstruct snapshot/delta locally; reject crossed/stale books
- Four deterministic **agent-role stubs**: market, quant, sentiment (abstains), adversary. These are **not separate LLM agents** yet.
- Evidence-linked decisions and no-trade reasons
- Cost-aware candidate filter (heuristic edge is not validated or calibrated)
- Paper execution with assumed spread/slippage/fees; stop/target/timeout; drawdown gates
- SQLite append-only event history, FastAPI read endpoints and tests
- Docker Compose for Coolify deployment; no secrets or order execution permissions needed

## Local start
```bash
cp .env.example .env
# Replace ADMIN_TOKEN in .env with a long random token
mkdir -p data
docker compose up --build -d
curl http://localhost:8800/health
curl -H "X-Admin-Token: YOUR_TOKEN" http://localhost:8800/status
curl -H "X-Admin-Token: YOUR_TOKEN" http://localhost:8800/decisions
curl -H "X-Admin-Token: YOUR_TOKEN" http://localhost:8800/events
```

## Coolify
Use **Docker Compose Application** from a Git repository, with `compose.yaml` at repo root. Set `ADMIN_TOKEN` as a secret environment variable and provide persistent volume `scalper_data`. Keep API **private** (the Compose mapping binds port 8800 to localhost); access through SSH tunneling or an authenticated private network. Avoid configuring a public domain for this service. See https://coolify.io/docs/applications/choose-deployment-method.

## Important limits and known gaps
1. **No live/demo Bybit order placement, no account authentication**. Paper simulator only.
2. Agent roles are explicit deterministic adapters, not independently prompted OpenAI models. Multi-LLM debate, chief investment agent, scoring, audit attribution, and model calibration are next milestone.
3. No historical replay/backtest, restart recovery of paper portfolio, Telegram, dashboard, PnL analytics, or private fills reconciliation yet.
4. Liquidity imbalance is not a forecast; initial entry threshold is arbitrary. Never interpret trial results as a validated edge.
5. Fees default to 10 bps per side and slippage 2 bps per side **placeholders**, not your Bybit account's terms. Correct before evaluating performance.
6. Stop is checked only on arriving quotes and simulated fills may gap; no guarantees for loss ceilings.
7. Underlying book updates may arrive faster than Python processes them. Confirm latency and packet gaps; do not use for HFT.
8. Using samples of *orderbook midpoints* for momentum is NOT equivalent to 1m/3m candlesticks; proper kline/trade features are pending.
9. The in-memory paper portfolio resets on restart while event history persists. Do not interpret cumulative SQLite trades as a consistent portfolio track record until restore/replay is implemented.
10. Daily/peak risk controls are preliminary and should remain stricter than any potential production risk control.

## Next milestones
- Real candle/trade feature engine, bounded event queues and sequence integrity
- Independent LLM agent contracts with per-agent deadlines, logged prompt/model versions and deterministic dispute resolution
- Deterministic chief/risk gate; position budget and price/qty tick-size validations
- Restart-safe PostgreSQL ledger and auditable execution state machine
- Bybit **Demo-only** private APIs, idempotent orders and reconciliation; explicitly separate credentials from Bybit production
- Replay/backtest with walk-forward splits and honest transaction-cost modeling
- Telegram and operational dashboard, reproducible performance scorecards, chaos/failure tests

Bybit public WS: https://bybit-exchange.github.io/docs/v5/ws/connect
Bybit demo service: https://bybit-exchange.github.io/docs/v5/demo

## v0.2 — Central Paper Order Manager

Added `app/orders.py` with:
- Single order-intent entry point, rejecting duplicate decision IDs and unsupported symbols.
- Local sliding-window limiter (default 3 intents per second), a safety throttle **not** a substitute for exchange limit tracking.
- Fail-closed kill switch and input validation.
- Explicit PAPER-only routing: DEMO and LIVE are *not implemented*; there is no authenticated exchange-order adapter.
- Order intent audit events in process memory.

**Important limitations:** No Bybit account connection, no authenticated Demo execution, and no LLM-backed agents yet. The router state and paper portfolio are not durable across process restarts; SQLite currently stores decision/trade event logs, not a resumable ledger. Running multiple replicas is unsupported. Bybit's per-endpoint/UID limit headers must be integrated before authenticated execution. Never expose the admin API publicly. Live execution requires separate architecture, approvals, and tests.

Bybit official API references: https://bybit-exchange.github.io/docs/v5/demo and https://bybit-exchange.github.io/docs/v5/rate-limit

## v0.3 — Dynamic Pair Discovery (research only)
- `app/discovery.py` fetches **public** Bybit V5 Spot instruments and tickers; selects USDT pairs with Trading status, 24h turnover >= 5M USDT, and top-of-book quoted spread <= 8 bps.
- Scores candidates using bounded 24h turnover, absolute 24h change, and spread penalty; this is a **non-predictive liquidity/movement heuristic**. Default top 5.
- Reconnects public WebSocket approximately every five minutes to update subscriptions. Open positions remain subscribed even when dropped from ranking. Reconnect gaps and outages mean stops/targets may be missed; no guarantees.
- Paper position size capped at 20% of equity per position and 40% aggregate entry notional, in addition to 0.25% estimated per-trade risk. This is spot-only and uses estimated stop, fees and slippage; risk can exceed limits under gaps.
- `GET /status` includes `ranked_pairs` with public-filter metrics (admin token required).
- No authenticated Bybit endpoints, no DEMO or LIVE order execution, no LLM agents, and no real account connection.
- **Not yet implemented:** symbol-specific tick size/quantity rounding on simulated fills; proper exchange min-order validation on every execution; persistent portfolio/order state restoration; order book historical replay; robust market stream sequence-gap handling; observable audited multi-agent forecasts; testing against the live exchange network.
- The previous BTC/ETH/SOL fixed-symbol engine has been replaced by rolling candidates; previous tests remain compatible. Do not deploy more than one engine replica.

## v0.4 dashboard and AI shadow-review

Open **`http://127.0.0.1:8800/dashboard`** from the server or via an SSH tunnel, enter the configured `ADMIN_TOKEN` (kept only in JavaScript memory), and monitor live paper state, pair rankings, simulated trades and shadow reviews. The application is intentionally bound to localhost in `compose.yaml`; do not expose it publicly without TLS, authentication, and appropriate network restrictions. The API is protected by `X-Admin-Token`; the dashboard HTML itself is public but contains no data or secret.

Optional `OPENAI_API_KEY` enables four *advisory* LLM reviews (market, quant, adversary, chief) per sampled baseline decision. Configure `AI_MAX_REVIEWS_PER_RUN` for a strict cap on review jobs per process lifetime (up to four API requests each). They are **SHADOW ONLY**, asynchronous, cannot place/change/cancel orders, and are not connected to the paper execution gate. Records appear under `/ai/status` and in the persisted `shadow_review` events. Without API key, rules-based paper trading continues unchanged. Costs depend on the model and number of reviews; set a low cap initially.

Comparison is **descriptive**, not performance attribution yet: baseline verdict and AI shadow verdict are saved together for subsequent replay/outcome scoring. Realized shadow-trade P&L, persistent paper positions across restarts, historical replay, secure multi-user access and Bybit Demo execution **are not implemented**. Never mistake AI agreement for proven edge. No Bybit trading credentials are read by this release.

Start with `docker compose --env-file .env up -d --build`; verify `GET /health`, `/dashboard` and authenticated `/ai/status`. As this is a research MVP, do not treat results as validated profitability.

## v0.5 — News & Event Risk Shadow Agent

- Polls two public crypto news RSS feeds (CoinDesk and Cointelegraph) every 180s by default (min 60s). Sources may change availability or format; failures are visible at `/news/status`.
- Parses **headlines only** plus publish time, source and link. Discards old (>24h), undated and future-dated events; deduplicates and flags simple event-risk keywords. **A headline flag is not confirmed news, sentiment accuracy or a trading signal.**
- Optional OpenAI `news` reviewer sees up to five related (or broad-market) headlines in its immutable shadow snapshot. Instructed to treat headlines as untrusted data and not as instructions. Fifth LLM request per reviewed decision when enabled; consider API costs.
- Authenticated `GET /news/status` and the dashboard display news-feed health, recent headlines, related assets and mechanical risk flags.
- No article crawling, breaking-news guarantees, external execution or strategy changes; failure of RSS sources does not authorize trades, and all AI output is **SHADOW ONLY**.
- Public RSS links are not authenticated Bybit services. The project remains experimental PAPER only.
