"""Walk-forward research ranking. Never authorizes orders or self-modifies rules."""
from collections import defaultdict
import math

def evaluate(samples,min_train=30,min_test=15):
    grouped=defaultdict(list)
    for row in samples:
        try:
            if "15m" not in row.get("returns",{}):continue
            value=float(row["returns"]["15m"])
            if not math.isfinite(value):continue
            grouped[(row["symbol"],row["strategy"])].append((int(row["at_ms"]),value))
        except (KeyError,ValueError,TypeError):continue
    rankings=[]
    for (symbol,strategy),pairs in grouped.items():
        pairs.sort()
        # Remove overlapping windows per strategy and symbol.
        accepted=[];next_at=-1
        for at,result in pairs:
            if at>=next_at:
                accepted.append(result);next_at=at+900000
        split=int(len(accepted)*.7)
        train,test=accepted[:split],accepted[split:]
        if len(train)<min_train or len(test)<min_test:continue
        training_avg=sum(train)/len(train)
        testing_avg=sum(test)/len(test)
        testing_positive=sum(v>0 for v in test)/len(test)
        # Strict: no promotion without out-of-sample positive observations.
        passed=training_avg>0 and testing_avg>0 and testing_positive>.5
        rankings.append({"symbol":symbol,"strategy":strategy,
            "train_samples":len(train),"test_samples":len(test),
            "train_net_bps":round(training_avg,3),"test_net_bps":round(testing_avg,3),
            "test_positive_pct":round(testing_positive*100,2),"research_candidate":passed})
    rankings.sort(key=lambda x:x["test_net_bps"],reverse=True)
    return {"mode":"RESEARCH_ONLY","selection_authority":"NONE",
            "qualified":[r for r in rankings if r["research_candidate"]],
            "rankings":rankings,
            "notes":"Chronological 70/30 split of nonoverlapping 15m forward observations. Not tick replay; no parameter tuning, no execution authority or statistical proof. No observations reused to validate modified rules."}
