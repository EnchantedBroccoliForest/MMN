"""Report rendering: the 'confirmed' block and scale-free claims must match the
actual parameters (regression for the Codex review feedback on PR #1)."""

from mmn.cli import _is_ft_production, render, render_mc
from mmn.curves import AffineCurve, PowerCurve
from mmn.montecarlo import McConfig, run_montecarlo
from mmn.simulator import SimConfig, simulate


def _render(**kw):
    base = dict(num_outcomes=4, early_pct=1.0, curve=PowerCurve.ft(),
                total_supply=1e6, buy_fee=0.002, sell_fee=0.002,
                multiples=(1, 100))
    base.update(kw)
    return render(simulate(SimConfig(**base)))


def test_ft_default_shows_verified_curve_and_scale_free():
    out = _render()
    assert "VERIFIED CURVE" in out
    assert "CUSTOM CURVE" not in out
    assert "scale-free" in out


def test_custom_curve_shows_custom_not_verified():
    out = _render(curve=AffineCurve(slope=1e-13))
    assert "CUSTOM CURVE" in out
    assert "VERIFIED CURVE" not in out


def test_no_fee_is_ever_claimed_confirmed():
    # custom fee on the verified curve: fee must be labelled an assumption,
    # and the stale 0.2% claim must never appear.
    out = _render(buy_fee=0.01, sell_fee=0.01)
    assert "VERIFIED CURVE" in out          # curve is still verified
    assert "ASSUMPTION" in out              # but fee is flagged as an assumption
    assert "0.2%" not in out


def test_house_seed_qualifies_scale_free_claim():
    out = _render(house_seed_mcap=5.0)
    assert "DO depend on the $ scale" in out
    # the unconditional "scale-free" reassurance must not appear for seeded runs
    assert "ownership are scale-free: they do NOT depend" not in out


def test_non_usdt_quote_is_not_verified():
    out = _render(quote="DAI")
    assert "CUSTOM CURVE" in out
    assert "VERIFIED CURVE" not in out


def test_mc_render_honors_quote():
    r = run_montecarlo(McConfig(num_outcomes=2, early_pct=1.0, quote="DAI",
                                n_trials=500, seed=1, mean_added_pool=50_000.0))
    out = render_mc(r)
    assert "DAI" in out
    assert "USDT" not in out


def test_is_ft_production_predicate():
    ok = SimConfig(num_outcomes=2, early_pct=1.0, curve=PowerCurve.ft(),
                   buy_fee=0.002, sell_fee=0.002)
    assert _is_ft_production(ok)
    bad = SimConfig(num_outcomes=2, early_pct=1.0,
                    curve=PowerCurve(coefficient=1e-6, exponent=1.0),
                    buy_fee=0.002, sell_fee=0.002)
    assert not _is_ft_production(bad)
