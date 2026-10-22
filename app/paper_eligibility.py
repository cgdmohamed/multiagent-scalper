"""Preconditions for paper-trading activation. Explicitly deny any unbound strategy."""
def eligibility(*,feed_ok,bot_stopped,operator_paused,risk_halted,capital_allowed,
                recovery_ok,qualified_benchmark,qualified_optimizer,strategy_bound):
    reasons=[]
    if not feed_ok: reasons.append("MARKET_FEED_NOT_FRESH")
    if bot_stopped: reasons.append("BOT_STOPPED")
    if operator_paused: reasons.append("OPERATOR_PAUSED")
    if risk_halted: reasons.append("RISK_CIRCUIT_HALTED")
    if not capital_allowed: reasons.append("CAPITAL_GUARDIAN_BLOCK")
    if not recovery_ok: reasons.append("UNTRUSTED_PORTFOLIO_RECOVERY")
    if not qualified_benchmark: reasons.append("NO_BENCHMARK_QUALIFIED_STRATEGY")
    # Candidate output alone isn't validated executable logic.
    names={(x.get("symbol"),x.get("strategy")) for x in qualified_optimizer}
    if not qualified_benchmark or (qualified_benchmark.get("symbol"),qualified_benchmark.get("strategy")) not in names:
        reasons.append("NO_MATCHING_HOLDOUT_CANDIDATE")
    if not strategy_bound: reasons.append("NO_VALIDATED_STRATEGY_BOUND_TO_EXECUTION_ENGINE")
    return {"eligible":not reasons,"mode":"RESEARCH_ONLY_UNTIL_ELIGIBLE",
            "reasons":reasons,"paper_orders_only":True,
            "selected_candidate":qualified_benchmark if not reasons else None}
