"""Explicit single-batch KC procurement planning and scenario cost attribution.

No contract is inferred from a continuous ticker. Exit deadline and margin
must be supplied from the user's broker/calendar. Costs exclude taxes/freight.
"""
from dataclasses import dataclass, asdict
from datetime import date
import math
import re

from arbor.domain.procurement import KC_CONTRACT_TONNES, LB_PER_TONNE, plan_procurement


def positive(name, value, allow_zero=False):
    if not math.isfinite(value) or value < 0 or (value == 0 and not allow_zero):
        raise ValueError(f"invalid {name}")


@dataclass(frozen=True)
class PurchaseBatch:
    batch_id: str
    purchase_tonnes: float
    priced_tonnes: float
    pricing_date: date
    contract_month: str
    exit_deadline: date
    policy_reference: str
    target_ratio: float
    kc_price_cents_lb: float
    basis_cents_lb: float
    basis_fixed: bool
    usd_cny: float
    priced_unit_cents_lb: float | None = None
    price_basis: str = 'KC'
    coffee_type: str = 'arabica'

    @property
    def contract_id(self):
        return f"KC-{self.contract_month}"

    def validate(self, as_of):
        if not isinstance(as_of, date):
            raise ValueError("as_of must be a date")
        if not self.batch_id.strip() or not self.policy_reference.strip():
            raise ValueError("batch_id and policy_reference are required")
        if self.price_basis != 'KC' or self.coffee_type != 'arabica':
            raise ValueError("only explicitly KC-priced arabica batches are supported")
        if not re.fullmatch(r'\d{4}-(03|05|07|09|12)', self.contract_month):
            raise ValueError("contract_month must be a listed KC month YYYY-MM")
        delivery_start = date.fromisoformat(self.contract_month+'-01')
        if (not self.pricing_date <= self.exit_deadline < delivery_start
                or as_of >= self.exit_deadline
                or (self.priced_tonnes < self.purchase_tonnes and as_of > self.pricing_date)):
            raise ValueError("require as_of <= pricing_date <= exit_deadline < delivery month, and as_of before exit_deadline")
        positive('purchase_tonnes', self.purchase_tonnes, True)
        positive('priced_tonnes', self.priced_tonnes, True)
        if self.priced_tonnes > self.purchase_tonnes:
            raise ValueError("priced_tonnes exceeds purchase_tonnes")
        if not isinstance(self.basis_fixed, bool):
            raise ValueError("basis_fixed must be a boolean")
        positive('kc_price_cents_lb', self.kc_price_cents_lb)
        positive('usd_cny', self.usd_cny)
        if not math.isfinite(self.basis_cents_lb):
            raise ValueError("basis must be finite")
        positive('physical price', self.kc_price_cents_lb+self.basis_cents_lb)
        if self.priced_tonnes:
            if self.priced_unit_cents_lb is None:
                raise ValueError("priced_unit_cents_lb required for fixed-price quantity")
            positive('priced_unit_cents_lb', self.priced_unit_cents_lb)
        if not math.isfinite(self.target_ratio) or not 0 <= self.target_ratio <= 1:
            raise ValueError("target_ratio must be between 0 and 1")


def batch_plan(batch, *, as_of, equity, margin_per_contract, commission_per_contract=15):
    batch.validate(as_of)
    return plan_procurement(purchase_tonnes=batch.purchase_tonnes, priced_tonnes=batch.priced_tonnes,
        target_ratio=batch.target_ratio, contract_tonnes=KC_CONTRACT_TONNES, equity=equity,
        margin_per_contract=margin_per_contract, commission_per_contract=commission_per_contract)


def stress_batch(batch, *, as_of, hedge_tonnes, kc_change_cents_lb=0.,
                 basis_change_cents_lb=0., fx_change_pct=0.):
    """Terminal USD cash flows translated at one FX rate; no FX hedge assumed.

    All purchase amounts are assumed unpaid. Fixed-price tonnes retain their
    locked price; futures hedge only the floating KC component.
    """
    batch.validate(as_of)
    remaining = batch.purchase_tonnes-batch.priced_tonnes
    if not math.isfinite(hedge_tonnes) or hedge_tonnes < 0 or (hedge_tonnes > remaining and not math.isclose(hedge_tonnes, remaining, rel_tol=0., abs_tol=1e-10)):
        raise ValueError("hedge_tonnes must not exceed remaining exposure")
    if not all(math.isfinite(v) for v in (kc_change_cents_lb, basis_change_cents_lb, fx_change_pct)):
        raise ValueError("stress inputs must be finite")
    fx = batch.usd_cny*(1+fx_change_pct)
    positive('stressed fx', fx)
    basis_change = 0. if batch.basis_fixed else basis_change_cents_lb
    physical_price = batch.kc_price_cents_lb+batch.basis_cents_lb+kc_change_cents_lb+basis_change
    positive('stressed physical price', physical_price)
    positive('stressed futures price', batch.kc_price_cents_lb+kc_change_cents_lb)
    factor = LB_PER_TONNE/100
    fixed = batch.priced_tonnes*(batch.priced_unit_cents_lb or 0)*factor
    base = fixed+remaining*(batch.kc_price_cents_lb+batch.basis_cents_lb)*factor
    physical = fixed+remaining*physical_price*factor
    pnl = hedge_tonnes*kc_change_cents_lb*factor
    kc_residual = (remaining-hedge_tonnes)*kc_change_cents_lb*factor
    basis_cost = remaining*basis_change*factor
    net = physical-pnl
    return {'physical_cost_usd': physical, 'futures_pnl_usd': pnl, 'net_cost_usd': net,
            'net_cost_cny': net*fx, 'base_cost_cny': base*batch.usd_cny,
            'kc_residual_change_cny': kc_residual*batch.usd_cny,
            'basis_change_cny': basis_cost*batch.usd_cny,
            'fx_change_cny': net*(fx-batch.usd_cny),
            'total_change_cny': net*fx-base*batch.usd_cny,
            'assumption': 'Unpaid purchases; spot and futures terminal USD cash flows translated at the same FX; fees, freight and taxes excluded.'}


def batch_from_dict(data):
    values = dict(data)
    for key in ('pricing_date', 'exit_deadline'):
        values[key] = date.fromisoformat(values[key])
    return PurchaseBatch(**values)


def preview_batch(batch, *, as_of, equity, margin_per_contract, shocks=()):
    plan = batch_plan(batch, as_of=as_of, equity=equity, margin_per_contract=margin_per_contract)
    return {'batch_id': batch.batch_id, 'contract_id': batch.contract_id,
            'as_of': as_of.isoformat(), 'pricing_date': batch.pricing_date.isoformat(),
            'exit_deadline': batch.exit_deadline.isoformat(), 'policy_reference': batch.policy_reference,
            'plan': asdict(plan), 'mode': 'PREVIEW_NO_ORDER',
            'uncovered_risks': ([] if batch.basis_fixed else ['basis']) + ['USD/CNY', 'freight', 'taxes'],
            'stress': [{'inputs': shock, **stress_batch(batch, as_of=as_of, hedge_tonnes=plan.actual_tonnes, **shock)} for shock in shocks]}
