"""Report rendering: the modeled-curve block and scale-free claims must match the
actual parameters, and the stale 0.2%/"verified"/"exact" claims must never appear.
Also covers offline error exit codes."""

from mmn.cli import _is_ft_production, main, render, render_mc
from mmn.curves import PowerCurve
from mmn.montecarlo import McConfig, run_montecarlo
from mmn.simulator import SimConfig, simulate


def _render(**kw):
    base = dict(
        num_outcomes=4,
        early_pct=1.0,
        curve=PowerCurve.ft(),
        total_supply=1e6,
        buy_fee=0.008,
        sell_fee=0.008,
        multiples=(1, 100),
    )
    base.update(kw)
    return render(simulate(SimConfig(**base)))


def test_ft_default_shows_production_curve_and_scale_free():
    out = _render()
    assert "42 PRODUCTION CURVE" in out
    assert "CUSTOM CURVE" not in out
    assert "scale-free" in out


def test_custom_curve_shows_custom_not_production():
    out = _render(curve=PowerCurve(coefficient=1e-9, exponent=1.0))  # off the 42 curve
    assert "CUSTOM CURVE" in out
    assert "42 PRODUCTION CURVE" not in out


def test_no_stale_fee_claims():
    # the stale 0.2% claim must never appear (production fee is 0.8% one-way)
    out = _render(buy_fee=0.008, sell_fee=0.008)
    assert "42 PRODUCTION CURVE" in out
    assert "0.2%" not in out


def test_no_exact_or_confirmed_claims_anywhere():
    out = _render()
    lowered = out.lower()
    assert "verified curve" not in lowered
    assert "roi is exact" not in lowered
    assert "0.2%" not in lowered
    # no POSITIVE confirmation claim (honest negations like "not confirmed" are ok)
    for bad in (
        "42 confirmed",
        "confirmed production",
        "fees confirmed",
        "fee confirmed",
        "confirmed curve",
    ):
        assert bad not in lowered


def test_house_seed_qualifies_scale_free_claim():
    out = _render(house_seed_mcap=5.0)
    assert "DO depend on the $ scale" in out
    # the unconditional "scale-free" reassurance must not appear for seeded runs
    assert "ownership are scale-free: they do NOT depend" not in out


def test_non_usdt_quote_is_not_production():
    out = _render(quote="DAI")
    assert "CUSTOM CURVE" in out
    assert "42 PRODUCTION CURVE" not in out


def test_mc_render_honors_quote():
    r = run_montecarlo(
        McConfig(
            num_outcomes=2,
            early_pct=1.0,
            quote="DAI",
            n_trials=500,
            seed=1,
            mean_added_pool=50_000.0,
        )
    )
    out = render_mc(r)
    assert "DAI" in out
    assert "USDT" not in out


def test_is_ft_production_predicate():
    ok = SimConfig(
        num_outcomes=2, early_pct=1.0, curve=PowerCurve.ft(), buy_fee=0.008, sell_fee=0.008
    )
    assert _is_ft_production(ok)
    bad = SimConfig(
        num_outcomes=2,
        early_pct=1.0,
        curve=PowerCurve(coefficient=1e-6, exponent=1.0),
        buy_fee=0.008,
        sell_fee=0.008,
    )
    assert not _is_ft_production(bad)


# ----------------------------- CLI exit codes ------------------------------
def test_bad_winner_prior_returns_2(capsys):
    # wrong-length prior must surface as a clean exit code 2, not a traceback
    rc = main(
        [
            "--outcomes",
            "3",
            "--early-pct",
            "1",
            "--yes",
            "--winner-prior",
            "0.5,0.5",
            "--monte-carlo",
            "--mc-trials",
            "100",
        ]
    )
    assert rc == 2
    err = capsys.readouterr().err
    assert "winner-prior" in err
