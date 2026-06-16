"""Verify the simulation's economic identities on 42's exact curve."""

import pytest

from mmn.curves import PowerCurve
from mmn.simulator import SimConfig, simulate


def make(
    num_outcomes=4,
    early_pct=1.0,
    buy_fee=0.0,
    sell_fee=0.0,
    redeem_tax=0.0,
    total_supply=1_000_000.0,
    house_seed_mcap=0.0,
    multiples=(1, 2, 10, 100),
    curve=None,
):
    return SimConfig(
        num_outcomes=num_outcomes,
        early_pct=early_pct,
        curve=curve or PowerCurve.ft(),
        total_supply=total_supply,
        buy_fee=buy_fee,
        sell_fee=sell_fee,
        redeem_tax=redeem_tax,
        house_seed_mcap=house_seed_mcap,
        multiples=multiples,
    )


def test_total_spend_scales_with_outcomes():
    r1 = simulate(make(num_outcomes=1))
    r4 = simulate(make(num_outcomes=4))
    assert r4.total_spend == pytest.approx(4 * r1.spend_per_outcome)


def test_tokens_bought_is_pct_of_supply():
    r = simulate(make(early_pct=2.5, total_supply=1e6))
    assert r.tokens_per_outcome == pytest.approx(0.025 * 1e6)


def test_entry_reserve_equals_spend_no_fee_no_seed():
    """Reserve == cumulative staked, so entry reserve == fee-free spend; and the
    spot market cap = (n+1) * reserve."""
    r = simulate(make(multiples=(1,)))
    assert r.entry_reserve == pytest.approx(r.spend_per_outcome)  # buy_fee=0
    assert r.entry_market_cap == pytest.approx((1 + 0.75) * r.entry_reserve)  # price*supply
    s = r.stages[0]
    assert s.ownership_pct == pytest.approx(100.0)
    assert s.reserve == pytest.approx(r.spend_per_outcome)
    assert s.redeem_value == pytest.approx(r.spend_per_outcome)
    assert s.redeem_roi == pytest.approx(0.0, abs=1e-12)


@pytest.mark.parametrize("m", [2.0, 10.0, 100.0, 1000.0])
def test_ownership_is_M_pow_minus_4_over_7(m):
    """On the 42 curve (n=3/4): ownership at mcap multiple M is M^(-4/7)."""
    r = simulate(make(multiples=(m,)))
    assert r.stages[0].ownership_pct == pytest.approx(m ** (-4.0 / 7.0) * 100.0)


@pytest.mark.parametrize("m", [2.0, 10.0, 100.0, 1000.0])
def test_settlement_win_value_is_M_pow_3_over_7(m):
    """Win payout / spend at mcap multiple M is M^(3/7) on the 42 curve."""
    r = simulate(make(multiples=(m,)))
    assert r.stages[0].settle_roi + 1.0 == pytest.approx(m ** (3.0 / 7.0))


@pytest.mark.parametrize("m", [2.0, 10.0, 100.0])
def test_redeem_ratio_closed_form(m):
    """redeem/spend = M - (M^(4/7) - 1)^(7/4) on the 42 curve (fee-free)."""
    r = simulate(make(multiples=(m,)))
    expected = m - (m ** (4.0 / 7.0) - 1.0) ** (7.0 / 4.0)
    got = r.stages[0].redeem_value / r.spend_per_outcome
    assert got == pytest.approx(expected)


def test_settlement_pot_and_payout():
    r = simulate(make(num_outcomes=3, multiples=(10.0,)))
    s = r.stages[0]
    assert s.total_pot > 0
    assert s.settle_payout == pytest.approx(s.ownership_pct / 100.0 * s.total_pot)


def test_house_seed_dilutes_entry_ownership():
    """With a house seed the early buyer no longer owns 100% at entry."""
    r = simulate(make(house_seed_mcap=5.0, multiples=(1,)))
    assert r.seed_supply > 0
    assert r.stages[0].ownership_pct < 100.0


def test_roi_is_scale_free():
    """Doubling the reference supply leaves every ROI unchanged."""
    r1 = simulate(make(total_supply=1e6, multiples=(100.0,)))
    r2 = simulate(make(total_supply=4e6, multiples=(100.0,)))
    assert r1.stages[0].redeem_roi == pytest.approx(r2.stages[0].redeem_roi)
    assert r1.stages[0].settle_roi == pytest.approx(r2.stages[0].settle_roi)
    assert r1.stages[0].ownership_pct == pytest.approx(r2.stages[0].ownership_pct)


def test_buy_fee_increases_spend():
    base = simulate(make(buy_fee=0.0))
    fee = simulate(make(buy_fee=0.002))
    assert fee.spend_per_outcome == pytest.approx(base.spend_per_outcome * 1.002)


def test_sell_fee_reduces_redeem():
    r = simulate(make(sell_fee=0.002, multiples=(10.0,)))
    r0 = simulate(make(sell_fee=0.0, multiples=(10.0,)))
    assert r.stages[0].redeem_value == pytest.approx(r0.stages[0].redeem_value * 0.998)


def test_rejects_multiple_below_one():
    with pytest.raises(ValueError):
        simulate(make(multiples=(0.5,)))


def test_validation():
    with pytest.raises(ValueError):
        make(num_outcomes=0)
    with pytest.raises(ValueError):
        make(early_pct=0)
    with pytest.raises(ValueError):
        make(early_pct=150)
