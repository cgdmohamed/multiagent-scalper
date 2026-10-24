"""Deterministic research coordinator. Optional AI can comment, never promote."""
from collections import defaultdict
from .entry_experiments import experiment

def research_cycle(signals,bars_by_symbol,fee_bps=10,slippage_bps=2,hold_minutes=15):
    study=experiment(signals,bars_by_symbol,fee_bps=fee_bps,
                     slippage_bps=slippage_bps,hold_minutes=hold_minutes)
    grouped=defaultdict(list)
    for row in study["results"]:
        grouped[(row["symbol"],row["strategy"])].append(row)
    reviews=[]
    for (symbol,strategy),rows in sorted(grouped.items()):
        baseline=next((r for r in rows if r["variant"]=="NEXT_OPEN_FIXED"),None)
        if baseline is None:continue
        for row in rows:
            if row["variant"]=="NEXT_OPEN_FIXED":continue
            train=row["train"];test=row["holdout"]
            reasons=[]
            if train["n"]<30:reasons.append("TRAIN_SAMPLE_TOO_SMALL")
            if test["n"]<20:reasons.append("HOLDOUT_SAMPLE_TOO_SMALL")
            if train["mean_net_bps"] is None or train["mean_net_bps"]<=0:
                reasons.append("TRAIN_EXPECTANCY_NONPOSITIVE")
            if test["mean_net_bps"] is None or test["mean_net_bps"]<=0:
                reasons.append("HOLDOUT_EXPECTANCY_NONPOSITIVE")
            # Cannot compare just mean return when strategies trade different subsets.
            if row["variant"] in ("CONFIRM_CLOSE_FIXED","PULLBACK_LIMIT_FIXED"):
                reasons.append("DIFFERENT_ENTRY_POPULATION")
            if row["variant"]=="NEXT_OPEN_ATR" and row["mean_stop_bps"]>90:
                reasons.append("WIDE_STOP_NEEDS_POSITION_SIZING")
            reasons.append("NO_INDEPENDENT_FORWARD_VALIDATION")
            reviews.append({
                "symbol":symbol,"strategy":strategy,
                "hypothesis":row["variant"],"baseline_variant":"NEXT_OPEN_FIXED",
                "research_agent":{"role":"DETERMINISTIC_HYPOTHESIS","question":
                    "Does this entry/stop variant outperform a fixed next-open baseline?"},
                "quant_agent":{"role":"DETERMINISTIC_MEASUREMENT",
                    "training":train,"holdout":test,"baseline_holdout":baseline["holdout"]},
                "validation_agent":{"verdict":"NOT_VALIDATED","reasons":reasons},
                "adversary_agent":{"warnings":[
                    "Recorded signal selection is not regenerated out of sample",
                    "Holdout sample and variants may be correlated",
                    "Public OHLC cannot confirm executable limit fills"]},
                "chief_agent":{"verdict":"RESEARCH_ONLY","can_promote":False},
                "eligible_for_paper":False})
    return {"mode":"RESEARCH_ONLY","execution_authority":"NONE",
            "agent_mode":"DETERMINISTIC_RESEARCH_COORDINATOR_NO_LLM",
            "experiments":len(study["results"]),"hypothesis_reviews":reviews,
            "skipped":study["skipped"],
            "summary":{"reviewed":len(reviews),"promoted":0,
                       "note":"No model orders, no automatic strategy changes, no paper activation."}}
