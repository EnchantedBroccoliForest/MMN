"""Verify the closed-form bonding-curve math against numerical integration."""

import math

import pytest

from mmn.curves import AffineCurve, PowerCurve


def numeric_reserve(curve, s, steps=200_000):
    """Trapezoidal integral of price from 0..s as an independent cross-check."""
    if s == 0:
        return 0.0
    h = s / steps
    total = 0.5 * (curve.price(0.0) + curve.price(s))
    for i in range(1, steps):
        total += curve.price(i * h)
    return total * h


@pytest.mark.parametrize("n", [0.0, 0.5, 1.0, 2.0, 3.0])
def test_power_reserve_matches_integral(n):
    curve = PowerCurve(coefficient=3.3e-12, exponent=n)
    s = 1_000_000.0
    assert curve.reserve(s) == pytest.approx(numeric_reserve(curve, s), rel=1e-4)


@pytest.mark.parametrize("n", [0.0, 1.0, 2.0])
def test_power_market_cap_identity(n):
    """market_cap == (n+1) * reserve for a power curve."""
    curve = PowerCurve(coefficient=1e-9, exponent=n)
    s = 12_345.0
    assert curve.market_cap(s) == pytest.approx((n + 1) * curve.reserve(s))


@pytest.mark.parametrize("n", [0.5, 1.0, 2.0])
def test_power_inverses(n):
    curve = PowerCurve(coefficient=7e-10, exponent=n)
    s = 5_000_000.0
    assert curve.supply_for_market_cap(curve.market_cap(s)) == pytest.approx(s)
    assert curve.supply_for_reserve(curve.reserve(s)) == pytest.approx(s)


@pytest.mark.parametrize("n", [0.0, 1.0, 2.0])
def test_power_tokens_for_spend_roundtrip(n):
    curve = PowerCurve(coefficient=4e-11, exponent=n)
    s0 = 100_000.0
    spend = curve.cost(s0, 250_000.0)
    got = curve.tokens_for_spend(s0, spend)
    assert s0 + got == pytest.approx(250_000.0)


def test_from_full_mcap():
    curve = PowerCurve.from_full_mcap(total_supply=1e9, mcap_at_full=100_000.0, exponent=1.0)
    assert curve.market_cap(1e9) == pytest.approx(100_000.0)


@pytest.mark.parametrize("m,b", [(2e-13, 0.0), (1e-13, 5e-6), (0.0, 1e-5)])
def test_affine_reserve_matches_integral(m, b):
    curve = AffineCurve(slope=m, base=b)
    s = 2_000_000.0
    assert curve.reserve(s) == pytest.approx(numeric_reserve(curve, s), rel=1e-4)


@pytest.mark.parametrize("m,b", [(2e-13, 0.0), (1e-13, 5e-6), (0.0, 1e-5)])
def test_affine_inverses(m, b):
    curve = AffineCurve(slope=m, base=b)
    s = 3_000_000.0
    assert curve.supply_for_market_cap(curve.market_cap(s)) == pytest.approx(s)
    assert curve.supply_for_reserve(curve.reserve(s)) == pytest.approx(s)


def test_cost_requires_ordered_bounds():
    curve = PowerCurve(1e-9, 1.0)
    with pytest.raises(ValueError):
        curve.cost(10.0, 5.0)


def test_invalid_params():
    with pytest.raises(ValueError):
        PowerCurve(coefficient=0.0)
    with pytest.raises(ValueError):
        PowerCurve(coefficient=1.0, exponent=-1.0)
    with pytest.raises(ValueError):
        AffineCurve(slope=0.0, base=0.0)
