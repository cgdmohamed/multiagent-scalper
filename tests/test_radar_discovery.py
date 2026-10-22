from app.discovery import discover, is_meme
from app.radar import OpportunityRadar

def instrument(symbol):
    return {"symbol":symbol,"status":"Trading","quoteCoin":"USDT",
            "settleCoin":"USDT","contractType":"LinearPerpetual",
            "lotSizeFilter":{"minNotionalValue":"5","qtyStep":"1"},
            "priceFilter":{"tickSize":"0.0001"}}

def ticker(symbol,turnover="1000000",change="0.12"):
    return {"symbol":symbol,"turnover24h":turnover,"bid1Price":"1",
            "ask1Price":"1.001","price24hPcnt":change}

def test_meme_category_is_opt_in():
    assert is_meme("DOGEUSDT")
    assert is_meme("1000PEPEUSDT")
    assert not is_meme("BTCUSDT")
    assert not is_meme("SOXLUSDT")

def test_execution_discovery_still_uses_five_million_turnover():
    instruments=[instrument("DOGEUSDT"),instrument("BTCUSDT")]
    rows=[ticker("DOGEUSDT"),ticker("BTCUSDT",turnover="8000000")]
    assert [p.symbol for p in discover(instruments,rows)]==["BTCUSDT"]

def test_radar_watchlist_and_mode():
    radar=OpportunityRadar()
    radar.set_watchlist(["DOGEUSDT","BTCUSDT"])
    assert radar.status()["watchlist"]==["DOGEUSDT","BTCUSDT"]
    assert radar.status()["mode"]=="OBSERVE_ONLY"
