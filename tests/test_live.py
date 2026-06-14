"""Tests for the live-market buyer analyzer and report."""

import pytest

from mmn.fees import FeeModel
from mmn.ft_api import market_from_json
from mmn.live_report import render_live, render_market_list
from mmn.live_simulator import BuyerPlan, analyze


def make_market(n=3, minted=(4_000_000.0, 2_000_000.0, 800_000.0),
                caps=(50_000.0, 18_000.0, 4_000.0)):
    return market_from_json({
        "title": "T", "address": "0x1", "status": "live", "collateral": "USDT",
        "outcomes": [
            {"tokenId": str(i), "name": f"O{i}", "price": 0.01,
             "marketCap": caps[i], "mintedQuantity": minted[i]}
            for i in range(n)
        ],
    })


def fee(**kw):
    base = dict(protocol_fee=0.008, redeem_tax_mode="documented",
                manual_redeem_tax=0.0, gas_usd=0.0)
    base.update(kw)
    return FeeModel(**base)


# ----------------------------- fees ---------------------------------------
def test_fee_net_and_amount():
    f = fee(protocol_fee=0.008)
    assert f.net_to_curve(100.0) == pytest.approx(99.2)
    assert f.buy_fee(100.0) == pytest.approx(0.8)


def test_redeem_tax_modes():
    assert fee(redeem_tax_mode="ignore").redeem_tax_rate() == pytest.approx(0.008)
    assert fee(redeem_tax_mode="manual", manual_redeem_tax=0.05).redeem_tax_rate() \
        == pytest.approx(0.058)


def test_bad_fee_validation():
    with pytest.raises(ValueError):
        FeeModel(protocol_fee=1.5)
    with pytest.raises(ValueError):
        FeeModel(redeem_tax_mode="bogus")


# ----------------------------- allocation ---------------------------------
def test_equal_budget_allocation():
    r = analyze(make_market(), BuyerPlan(budget=300.0), fee())
    spends = [o.spend_gross for o in r.outcomes]
    assert spends == pytest.approx([100.0, 100.0, 100.0])
    assert r.total_spend == pytest.approx(300.0)
    assert r.total_fee == pytest.approx(300.0 * 0.008)


def test_per_outcome_budget():
    r = analyze(make_market(), BuyerPlan(per_outcome_budget=50.0), fee())
    assert r.total_spend == pytest.approx(150.0)


def test_custom_allocation_weights():
    r = analyze(make_market(),
                BuyerPlan(budget=300.0, allocation="custom", custom_weights=[3, 1, 1]),
                fee())
    spends = [o.spend_gross for o in r.outcomes]
    assert spends == pytest.approx([180.0, 60.0, 60.0])


def test_custom_allocation_wrong_length_raises():
    with pytest.raises(ValueError):
        analyze(make_market(),
                BuyerPlan(budget=300.0, allocation="custom", custom_weights=[1, 1]),
                fee())


def test_plan_requires_exactly_one_mode():
    with pytest.raises(ValueError):
        BuyerPlan(budget=100.0, per_outcome_budget=50.0)
    with pytest.raises(ValueError):
        BuyerPlan()


# ------------------------- target ownership -------------------------------
def test_target_ownership_is_met():
    target = 2.0
    r = analyze(make_market(), BuyerPlan(target_ownership_pct=target), fee())
    for o in r.outcomes:
        assert o.ownership_pct == pytest.approx(target, rel=1e-6)


# ------------------------- settlement payout ------------------------------
def test_settlement_payout_is_ownership_times_pot():
    r = analyze(make_market(), BuyerPlan(budget=300.0), fee())
    pot = r.pot_post
    for o in r.outcomes:
        assert o.payout_if_win == pytest.approx(o.ownership_pct / 100.0 * pot)


def test_breakeven_pot_consistent():
    r = analyze(make_market(), BuyerPlan(budget=300.0), fee())
    for o in r.outcomes:
        # at the break-even pot, a win returns exactly the invested amount
        assert o.ownership_pct / 100.0 * o.breakeven_pot == pytest.approx(r.total_invested)


def test_added_capital_dilutes_and_grows_pot():
    base = analyze(make_market(), BuyerPlan(budget=300.0), fee())
    grown = analyze(make_market(), BuyerPlan(budget=300.0), fee(),
                    added_capital=500_000.0)
    # ownership falls (more supply), pot used in settlement grows
    assert grown.outcomes[0].payout_if_win != base.outcomes[0].payout_if_win
    assert grown.expected_payout > 0


def test_gas_is_added_to_invested():
    r = analyze(make_market(), BuyerPlan(budget=300.0), fee(gas_usd=5.0))
    assert r.total_invested == pytest.approx(305.0)


# ----------------------------- priors -------------------------------------
def test_uniform_prior_when_none():
    r = analyze(make_market(n=3), BuyerPlan(budget=300.0), fee())
    assert r.prior_is_default
    assert r.prior == pytest.approx([1/3, 1/3, 1/3])


def test_custom_prior_normalized():
    r = analyze(make_market(), BuyerPlan(budget=300.0), fee(), prior=[2, 1, 1])
    assert r.prior == pytest.approx([0.5, 0.25, 0.25])
    assert not r.prior_is_default


def test_invalid_prior_length():
    with pytest.raises(ValueError):
        analyze(make_market(n=3), BuyerPlan(budget=300.0), fee(), prior=[0.5, 0.5])


def test_negative_prior_rejected():
    with pytest.raises(ValueError):
        analyze(make_market(), BuyerPlan(budget=300.0), fee(), prior=[-1, 1, 1])


# --------------------------- missing fields -------------------------------
def test_missing_minted_quantity_derives_supply_with_warning():
    m = market_from_json({"title": "T", "collateral": "USDT", "outcomes": [
        {"name": "A", "marketCap": 10_000.0},   # no mintedQuantity
        {"name": "B", "marketCap": 5_000.0, "mintedQuantity": 1_000_000.0},
    ]})
    r = analyze(m, BuyerPlan(budget=200.0), fee())
    assert r.outcomes[0].supply_derived is True
    assert r.outcomes[0].start_supply > 0
    assert any("derived from market cap" in w for w in r.warnings)


def test_market_with_no_outcomes_raises():
    with pytest.raises(ValueError):
        analyze(market_from_json({"title": "empty", "outcomes": []}),
                BuyerPlan(budget=100.0), fee())


# ----------------------------- report -------------------------------------
def test_render_live_has_all_sections():
    r = analyze(make_market(), BuyerPlan(budget=300.0), fee(), prior=[3, 2, 1])
    out = render_live(r)
    for section in ["MARKET SUMMARY", "CURRENT OUTCOMES", "BUYER PLAN", "EXPENSES",
                    "OWNERSHIP AFTER BUY", "SETTLEMENT PAYOUT BY WINNING OUTCOME",
                    "EXPECTED PROFITABILITY", "EXIT / REDEEM", "ASSUMPTIONS & WARNINGS"]:
        assert section in out
    assert "APPROXIMATE" in out          # redeem caveat present
    assert "0.2%" not in out             # stale fee claim gone


def test_render_market_list():
    markets = [make_market(), make_market(n=2, minted=(1e6, 1e6), caps=(100.0, 100.0))]
    out = render_market_list(markets, "live")
    assert "status=live" in out and "2 shown" in out


def test_render_market_list_empty():
    assert "no markets" in render_market_list([], "live")
