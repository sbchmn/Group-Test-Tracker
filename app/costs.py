"""Assigned charges, frozen pricing and explicit repricing of the funding cohort.

These helpers participate in the caller's transaction; they never commit or send
notifications. Payment verification and payment evidence are independent of pricing.
"""
import hashlib
import json
import math
from datetime import datetime
from decimal import Decimal, InvalidOperation

from . import db


class CostPolicyError(ValueError):
    pass


def money(value):
    try:
        amount = Decimal(str(value))
        if not amount.is_finite() or amount < 0 or amount > Decimal('9999999999.99') or amount != amount.quantize(Decimal('.01')):
            raise ValueError()
        return amount.quantize(Decimal('.01'))
    except (InvalidOperation, ValueError, TypeError):
        raise CostPolicyError('Enter a buy-in amount from $0 to $9,999,999,999.99, with at most two decimal places.')


def _funding(test):
    return test.participations.filter_by(approved=True, is_late_buy_in=False).all()


def _inputs(test):
    result = {key: getattr(test, key) for key in (
        'total_lab_cost', 'shipping_cost', 'donor_shipping_cost',
        'donor_shipping_reimbursement', 'donor_shipping_reimbursed_by_id', 'refund_per_donor',
    )}
    result['lab_test_details'] = [
        {key: item.get(key) for key in ('name', 'price', 'vials_needed')}
        for item in (test.lab_test_details or [])
    ]
    return result


def _live_costs(test):
    costs = test.calculate_live_costs()
    if any(isinstance(value, float) and not math.isfinite(value) for value in costs.values()):
        raise CostPolicyError('Cost inputs must be finite numbers before charges can be updated.')
    return costs


def legacy_snapshot(test):
    """Read-only projection until the first mutation persists a legacy baseline.

Never reconstruct historical prices by dividing today's costs by today's roster.
Only an unambiguous assigned rate is suitable as a default for later buyers.
"""
    parts = _funding(test)
    result = test.calculate_live_costs()
    for donor, key in [(False, 'non_donor_pays'), (True, 'donor_pays')]:
        amounts = {round(p.amount_owed, 2) for p in parts if bool(p.vial_donor) == donor and p.amount_owed is not None}
        cohort = [p for p in parts if bool(p.vial_donor) == donor]
        result[key] = next(iter(amounts)) if len(amounts) == 1 and all(p.amount_owed is not None for p in cohort) else None
    result.update(legacy=True, base_per_person=None, participant_ids=[p.id for p in parts],
                  inputs=_inputs(test), message='Existing assigned charges have been preserved.')
    return result


def ensure_snapshot(test):
    if test.costs_locked and not test.cost_snapshot:
        test.cost_snapshot = legacy_snapshot(test)
        test.costs_frozen = True
        if test.late_buy_in_amount is None and test.late_buy_in_price is not None:
            test.late_buy_in_amount = money(test.late_buy_in_price)


def recalculate(test):
    """Automatic repricing is limited to unlocked recruiting tests."""
    if test.costs_locked:
        test.cost_revision = (test.cost_revision or 1) + 1
        return
    costs = _live_costs(test)
    for part in _funding(test):
        part.update_amount_owed(costs)
    test.cost_revision = (test.cost_revision or 1) + 1


def freeze(test, actor_id=None):
    """Finalize once before any notifications observe the new test status."""
    costs = _live_costs(test)
    parts = _funding(test)
    for part in parts:
        part.update_amount_owed(costs)
    test.cost_snapshot = {**costs, 'inputs': _inputs(test), 'participant_ids': [p.id for p in parts], 'legacy': False}
    test.costs_frozen = True
    test.costs_frozen_at = datetime.utcnow()
    test.costs_frozen_by_id = actor_id
    if costs['total_non_donors']:
        test.late_buy_in_amount = money(costs['non_donor_pays'])
    test.cost_revision = (test.cost_revision or 1) + 1


def price_approval(part, override=None):
    """Called before approval, with the original roster still intact."""
    test = part.group_test
    ensure_snapshot(test)
    if not test.costs_locked:
        return
    if not part.is_late_buy_in and part.id in (test.cost_snapshot or {}).get('participant_ids', []):
        test.cost_revision = (test.cost_revision or 1) + 1
        return  # Reapproving an original funder keeps their agreed charge.
    price = money(override) if override not in (None, '') else test.late_buy_in_price
    if price is None:
        raise CostPolicyError(f'Set a late buy-in price for "{test.title}" before approving additional participants.')
    price = money(price)
    if test.late_buy_in_price is None:
        test.late_buy_in_amount = price
    part.is_late_buy_in = True
    part.amount_owed = float(price)
    test.cost_revision = (test.cost_revision or 1) + 1


def preview(test):
    costs = _live_costs(test)
    changes = []
    for part in test.participations.filter_by(approved=True).all():
        amount = part.amount_owed if part.is_late_buy_in else costs['donor_pays' if part.vial_donor else 'non_donor_pays']
        changes.append({'id': part.id, 'name': part.name or part.user.username,
                        'old': part.amount_owed or 0, 'new': amount or 0, 'late': part.is_late_buy_in})
    # Bind confirmation to both prices and inputs, including concurrent payments
    # and role/approval changes. A saved preview must never approve a different plan.
    state = {'test_revision': test.cost_revision, 'status': test.status, 'frozen': test.costs_locked,
             'inputs': _inputs(test), 'snapshot': test.cost_snapshot, 'buy_in': str(test.late_buy_in_price),
             'rows': [(p.id, p.approved, p.vial_donor, p.is_late_buy_in, p.amount_owed, p.payment_revision)
                      for p in test.participations.order_by(None).order_by('id').all()]}
    token = hashlib.sha256(json.dumps(state, sort_keys=True, default=str).encode()).hexdigest()
    return changes, token


def confirm_recalculation(test, token, actor_id=None):
    _, current = preview(test)
    if not token or token != current:
        raise CostPolicyError('The roster, payments or cost inputs changed. Review the updated preview before confirming.')
    if test.status == 'recruiting':
        test.costs_frozen = False
        test.cost_snapshot = None
        test.costs_frozen_at = None
        test.costs_frozen_by_id = None
        recalculate(test)
    else:
        freeze(test, actor_id)  # Deliberate one-off repricing stays frozen outside recruiting.
