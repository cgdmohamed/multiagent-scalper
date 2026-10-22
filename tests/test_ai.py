import pytest
from app.ai import ShadowAgents, validate_vote, ROLES

def test_shadow_disabled_without_key():
    assert not ShadowAgents(key='',max_reviews=2).enabled

def test_roles_independent():
    assert set(ROLES)=={'market','quant','adversary','chief','news'}

def test_vote_validation():
    assert validate_vote({'action':'VETO','reason':'spread'})['action']=='VETO'
    with pytest.raises(ValueError): validate_vote({'action':'EXECUTE','reason':'go'})
    with pytest.raises(ValueError): validate_vote({'action':'BUY','reason':''})

def test_no_execution_adapter():
    from app.orders import OrderManager,RoutingError
    with pytest.raises(RoutingError): OrderManager(mode='LIVE')
