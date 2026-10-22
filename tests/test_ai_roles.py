import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest

from app.ai import ShadowAgents, validate_vote


def test_role_restrictions():
    assert validate_vote({"action":"SELL","reason":"trend"},"market")["action"]=="SELL"
    for role in ("adversary","news"):
        with pytest.raises(ValueError,match="INVALID_ACTION"):
            validate_vote({"action":"SELL","reason":"not my job"},role)


def test_chief_receives_all_four_reviews(monkeypatch):
    agents=ShadowAgents(key="test-key",model="gpt-4o-mini",max_reviews=1)
    seen=[]
    async def fake_vote(client,role,snapshot):
        seen.append((role,snapshot))
        return {"action":"SELL" if role in ("market","quant","chief") else "HOLD","reason":"test"}
    monkeypatch.setattr(agents,"_vote",fake_vote)
    decision=SimpleNamespace(symbol="BTCUSDT",snapshot_id="s1",decision_id="id1",
                             market={"direction":"SHORT"},verdict="APPROVE",reasons=[])
    reviews=[]
    asyncio.run(agents.review(decision,reviews.append))
    assert [role for role,_ in seen]==["market","quant","adversary","news","chief"]
    assert set(seen[-1][1]["reviewer_votes"])=={"market","quant","adversary","news"}
    assert reviews[0]["shadow_verdict"]=="SHORT"


def test_baseline_skip_never_shadow_approves(monkeypatch):
    agents=ShadowAgents(key="test-key",model="gpt-4o-mini",max_reviews=1)
    async def fake_vote(client,role,snapshot):
        return {"action":"SELL" if role in ("market","quant","chief") else "HOLD","reason":"test"}
    monkeypatch.setattr(agents,"_vote",fake_vote)
    decision=SimpleNamespace(symbol="BTCUSDT",snapshot_id="s1",decision_id="id1",
                             market={"direction":"SHORT"},verdict="SKIP",reasons=["SPREAD_TOO_WIDE"])
    reviews=[]
    asyncio.run(agents.review(decision,reviews.append))
    assert reviews[0]["shadow_verdict"]=="SKIP"


def test_invalid_action_repaired_once_and_gpt4o_no_reasoning(monkeypatch):
    agents=ShadowAgents(key="test-key",model="gpt-4o-mini")
    bodies=[]
    class FakeResponse:
        is_error=False
        def __init__(self,content):self.content=content
        def json(self):return {"choices":[{"message":{"content":self.content}}]}
    class Client:
        async def post(self,url,json,headers,timeout):
            bodies.append(json)
            return FakeResponse('{"action":"SELL","reason":"bad role"}' if len(bodies)==1 else '{"action":"HOLD","reason":"no news"}')
    output=asyncio.run(agents._vote(Client(),"news",{"symbol":"BTCUSDT"}))
    assert output["action"]=="HOLD"
    assert len(bodies)==2
    assert all("reasoning_effort" not in body for body in bodies)
    assert "Previous output failed validation" in bodies[-1]["messages"][-1]["content"]
