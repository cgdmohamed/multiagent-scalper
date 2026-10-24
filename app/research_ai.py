"""Optional bounded AI interpretation of deterministic research results.

The model receives aggregate numeric evidence only. No tools, no trading authority.
"""
import json
import os
import httpx

SYSTEM = """You are a research committee for an experimental trading system.
Provide one JSON object with keys research, quant, adversary, chief, each
a concise string <=500 characters. Research proposes a falsifiable hypothesis;
quant discusses sample size and costs; adversary finds selection/overfit risks;
chief summarizes next experiment. Never claim a strategy is validated, never
give orders, never change controls, and do not invent missing measurements."""

async def research_commentary(report):
    key=os.getenv("OPENAI_API_KEY","")
    if not key:return {"mode":"UNAVAILABLE","reason":"OPENAI_API_KEY_NOT_CONFIGURED"}
    model=os.getenv("OPENAI_RESEARCH_MODEL",os.getenv("OPENAI_MODEL","gpt-4o-mini"))
    # Bounded aggregate input, never send arbitrary market headlines or tool instructions.
    rows=[{"symbol":r["symbol"],"strategy":r["strategy"],
           "variant":r["hypothesis"],"training":r["quant_agent"]["training"],
           "holdout":r["quant_agent"]["holdout"],
           "veto_reasons":r["validation_agent"]["reasons"]}
          for r in report["hypothesis_reviews"][:20]]
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp=await client.post("https://api.openai.com/v1/chat/completions",
                headers={"Authorization":"Bearer "+key},
                json={"model":model,"response_format":{"type":"json_object"},
                      "messages":[{"role":"system","content":SYSTEM},
                                  {"role":"user","content":json.dumps({"examples":rows,
                                    "sampled":len(rows),"total_reviews":len(report["hypothesis_reviews"])})}]})
            resp.raise_for_status()
        data=json.loads(resp.json()["choices"][0]["message"]["content"])
        if not isinstance(data,dict) or any(not isinstance(data.get(k),str) for k in
                                            ("research","quant","adversary","chief")):
            raise ValueError("BAD_RESPONSE_SCHEMA")
        return {"mode":"ADVISORY_ONLY","model":model,
                "comments":{k:data[k][:500] for k in ("research","quant","adversary","chief")},
                "can_promote":False}
    except (httpx.HTTPError,KeyError,IndexError,TypeError,ValueError) as exc:
        return {"mode":"UNAVAILABLE","reason":type(exc).__name__}
