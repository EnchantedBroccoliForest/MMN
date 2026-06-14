"""Verify the simulation's economic identities."""

import math

import pytest

from mmn.curves import PowerCurve
from mmn.simulator import SimConfig, simulate


def make(num_outcomes=4, early_pct=1.0, n=1.0, buy_fee=0.0, sell_fee=0.0,
         total_supply=1e9, mcap_at_full=100_000.0,
         multiples=(1, 2, 10, 100)):
    curve = PowerCurve.from_full_mcap(total_supply, mcap_at_full, exponent=n)
    return SimConfig(
        num_outcomes=num_outcomes, early_pct=early_pct, curve=curve,
        total_supply=total_supply, buy_fee=buy_fee, sell_fee=sell_fee,
        multiples=multiples,
    )


def test_total_spend_scales_with_outcomes():
    r1 = simulate(make(num_outcomes=1))
    r4 = simulate(make(num_outcomes=4))
    assert r4.total_spend == pytest.approx(4 * r1.spend_per_outcome)
    assert r1.total_spend == pytest.approx(r1.spend_per_outcome)


def test_tokens_bought_is_pct_of_supply():
    r = simulate(make(early_pct=2.5, total_supply=1e9))
    assert r.tokens_per_outcome == pytest.approx(0.025 * 1e9)


def test_entry_stage_is_break_even_without_fees():
    """At 1x growth the user is the only holder: redeem == spend, ownership 100%."""
    r = simulate(make(multiples=(1,)))
    s = r.stages[0]
    assert s.ownership_pct == pytest.approx(100.0)
    assert s.redeem_value == pytest.approx(r.spend_per_outcome)
    assert s.spot_value == pytest.approx(r.entry_market_cap)
    assert s.redeem_roi == pytest.approx(0.0, abs=1e-12)


@pytest.mark.parametrize("n", [0.0, 1.0, 2.0])
@pytest.mark.parametrize("m", [2.0, 10.0, 100.0])
def test_ownership_follows_power_law(n, m):
    """For a power curve, ownership at growth m is m^(-1/(n+1))."""
    r = simulate(make(n=n, multiples=(m,)))
    expected = m ** (-1.0 / (n + 1)) * 100.0
    assert r.stages[0].ownership_pct == pytest.approx(expected)


def test_spot_value_grows_as_power_of_multiple():
    """spot value per outcome == entry_mcap * m^(n/(n+1)) for a power curve."""
    n = 1.0
    r = simulate(make(n=n, multiples=(50.0,)))
    s = r.stages[0]
    expected = r.entry_market_cap * 50.0 ** (n / (n + 1))
    assert s.spot_value == pytest.approx(expected)


def test_settlement_pot_and_payout():
    r = simulate(make(num_outcomes=3, multiples=(10.0,)))
    s = r.stages[0]
    # pot = sum of reserves across outcomes; payout = ownership share of pot
    assert s.total_pot > 0
    assert s.settle_payout == pytest.approx(s.ownership_pct / 100.0 * s.total_pot)


def test_buy_fee_increases_spend():
    base = simulate(make(buy_fee=0.0))
    fee = simulate(make(buy_fee=0.01))
    assert fee.spend_per_outcome == pytest.approx(base.spend_per_outcome * 1.01)


def test_sell_fee_reduces_redeem():
    r = simulate(make(sell_fee=0.01, multiples=(10.0,)))
    r0 = simulate(make(sell_fee=0.0, multiples=(10.0,)))
    assert r.stages[0].redeem_value == pytest.approx(r0.stages[0].redeem_value * 0.99)


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
