import asyncio
from types import SimpleNamespace
from app.ai import ShadowAgents


def test_denied_luna_role_is_not_retried(monkeypatch):
    agents = ShadowAgents(key="test-only", model="gpt-6-luna", max_reviews=2)
    calls=[]
    async def fake_vote(client, role, snapshot):
        calls.append(role)
        if role != "chief":
            raise RuntimeError("OPENAI_HTTP_403")
        return {"action":"HOLD","reason":"No trade"}
    monkeypatch.setattr(agents,"_vote",fake_vote)
    decision=SimpleNamespace(symbol="BTCUSDT",snapshot_id="snap",decision_id="id",
        market={"direction":"SHORT"},verdict="SKIP",reasons=[])
    results=[]
    async def run():
        await agents.review(decision,results.append)
        await agents.review(decision,results.append)
    asyncio.run(run())
    assert calls.count("market")==1
    assert calls.count("quant")==1
    assert calls.count("adversary")==1
    assert calls.count("news")==1
    assert calls.count("chief")==2
    assert len(results)==2
    assert results[-1]["votes"]["market"]["reason"]=="API_UNAVAILABLE:OPENAI_HTTP_403"
