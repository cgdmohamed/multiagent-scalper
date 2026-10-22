import pytest
from app.orders import OrderManager,OrderIntent,RoutingError,SlidingWindowLimiter

def intent(id='a'):
    return OrderIntent(id,'BTCUSDT','BUY',.001,100000,'snapshot-1')

def test_paper_only():
    for mode in ('DEMO','LIVE'):
        with pytest.raises(RoutingError): OrderManager(mode)

def test_idempotency():
    m=OrderManager()
    assert m.submit(intent())['event']=='PAPER_INTENT_ACCEPTED'
    with pytest.raises(RoutingError,match='DUPLICATE'): m.submit(intent())

def test_kill_switch():
    m=OrderManager();m.kill()
    with pytest.raises(RoutingError,match='KILL_SWITCH'): m.submit(intent())

def test_rate_limit():
    now=[0.]
    limiter=SlidingWindowLimiter(2,1,lambda:now[0])
    assert limiter.acquire() and limiter.acquire()
    assert not limiter.acquire()
    now[0]=1.1
    assert limiter.acquire()

def test_invalid_intents():
    m=OrderManager()
    with pytest.raises(RoutingError): m.submit(OrderIntent('z','BTCUSDT','BUY',float('nan'),10,'s'))
    with pytest.raises(RoutingError): m.submit(OrderIntent('y','DOGEUSDT','BUY',1,10,'s'))
