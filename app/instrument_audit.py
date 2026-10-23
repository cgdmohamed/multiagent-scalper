"""Read-only Bybit V5 instrument metadata classification for research eligibility."""
import asyncio
import httpx

async def audit(symbols):
    names=sorted({s for s in symbols if isinstance(s,str) and s.isalnum() and s.endswith("USDT")})[:25]
    async with httpx.AsyncClient(timeout=12) as client:
        async def fetch(symbol):
            try:
                response=await client.get("https://api.bybit.com/v5/market/instruments-info",
                                          params={"category":"linear","symbol":symbol})
                response.raise_for_status()
                payload=response.json()
                if payload.get("retCode")!=0:raise ValueError("exchange rejected instrument lookup")
                matches=[x for x in payload.get("result",{}).get("list",[]) if x.get("symbol")==symbol]
                if not matches:return {"symbol":symbol,"verified":False,"eligible_for_research":False,"reason":"NOT_LISTED"}
                x=matches[0]
                contract=x.get("contractType")
                status=x.get("status")
                settle=x.get("settleCoin")
                eligible=status=="Trading" and contract=="LinearPerpetual" and settle=="USDT"
                return {"symbol":symbol,"verified":True,"contract_type":contract,"status":status,
                        "settlement":settle,"eligible_for_research":eligible,
                        "reason":"LINEAR_USDT_PERPETUAL" if eligible else "NONSTANDARD_OR_NOT_TRADING"}
            except (httpx.HTTPError,ValueError,TypeError):
                return {"symbol":symbol,"verified":False,"eligible_for_research":False,"reason":"METADATA_UNAVAILABLE"}
        results=await asyncio.gather(*(fetch(s) for s in names))
    return {"mode":"RESEARCH_ONLY","source":"BYBIT_PUBLIC_INSTRUMENT_METADATA",
            "note":"Contract type does not prove asset economic exposure or execution liquidity; no live order authority.",
            "instruments":results}
