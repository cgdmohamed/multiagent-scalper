"""Deterministic fail-closed portfolio protection; AI cannot override it."""
from dataclasses import dataclass
import math

@dataclass(frozen=True)
class GuardianPolicy:
    risk_per_trade_fraction: float = .001
    daily_loss_fraction: float = .005
    drawdown_fraction: float = .02
    max_positions: int = 1

def inspect(engine, policy=GuardianPolicy()):
    equity=float(engine.equity())
    peak=float(engine.peak_equity)
    day_start=float(engine.day_start_equity)
    reasons=[]
    if not all(math.isfinite(v) and v>0 for v in (equity,peak,day_start)):
        reasons.append("INVALID_EQUITY_STATE")
    else:
        if equity <= day_start*(1-policy.daily_loss_fraction):reasons.append("DAILY_CAPITAL_GUARD")
        if equity <= peak*(1-policy.drawdown_fraction):reasons.append("DRAWDOWN_CAPITAL_GUARD")
    if len(engine.positions)>=policy.max_positions:reasons.append("GUARDIAN_POSITION_LIMIT")
    return {"allowed":not reasons,"reasons":reasons,
            "equity":round(equity,6) if math.isfinite(equity) else None,
            "max_risk_per_trade_pct":policy.risk_per_trade_fraction*100,
            "daily_loss_limit_pct":policy.daily_loss_fraction*100,
            "drawdown_limit_pct":policy.drawdown_fraction*100,
            "maximum_positions":policy.max_positions}

def configure_engine(engine,policy=GuardianPolicy()):
    """Apply stricter caps, never relax the engine's existing limits."""
    engine.cfg.risk_per_trade=min(engine.cfg.risk_per_trade,policy.risk_per_trade_fraction)
    engine.cfg.daily_loss_limit=min(engine.cfg.daily_loss_limit,policy.daily_loss_fraction)
    engine.cfg.drawdown_limit=min(engine.cfg.drawdown_limit,policy.drawdown_fraction)
    engine.cfg.max_positions=min(engine.cfg.max_positions,policy.max_positions)
    return policy
