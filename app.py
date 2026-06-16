"""Quart (ASGI) web UI for the 42 / Event Rush offline sandbox.

Wraps the ``mmn`` package with a small async JSON API (`/api/simulate`,
`/api/montecarlo`) and serves the single-page front-end.

Async boundary: the CPU-bound simulator / Monte Carlo run in a worker thread
(`asyncio.to_thread`) so they never block the ASGI event loop. Run under uvicorn
with uvloop (see README / .replit). The live-market analyzer is parked — see
docs/live-analyzer.md.
"""

from __future__ import annotations

import asyncio
import math
import os
from dataclasses import asdict
from pathlib import Path
from typing import Any

from quart import Quart, jsonify, render_template, request

from mmn.curves import PowerCurve
from mmn.fees import DOCUMENTED_PROTOCOL_FEE
from mmn.montecarlo import McConfig, run_montecarlo
from mmn.runtime import active_loop_name
from mmn.simulator import DEFAULT_MULTIPLES, SimConfig, simulate

MAX_MC_TRIALS = 200_000
MAX_NUM_OUTCOMES = 100
DEFAULT_FEE = DOCUMENTED_PROTOCOL_FEE  # 0.8% one-way protocol fee (1.6% round-trip)
DEFAULT_REDEEM_TAX = 0.05  # 5% pre-kink redemption tax (default)
# Redeem-ROI band shown on the chart: best (min tax) .. worst (max tax).
REDEEM_TAX_MIN = 0.001  # 0.1%
REDEEM_TAX_MAX = 0.05  # 5%

app = Quart(__name__)

_STATIC_DIR = Path(__file__).parent / "static"


def _asset_v(name: str) -> int:
    """Static-asset cache-bust token = file mtime; changes when the file changes."""
    try:
        return int((_STATIC_DIR / name).stat().st_mtime)
    except OSError:
        return 0


# 42 production curve coefficient: k = (n+1)/c2 = 1.75/2,000,000 (see curves.py).
FT_COEFFICIENT = (1.0 + 0.75) / 2_000_000.0  # 8.75e-7


def _build_curve(data: dict[str, Any]):
    # 42's production curve is the power curve (PowerLDACurveV2 core); coefficient
    # and exponent default to PowerCurveSet1 and are overridable for exploration.
    return PowerCurve(
        coefficient=float(data.get("coefficient", FT_COEFFICIENT)),
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
async def index():
    return await render_template("index.html", js_v=_asset_v("app.js"), css_v=_asset_v("style.css"))


@app.route("/favicon.ico")
async def favicon():
    return ("", 204)


@app.route("/api/simulate", methods=["POST"])
async def api_simulate():
    data = await request.get_json(silent=True)
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
            num_outcomes=min(int(data.get("num_outcomes", 4)), MAX_NUM_OUTCOMES),
            early_pct=float(data.get("early_pct", 1.0)),
            curve=curve,
            total_supply=total_supply,
            buy_fee=float(data.get("buy_fee", DEFAULT_FEE)),
            sell_fee=float(data.get("sell_fee", DEFAULT_FEE)),
            redeem_tax=float(data.get("redeem_tax", DEFAULT_REDEEM_TAX)),
            house_seed_mcap=float(data.get("house_seed", 0.0)),
            multiples=_parse_multiples(data.get("multiples")),
            quote=str(data.get("quote", "USDT")),
        )
        # CPU-bound -> offload so the event loop stays responsive.
        result = await asyncio.to_thread(simulate, config)
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
            "redeem_tax": config.redeem_tax,
            "tokens_per_outcome": result.tokens_per_outcome,
            "spend_per_outcome": result.spend_per_outcome,
            "total_spend": result.total_spend,
            "entry_price": result.entry_price,
            "entry_reserve": result.entry_reserve,
            "entry_market_cap": result.entry_market_cap,
            "stages": _stages_with_redeem_band(result, config),
        }
    )


def _stages_with_redeem_band(result, config):
    """Serialize stages, adding the redeem-ROI band across REDEEM_TAX_MIN..MAX.

    agg_redeem_value already bakes in (1 - redeem_tax)(1 - sell_fee); divide that
    tax factor back out, then re-apply the band's tax endpoints. Redeem proceeds are
    linear in (1 - tax), so this is exact.
    """
    ts = result.total_spend
    tax_factor = 1.0 - config.redeem_tax
    out = []
    for s in result.stages:
        d = asdict(s)
        base = s.agg_redeem_value / tax_factor if tax_factor > 0 else s.agg_redeem_value
        if ts > 0:
            d["redeem_roi_band_hi"] = base * (1.0 - REDEEM_TAX_MIN) / ts - 1.0  # min tax -> best
            d["redeem_roi_band_lo"] = base * (1.0 - REDEEM_TAX_MAX) / ts - 1.0  # max tax -> worst
        else:
            d["redeem_roi_band_hi"] = d["redeem_roi_band_lo"] = 0.0
        out.append(d)
    return out


@app.route("/api/montecarlo", methods=["POST"])
async def api_montecarlo():
    data = await request.get_json(silent=True)
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

        num_outcomes = min(int(data.get("num_outcomes", 4)), MAX_NUM_OUTCOMES)
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
            buy_fee=float(data.get("buy_fee", DEFAULT_FEE)),
            sell_fee=float(data.get("sell_fee", DEFAULT_FEE)),
            redeem_tax_min=float(data.get("redeem_tax_min", 0.001)),
            redeem_tax_max=float(data.get("redeem_tax_max", 0.05)),
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
        # CPU-bound (potentially seconds) -> offload to a worker thread.
        mc = await asyncio.to_thread(run_montecarlo, mc_cfg)
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
        return [0.6**i for i in range(n)]
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
    """True when the config matches 42's production curve (PowerCurveSet1 + 0.4% fee).

    Verified against ft-contracts: exponent 0.75, k=(n+1)/2,000,000, USDT, 0.4% fee.
    The opening LDA premium and the +start offset are not modelled, so the UI still
    flags absolute amounts as approximate near the curve start.
    """
    c = cfg.curve
    return (
        isinstance(c, PowerCurve)
        and cfg.quote == "USDT"
        and math.isclose(c.k, FT_COEFFICIENT, rel_tol=1e-9)
        and math.isclose(c.n, 0.75, rel_tol=1e-9)
        and math.isclose(cfg.buy_fee, DEFAULT_FEE, rel_tol=1e-9)
        and math.isclose(cfg.sell_fee, DEFAULT_FEE, rel_tol=1e-9)
    )


DEFAULT_PORT = 3000  # 5000 collides with macOS AirPlay Receiver; override via PORT

if __name__ == "__main__":
    # Dev entrypoint: serve the ASGI app under uvicorn with uvloop (same stack as
    # production; see .replit / README). 0.0.0.0 is required by the Replit proxy;
    # restrict via HOST elsewhere if exposing publicly. Port is PORT-overridable.
    import uvicorn

    host = os.environ.get("HOST", "0.0.0.0")  # noqa: S104 (Replit needs 0.0.0.0)
    port = int(os.environ.get("PORT", DEFAULT_PORT))
    log_level = "debug" if os.environ.get("DEBUG", "").lower() in ("1", "true", "yes") else "info"
    uvicorn.run(app, host=host, port=port, loop=active_loop_name(), log_level=log_level)
