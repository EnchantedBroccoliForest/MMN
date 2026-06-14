"""Flask web UI for the 42 / Event Rush early-buyer profitability simulator.

Wraps the dependency-free ``mmn`` package with a small JSON API and serves a
single-page front-end. Run on port 5000 for the Replit web preview.
"""

from __future__ import annotations

import os
from dataclasses import asdict
from typing import Any, Dict

from flask import Flask, jsonify, render_template, request

from mmn.curves import AffineCurve, PowerCurve
from mmn.simulator import DEFAULT_MULTIPLES, SimConfig, simulate
from mmn.montecarlo import McConfig, run_montecarlo

MAX_MC_TRIALS = 200_000

app = Flask(__name__)


def _build_curve(data: Dict[str, Any]):
    curve_kind = data.get("curve", "power")
    if curve_kind == "affine":
        return AffineCurve(
            slope=float(data.get("slope", 1e-13)),
            base=float(data.get("base", 0.0)),
        )
    return PowerCurve(
        coefficient=float(data.get("coefficient", 1.0 / 2_000_000.0)),
        exponent=float(data.get("exponent", 0.75)),
    )


def _parse_multiples(raw) -> tuple:
    if not raw:
        return DEFAULT_MULTIPLES
    if isinstance(raw, str):
        parts = [p for p in raw.replace(",", " ").split() if p]
        return tuple(float(p) for p in parts) if parts else DEFAULT_MULTIPLES
    return tuple(float(p) for p in raw)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/favicon.ico")
def favicon():
    return ("", 204)


@app.route("/api/simulate", methods=["POST"])
def api_simulate():
    data = request.get_json(silent=True)
    if data is None:
        return jsonify({"error": "Request body must be valid JSON."}), 400
    try:
        curve = _build_curve(data)
        full_mcap = float(data.get("full_mcap", 100_000.0))
        total_supply = data.get("total_supply")
        if total_supply:
            total_supply = float(total_supply)
        else:
            total_supply = curve.supply_for_reserve(full_mcap)

        config = SimConfig(
            num_outcomes=int(data.get("num_outcomes", 4)),
            early_pct=float(data.get("early_pct", 1.0)),
            curve=curve,
            total_supply=total_supply,
            buy_fee=float(data.get("buy_fee", 0.002)),
            sell_fee=float(data.get("sell_fee", 0.002)),
            house_seed_mcap=float(data.get("house_seed", 0.0)),
            multiples=_parse_multiples(data.get("multiples")),
            quote=str(data.get("quote", "USDT")),
        )
        result = simulate(config)
    except (ValueError, TypeError, OverflowError) as exc:
        return jsonify({"error": str(exc)}), 400

    return jsonify(
        {
            "quote": config.quote,
            "is_production": _is_production(config),
            "num_outcomes": config.num_outcomes,
            "early_pct": config.early_pct,
            "total_supply": config.total_supply,
            "house_seed": config.house_seed_mcap,
            "buy_fee": config.buy_fee,
            "sell_fee": config.sell_fee,
            "tokens_per_outcome": result.tokens_per_outcome,
            "spend_per_outcome": result.spend_per_outcome,
            "total_spend": result.total_spend,
            "entry_price": result.entry_price,
            "entry_market_cap": result.entry_market_cap,
            "stages": [asdict(s) for s in result.stages],
        }
    )


@app.route("/api/montecarlo", methods=["POST"])
def api_montecarlo():
    data = request.get_json(silent=True)
    if data is None:
        return jsonify({"error": "Request body must be valid JSON."}), 400
    try:
        curve = _build_curve(data)
        full_mcap = float(data.get("full_mcap", 100_000.0))
        total_supply = data.get("total_supply")
        if total_supply:
            total_supply = float(total_supply)
        else:
            total_supply = curve.supply_for_reserve(full_mcap)

        num_outcomes = int(data.get("num_outcomes", 4))
        mean_pool = data.get("mc_mean_pool")
        if mean_pool:
            mean_pool = float(mean_pool)
        else:
            mean_pool = curve.reserve(total_supply) * num_outcomes

        prior_spec = data.get("winner_prior", "uniform")
        prior = _parse_prior(prior_spec, num_outcomes)

        mc_cfg = McConfig(
            num_outcomes=num_outcomes,
            early_pct=float(data.get("early_pct", 1.0)),
            curve=curve,
            total_supply=total_supply,
            buy_fee=float(data.get("buy_fee", 0.002)),
            sell_fee=float(data.get("sell_fee", 0.002)),
            seed_min=float(data.get("seed_min", 0.10)),
            seed_max=float(data.get("seed_max", 10.0)),
            prior=prior,
            mean_added_pool=mean_pool,
            pool_sigma=float(data.get("pool_sigma", 0.6)),
            concentration=float(data.get("concentration", 8.0)),
            n_trials=min(int(data.get("mc_trials", 20_000)), MAX_MC_TRIALS),
            seed=int(data.get("mc_seed", 0)),
            quote=str(data.get("quote", "USDT")),
        )
        mc = run_montecarlo(mc_cfg)
    except (ValueError, TypeError, OverflowError) as exc:
        return jsonify({"error": str(exc)}), 400

    hist = _histogram(mc.settle_mult, bins=40)
    return jsonify(
        {
            "quote": mc_cfg.quote,
            "n_trials": mc_cfg.n_trials,
            "total_spend": mc.total_spend,
            "prob_profit": mc.prob_profit,
            "mean_settle": mc.mean_settle,
            "median_settle": mc.median_settle,
            "p05_settle": mc.p05_settle,
            "p95_settle": mc.p95_settle,
            "mean_redeem": mc.mean_redeem,
            "histogram": hist,
        }
    )


def _parse_prior(spec, n):
    if spec is None or spec == "uniform":
        return None
    if spec == "skewed":
        return [0.6 ** i for i in range(n)]
    parts = [float(p) for p in str(spec).replace(",", " ").split() if p]
    if len(parts) != n:
        raise ValueError(f"winner prior list has {len(parts)} values, need {n}")
    return parts


def _histogram(values, bins=40):
    if not values:
        return {"edges": [], "counts": []}
    lo = min(values)
    hi = max(values)
    if hi <= lo:
        hi = lo + 1.0
    width = (hi - lo) / bins
    counts = [0] * bins
    for v in values:
        idx = int((v - lo) / width)
        if idx >= bins:
            idx = bins - 1
        if idx < 0:
            idx = 0
        counts[idx] += 1
    edges = [lo + i * width for i in range(bins + 1)]
    return {"edges": edges, "counts": counts}


def _is_production(cfg) -> bool:
    import math

    c = cfg.curve
    return (
        isinstance(c, PowerCurve)
        and cfg.quote == "USDT"
        and math.isclose(c.k, 1.0 / 2_000_000.0, rel_tol=1e-9)
        and math.isclose(c.n, 0.75, rel_tol=1e-9)
        and math.isclose(cfg.buy_fee, 0.002, rel_tol=1e-9)
        and math.isclose(cfg.sell_fee, 0.002, rel_tol=1e-9)
    )


if __name__ == "__main__":
    debug = os.environ.get("FLASK_DEBUG", "").lower() in ("1", "true", "yes")
    app.run(host="0.0.0.0", port=5000, debug=debug)
