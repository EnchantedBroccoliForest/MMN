"""Monte Carlo sanity and invariants."""

import math

import pytest

from mmn.chart import mc_histogram_svg, ownership_and_roi_svg
from mmn.curves import PowerCurve
from mmn.montecarlo import McConfig, run_montecarlo
from mmn.simulator import SimConfig, simulate


def mc(**kw):
    base = dict(num_outcomes=4, early_pct=1.0, n_trials=3000, seed=7, mean_added_pool=400_000.0)
    base.update(kw)
    return McConfig(**base)


def test_reproducible_with_seed():
    a = run_montecarlo(mc(seed=42))
    b = run_montecarlo(mc(seed=42))
    assert a.settle_mult == b.settle_mult


def test_stats_are_ordered_and_finite():
    r = run_montecarlo(mc())
    assert r.p05_settle <= r.median_settle <= r.p95_settle
    assert 0.0 <= r.prob_profit <= 1.0
    assert all(math.isfinite(v) and v >= 0 for v in r.settle_mult)
    assert r.mean_settle > 0


def test_more_growth_increases_settlement():
    """A bigger inflow of later capital lifts the early buyer's settlement payout
    (payout scales like pool^(3/7) while entry spend stays put)."""
    small = run_montecarlo(mc(mean_added_pool=100_000.0))
    big = run_montecarlo(mc(mean_added_pool=2_000_000.0))
    assert big.mean_settle > small.mean_settle


def test_zero_seed_range_is_allowed():
    r = run_montecarlo(mc(seed_min=0.0, seed_max=0.0))
    assert r.mean_settle > 0


def test_prior_length_validation():
    with pytest.raises(ValueError):
        run_montecarlo(mc(prior=[0.5, 0.5]))  # n=4 but prior len 2


def test_charts_emit_svg():
    result = simulate(
        SimConfig(
            num_outcomes=4,
            early_pct=1.0,
            curve=PowerCurve.ft(),
            total_supply=1e6,
            multiples=(1, 2, 10, 100),
        )
    )
    svg = ownership_and_roi_svg(result)
    assert svg.startswith("<svg") and svg.rstrip().endswith("</svg>")
    assert "ownership" in svg

    r = run_montecarlo(mc())
    h = mc_histogram_svg(r)
    assert h.startswith("<svg") and "Monte Carlo" in h
