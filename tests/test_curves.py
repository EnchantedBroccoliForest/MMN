"""Verify the curve math: closed forms vs numerical integration, and an exact
match against 42's production formulas (from MC_Sim/parimutuel_sim/market.py)."""

import pytest

from mmn.curves import FT_ALPHA, FT_PRICE_SCALE, PowerCurve


def numeric_reserve(curve, s, steps=200_000):
    """Trapezoidal integral of price from 0..s as an independent cross-check."""
    if s == 0:
        return 0.0
    h = s / steps
    total = 0.5 * (curve.price(0.0) + curve.price(s))
    for i in range(1, steps):
        total += curve.price(i * h)
    return total * h


# ----------------------------- power curve --------------------------------
@pytest.mark.parametrize("n", [0.0, 0.5, 0.75, 1.0, 2.0, 3.0])
def test_power_reserve_matches_integral(n):
    curve = PowerCurve(coefficient=3.3e-7, exponent=n)
    s = 1_000_000.0
    assert curve.reserve(s) == pytest.approx(numeric_reserve(curve, s), rel=1e-4)


@pytest.mark.parametrize("n", [0.0, 0.75, 1.0, 2.0])
def test_power_spot_market_cap_identity(n):
    curve = PowerCurve(coefficient=1e-9, exponent=n)
    s = 12_345.0
    assert curve.spot_market_cap(s) == pytest.approx((n + 1) * curve.reserve(s))


@pytest.mark.parametrize("n", [0.5, 0.75, 1.0, 2.0])
def test_power_inverses(n):
    curve = PowerCurve(coefficient=7e-10, exponent=n)
    s = 5_000_000.0
    assert curve.supply_for_spot_market_cap(curve.spot_market_cap(s)) == pytest.approx(s)
    assert curve.supply_for_reserve(curve.reserve(s)) == pytest.approx(s)


@pytest.mark.parametrize("n", [0.0, 0.75, 1.0, 2.0])
def test_power_tokens_for_spend_roundtrip(n):
    curve = PowerCurve(coefficient=4e-8, exponent=n)
    s0 = 100_000.0
    spend = curve.cost(s0, 250_000.0)
    got = curve.tokens_for_spend(s0, spend)
    assert s0 + got == pytest.approx(250_000.0)


# --------------------- EXACT match to 42's MC_Sim -------------------------
# Re-implement MC_Sim/market.py formulas independently and require equality.
# Ground truth = the on-chain contract (ft-contracts PowerCurveSet1 / PowerMath):
#   cost / mcap = x^(c1+1)/c2 ; price = (c1+1)*x^c1/c2 ; with c1=0.75, c2=2e6.
# (ignoring the +start=8.888 offset, which MMN's ft() also omits.)
ALPHA, EXP_OUT, INV_EXP, SCALE = 0.75, 1.75, 4.0 / 7.0, 2_000_000.0


def _ct_price(x):
    return (1.0 + ALPHA) * x**ALPHA / SCALE


def _ct_mcap(x):
    return x**EXP_OUT / SCALE


def _ct_mint_units(x1, dollars):
    x2 = (x1**EXP_OUT + SCALE * dollars) ** INV_EXP
    return x2 - x1


def _ct_supply_for_mcap(m):
    return (SCALE * m) ** INV_EXP


@pytest.mark.parametrize("x", [1.0, 123.0, 10_000.0, 3_960_000.0])
def test_ft_curve_matches_contract(x):
    c = PowerCurve.ft()
    assert c.price(x) == pytest.approx(_ct_price(x))
    assert c.reserve(x) == pytest.approx(_ct_mcap(x))  # 42 mcap == reserve == cost
    assert c.cost(0.0, x) == pytest.approx(_ct_mcap(x))


@pytest.mark.parametrize("dollars", [1.0, 50.0, 12_345.0])
def test_ft_mint_and_supply_match_contract(dollars):
    c = PowerCurve.ft()
    x1 = 500_000.0
    assert c.tokens_for_spend(x1, dollars) == pytest.approx(_ct_mint_units(x1, dollars))
    assert c.supply_for_reserve(dollars) == pytest.approx(_ct_supply_for_mcap(dollars))


def test_ft_constants():
    c = PowerCurve.ft()
    assert c.k == pytest.approx((1.0 + FT_ALPHA) / FT_PRICE_SCALE)  # = 1.75/2e6
    assert c.n == FT_ALPHA


@pytest.mark.parametrize("n", [0.5, 0.75, 1.0, 2.0])
def test_power_inverse_nonpositive_returns_float_zero(n):
    """Negative/zero reserve must return a real 0.0, not a complex number."""
    curve = PowerCurve(coefficient=7e-10, exponent=n)
    for bad in (-100.0, -1.0, 0.0):
        r = curve.supply_for_reserve(bad)
        m = curve.supply_for_spot_market_cap(bad)
        assert isinstance(r, float) and r == 0.0
        assert isinstance(m, float) and m == 0.0


def test_cost_requires_ordered_bounds():
    curve = PowerCurve(1e-9, 1.0)
    with pytest.raises(ValueError):
        curve.cost(10.0, 5.0)


def test_invalid_params():
    with pytest.raises(ValueError):
        PowerCurve(coefficient=0.0)
    with pytest.raises(ValueError):
        PowerCurve(coefficient=1.0, exponent=-1.0)
