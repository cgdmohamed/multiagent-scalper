from app.discovery import discover
from app.core import PaperEngine,Settings,Book
from app.orders import OrderIntent

def instrument(s):
    return {'symbol':s,'status':'Trading','quoteCoin':'USDT','settleCoin':'USDT','contractType':'LinearPerpetual','lotSizeFilter':{'minNotionalValue':'5','qtyStep':'0.0001'},'priceFilter':{'tickSize':'0.01'}}

def ticker(s,turnover='10000000',bid='100',ask='100.01',change='0.03'):
    return {'symbol':s,'turnover24h':turnover,'bid1Price':bid,'ask1Price':ask,'price24hPcnt':change}

def test_rank_liquidity_and_spread():
    instruments=[instrument('AUSDT'),instrument('BUSDT'),instrument('CUSDT')]
    tickers=[ticker('AUSDT'),ticker('BUSDT',turnover='1000'),ticker('CUSDT',ask='101')]
    ranked=discover(instruments,tickers)
    assert [c.symbol for c in ranked]==['AUSDT']

def test_reject_nontrading_and_non_usdt():
    a=instrument('AUSDT');a['status']='PreLaunch'
    assert not discover([a,instrument('BTCUSDC')],[ticker('AUSDT'),ticker('BTCUSDC')])

def test_dynamic_pair_order_whitelist_and_sizing():
    e=PaperEngine(Settings(taker_fee_bps=10,slippage_bps_per_side=2))
    c=discover([instrument('XUSDT')],[ticker('XUSDT')])[0]
    e.set_candidates([c]);e.order_manager.allowed_symbols.add('XUSDT')
    b=Book('XUSDT',100,100.01,500,100,1000,1000,1)
    e._enter(b,1000,'unique-test')
    p=e.positions['XUSDT']
    assert p.qty*p.entry <= 200.000001
    assert p.qty*p.entry > 0
    assert 'XUSDT' in e.order_manager.allowed_symbols

def test_not_ranked_gate():
    e=PaperEngine()
    b=Book('XUSDT',100,100.01,500,100,1000,1000,1)
    assert 'NOT_RANKED_CANDIDATE' in e.gates(b,1000)
