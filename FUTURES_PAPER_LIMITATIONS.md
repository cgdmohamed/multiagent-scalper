# Futures Paper Mode — limitations

The currently deployed entrypoint uses public Bybit linear USDT perpetual market data. It simulates long and short positions at 1x with paper-only order intents.

**This is a research simulator, not a live or exchange Demo trading integration.** It does not yet model funding charges, liquidation, maintenance margin, all instrument-specific order validation, restart-safe position ledgers, or exchange-specific fills. Performance numbers are therefore not representative of actual futures results.

Health should report FUTURES_PAPER_ONLY. Check the authenticated status endpoint for books, candle readiness and decisions, and inspect reject reasons before changing strategy thresholds. Historical Spot trading records must not be combined with Futures performance.
