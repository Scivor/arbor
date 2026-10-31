from dataclasses import replace
from datetime import date
import json
import subprocess
import sys

import pytest

from arbor.domain.purchase_batch import PurchaseBatch, batch_plan, stress_batch, preview_batch
from arbor.domain.procurement import KC_CONTRACT_TONNES as KC
from arbor.application.paper_trading.engine import PaperTradingEngine

AS_OF = date(2026, 10, 30)


def batch(**overrides):
    b = PurchaseBatch('lot-1', KC*3, KC, date(2026,11,20), '2026-12', date(2026,11,25),
                      'demo-policy', .5, 200., 10., False, 7., 205.)
    return replace(b, **overrides)


def test_batch_target_excludes_fixed_price_volume():
    p = batch_plan(batch(), as_of=AS_OF, equity=100000, margin_per_contract=1000)
    assert p.target_contracts == 1
    assert p.unpriced_tonnes == pytest.approx(KC*2)
    assert p.actual_ratio == pytest.approx(.5)


@pytest.mark.parametrize('overrides', [
    {'contract_month': '2026-11'}, {'exit_deadline': date(2026,12,1)},
    {'pricing_date': date(2026,11,26)}, {'pricing_date': date(2026,10,29)},
    {'price_basis': 'fixed'}, {'coffee_type': 'robusta'}, {'policy_reference': ''},
    {'priced_unit_cents_lb': None}, {'usd_cny': 0}, {'basis_fixed': 'false'},
])
def test_invalid_batch_is_blocked(overrides):
    with pytest.raises(ValueError):
        batch_plan(batch(**overrides), as_of=AS_OF, equity=100000, margin_per_contract=1000)


def test_cost_attribution_adds_up_and_fixed_volume_keeps_its_price():
    b = batch()
    out = stress_batch(b, as_of=AS_OF, hedge_tonnes=KC, kc_change_cents_lb=10,
                      basis_change_cents_lb=5, fx_change_pct=.1)
    assert out['futures_pnl_usd'] == pytest.approx(3750)
    assert out['kc_residual_change_cny'] == pytest.approx(3750*7)
    assert out['basis_change_cny'] == pytest.approx(3750*7)
    assert out['total_change_cny'] == pytest.approx(sum(out[k] for k in
        ['kc_residual_change_cny', 'basis_change_cny', 'fx_change_cny']))
    fixed_basis = stress_batch(replace(b, basis_fixed=True), as_of=AS_OF,
                              hedge_tonnes=KC, basis_change_cents_lb=100)
    assert fixed_basis['basis_change_cny'] == 0
    assert fixed_basis['total_change_cny'] == 0


def test_fully_fixed_unpaid_purchase_still_has_fx_risk():
    b = batch(priced_tonnes=KC*3)
    out = stress_batch(b, as_of=AS_OF, hedge_tonnes=0, kc_change_cents_lb=10, fx_change_pct=.1)
    assert out['kc_residual_change_cny'] == 0
    assert out['fx_change_cny'] > 0


def test_paper_rejects_wrong_contract_and_unassigned_position(tmp_path):
    engine = PaperTradingEngine(db_path=tmp_path/'paper.db', margin_per_contract=1000)
    with pytest.raises(ValueError, match='quote contract'):
        engine.sync_batch(batch(), as_of=AS_OF, quote_contract_id='KC=F', current_price=200)
    assert engine._position is None
    engine.sync_batch(batch(), as_of=AS_OF, quote_contract_id='KC-2026-12', current_price=200)
    assert engine._position.contracts == 1
    assert engine.get_summary()['open_position']['batch_id'] == 'lot-1'
    with pytest.raises(ValueError, match='another batch'):
        engine.sync_batch(batch(batch_id='lot-2'), as_of=AS_OF, quote_contract_id='KC-2026-12', current_price=200)
    with pytest.raises(ValueError, match='sync_batch'):
        engine.sync_to_ratio(.5, 200, 100)
    engine.sync_batch(batch(priced_tonnes=KC*3), as_of=AS_OF, quote_contract_id='KC-2026-12', current_price=200)
    assert engine._position is None
    engine.close()


def test_preview_missing_margin_is_not_executable():
    out = preview_batch(batch(), as_of=AS_OF, equity=100000, margin_per_contract=None)
    assert not out['plan']['executable']
    assert out['mode'] == 'PREVIEW_NO_ORDER'
    assert out['contract_id'] == 'KC-2026-12'


def test_cli_reads_batch_and_emits_only_preview(tmp_path):
    from dataclasses import asdict
    value = asdict(batch())
    for key in ['pricing_date', 'exit_deadline']:
        value[key] = value[key].isoformat()
    path = tmp_path/'batch.json'
    path.write_text(json.dumps({'batch': value, 'equity_usd': 100000,
                               'margin_per_contract_usd': 1000, 'shocks': [{'fx_change_pct': .1}]}))
    run = subprocess.run([sys.executable, '-m', 'cli.procurement_plan', str(path), '--as-of', AS_OF.isoformat()],
                         capture_output=True, text=True, check=True)
    out = json.loads(run.stdout)
    assert out['plan']['target_contracts'] == 1
    assert out['stress'][0]['fx_change_cny'] > 0
    assert out['mode'] == 'PREVIEW_NO_ORDER'


def test_fully_fixed_batch_can_be_closed_after_its_pricing_date():
    p = batch_plan(batch(priced_tonnes=KC*3, pricing_date=date(2026,10,29)),
                   as_of=AS_OF, equity=100000, margin_per_contract=1000)
    assert p.target_contracts == 0

def test_true_fraction_below_contract_boundary_stays_flat():
    p = batch_plan(batch(purchase_tonnes=KC*.999999, priced_tonnes=0, target_ratio=1),
                   as_of=AS_OF, equity=100000, margin_per_contract=1000)
    assert p.target_contracts == 0
