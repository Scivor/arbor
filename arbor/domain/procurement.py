"""Pure procurement exposure and cash-budget sizing. Prices are cents/lb."""
from dataclasses import dataclass
import math

LB_PER_TONNE = 1000 / 0.45359237
KC_CONTRACT_TONNES = 37500 / LB_PER_TONNE


def nonnegative(name, value):
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"{name} must be finite and nonnegative")


def futures_pnl(entry_price, exit_price, size_tonnes):
    return (exit_price - entry_price) * size_tonnes * LB_PER_TONNE / 100


@dataclass(frozen=True)
class ProcurementPlan:
    unpriced_tonnes: float
    target_contracts: int
    actual_tonnes: float
    residual_tonnes: float
    actual_ratio: float
    margin_required: float | None
    cash_limited: bool
    executable: bool


def plan_procurement(*, purchase_tonnes, priced_tonnes, target_ratio,
                     contract_tonnes=KC_CONTRACT_TONNES, equity=0.0,
                     margin_per_contract=None, commission_per_contract=0.0):
    """Target TOTAL futures, not an additive order. Reserve round-trip fees.

    Missing margin gives theoretical sizing only, never an executable plan.
    Caller must compare this target with existing positions of the same batch.
    Margin is user-supplied, not an assumed current exchange requirement.
    """
    for name, value in [("purchase_tonnes", purchase_tonnes), ("priced_tonnes", priced_tonnes),
                        ("target_ratio", target_ratio), ("commission", commission_per_contract)]:
        nonnegative(name, value)
    if priced_tonnes > purchase_tonnes or target_ratio > 1:
        raise ValueError("priced quantity exceeds purchase or ratio exceeds 1")
    if not math.isfinite(equity) or not math.isfinite(contract_tonnes) or contract_tonnes <= 0:
        raise ValueError("invalid equity or contract size")
    remaining = purchase_tonnes - priced_tonnes
    desired = math.floor(remaining * target_ratio / contract_tonnes)
    contracts = desired
    if margin_per_contract is not None:
        if not math.isfinite(margin_per_contract) or margin_per_contract <= 0:
            raise ValueError("margin_per_contract must be positive and finite")
        affordable = math.floor(max(0, equity) / (margin_per_contract + 2 * commission_per_contract))
        contracts = min(desired, affordable)
    actual = contracts * contract_tonnes
    return ProcurementPlan(remaining, contracts, actual, remaining - actual,
                           actual / remaining if remaining else 0.0,
                           contracts * margin_per_contract if margin_per_contract is not None else None,
                           contracts < desired, margin_per_contract is not None)
