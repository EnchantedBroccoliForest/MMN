"""Report rendering: the 'confirmed' block and scale-free claims must match the
actual parameters (regression for the Codex review feedback on PR #1)."""

from mmn.cli import _is_ft_production, render
from mmn.curves import AffineCurve, PowerCurve
from mmn.simulator import SimConfig, simulate


def _render(**kw):
    base = dict(num_outcomes=4, early_pct=1.0, curve=PowerCurve.ft(),
                total_supply=1e6, buy_fee=0.002, sell_fee=0.002,
                multiples=(1, 100))
    base.update(kw)
    return render(simulate(SimConfig(**base)))


def test_ft_default_shows_confirmed_and_scale_free():
    out = _render()
    assert "CONFIRMED FROM 42" in out
    assert "CUSTOM SCENARIO" not in out
    assert "scale-free" in out


def test_custom_curve_shows_custom_not_confirmed():
    out = _render(curve=AffineCurve(slope=1e-13))
    assert "CUSTOM SCENARIO" in out
    assert "CONFIRMED FROM 42" not in out


def test_custom_fee_is_not_flagged_confirmed():
    out = _render(buy_fee=0.01, sell_fee=0.01)
    assert "CUSTOM SCENARIO" in out
    assert "0.2% per side to treasury" not in out


def test_house_seed_qualifies_scale_free_claim():
    out = _render(house_seed_mcap=5.0)
    assert "DO depend on the $ scale" in out
    # the unconditional "scale-free" reassurance must not appear for seeded runs
    assert "are scale-free" not in out


def test_is_ft_production_predicate():
    ok = SimConfig(num_outcomes=2, early_pct=1.0, curve=PowerCurve.ft(),
                   buy_fee=0.002, sell_fee=0.002)
    assert _is_ft_production(ok)
    bad = SimConfig(num_outcomes=2, early_pct=1.0,
                    curve=PowerCurve(coefficient=1e-6, exponent=1.0),
                    buy_fee=0.002, sell_fee=0.002)
    assert not _is_ft_production(bad)
