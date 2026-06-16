"""Command-line front-end for the MMN 42 / Event Rush offline sandbox.

The OFFLINE / HYPOTHETICAL model (legacy "buy first x% of supply"):

    python -m mmn --outcomes 4 --early-pct 1 --yes
    python -m mmn --outcomes 8 --early-pct 1 --monte-carlo --winner-prior skewed --yes

This is a what-if on INVENTED inputs, not a live market. Fees default to 42's
DOCUMENTED protocol fee (~0.8%), not the earlier (incorrect) 0.2%; absolute USDT
figures depend on an assumed curve scale and are estimates. The live-market
analyzer is parked — see docs/live-analyzer.md.
"""

from __future__ import annotations

import argparse
import math
import sys

from .chart import mc_histogram_svg, ownership_and_roi_svg
from .curves import FT_ALPHA, FT_PRICE_SCALE, PowerCurve
from .fees import DOCUMENTED_PROTOCOL_FEE
from .montecarlo import McConfig, McResult, run_montecarlo
from .simulator import DEFAULT_MULTIPLES, SimConfig, SimResult, simulate

# Offline/hypothetical model defaults. The curve is 42's modeled power curve
# (shape matched to MC_Sim; price scale assumed); the fee here is the DOCUMENTED
# protocol fee (configurable), NOT a confirmed 0.2% (that earlier claim was wrong).
DEFAULTS = {
    "exponent": FT_ALPHA,  # 0.75 (PowerCurveSet1.C1)
    "coefficient": (1.0 + FT_ALPHA) / FT_PRICE_SCALE,  # 1.75/2e6 = 8.75e-7 (matches contract)
    "full_mcap": 100_000.0,  # reference market cap per outcome (sets $ scale)
    "total_supply": None,  # derived from full_mcap unless set explicitly
    "house_seed": 0.0,
    "buy_fee": DOCUMENTED_PROTOCOL_FEE,  # 0.4% production protocol-fee default
    "sell_fee": DOCUMENTED_PROTOCOL_FEE,
    "redeem_tax": 0.05,  # pre-kink dynamic redemption tax default (5%; range ~0.1-5%)
    "quote": "USDT",
}


# ---------------------------------------------------------------------------
# formatting helpers
# ---------------------------------------------------------------------------
def fmt_money(x: float, quote: str = "USDT") -> str:
    if x == 0:
        return f"0 {quote}"
    ax = abs(x)
    if ax >= 1:
        return f"{x:,.2f} {quote}"
    return f"{x:,.6g} {quote}"


def fmt_num(x: float) -> str:
    if x == 0:
        return "0"
    ax = abs(x)
    if ax >= 1000:
        return f"{x:,.0f}"
    if ax >= 1:
        return f"{x:,.2f}"
    return f"{x:.4g}"


def fmt_pct(x: float) -> str:
    return f"{x:,.3f}%"


def fmt_x(roi: float) -> str:
    """ROI as a multiplier, e.g. +900% -> 10.0x."""
    return f"{roi + 1.0:,.2f}x"


def _hr(width: int = 96) -> str:
    return "-" * width


# ---------------------------------------------------------------------------
# report
# ---------------------------------------------------------------------------
def _is_ft_production(cfg) -> bool:
    """True iff the run uses 42's production curve (PowerCurveSet1) and USDT.

    Verified against ft-contracts: exponent 0.75 and k=(n+1)/2,000,000 reproduce
    the on-chain cost/price exactly (above the +start offset). Fees are NOT part of
    this check (they are a separate per-market governance parameter).
    """
    c = cfg.curve
    return (
        isinstance(c, PowerCurve)
        and cfg.quote == "USDT"
        and math.isclose(c.k, (1.0 + FT_ALPHA) / FT_PRICE_SCALE, rel_tol=1e-9)
        and math.isclose(c.n, FT_ALPHA, rel_tol=1e-9)
    )


def _curve_formula(c) -> str:
    if isinstance(c, PowerCurve):
        return f"p(x) = {c.k:g} * x^{c.n:g}"
    return "custom curve"


def render(result: SimResult) -> str:
    cfg = result.config
    quote = cfg.quote
    ft = _is_ft_production(cfg)
    seeded = bool(cfg.house_seed_mcap)
    lines = []
    a = lines.append

    a("=" * 96)
    a("42 / EVENT RUSH  -  OFFLINE / HYPOTHETICAL EARLY-BUYER MODEL")
    a("=" * 96)
    a("  This is a WHAT-IF model on INVENTED inputs, NOT a live market.")
    a("  (The live-market analyzer is parked - see docs/live-analyzer.md.)")
    a("")
    a("INPUTS")
    a(_hr())
    a(f"  Outcomes in market        : {cfg.num_outcomes}")
    a(f"  Early buy (% of supply)   : {cfg.early_pct:g}%  (the cheapest, earliest tokens)")
    a(f"  Per-outcome curve         : {cfg.curve!r}")
    a(f"  Reference supply / outcome: {fmt_num(cfg.total_supply)} tokens")
    if cfg.house_seed_mcap:
        a(f"  House seed / outcome      : {fmt_money(cfg.house_seed_mcap, quote)}")
    a(f"  Buy / sell fee            : {cfg.buy_fee * 100:g}% / {cfg.sell_fee * 100:g}%")
    a(f"  Collateral                : {quote}")
    a("")

    if ft:
        a("42 PRODUCTION CURVE  (verified vs ft-contracts: PowerCurveSet1 + PowerMath)")
        a(_hr())
        a("  - Collateral = USDT (BEP-20, 18 decimals); one market = many ERC-6909 ids")
        a("  - Reserve (staked) = x^(7/4) / 2,000,000 ; market cap = price x supply")
        a("    (C1=0.75, C2=2,000,000 on-chain; the +start=8.888 offset is omitted ->")
        a("    absolute USDT diverges only near zero supply)")
        a("  - Settlement = parimutuel: payout/unit = total_pool / winning_supply")
        a(
            f"  - Fee: {cfg.buy_fee * 100:g}% buy / {cfg.sell_fee * 100:g}% sell "
            "(42 protocol fee, 0.8% one-way / 1.6% round-trip); redeem tax "
        )
        a(f"    {cfg.redeem_tax * 100:g}% (pre-kink; ramps to 90% near settlement on-chain).")
    else:
        a("CUSTOM CURVE  (NOT 42's production curve)")
        a(_hr())
        a(f"  - Curve: marginal price  {_curve_formula(cfg.curve)}")
        a("  - Reserve = cumulative collateral staked (integral of price)")
        a(
            f"  - Fee modelled here: {cfg.buy_fee * 100:g}% buy / {cfg.sell_fee * 100:g}% sell "
            "(your assumption)"
        )
        a("  - Settlement = parimutuel: winners split the pot pro-rata")
        a("  These are YOUR parameters; 42's production curve is mcap=x^(7/4)/2,000,000.")
    a("")
    a("ASSUMPTIONS / SCALE")
    a(_hr())
    if seeded:
        a("  - A house seed is set: it is an ABSOLUTE amount, so ROI and ownership")
        a("    DO depend on the $ scale here (they are scale-free only when seed = 0).")
    else:
        a("  - ROI and ownership are scale-free: they do NOT depend on the $ scale")
        a(f"    (reference market cap / supply); only the {quote} amounts scale with it.")
    a("  - Redeem values apply the pre-kink redemption tax + sell fee; the on-chain")
    a("    tax ramps toward 90% near settlement and the opening LDA premium is omitted.")
    a("")

    a("STEP 1-2  -  ENTRY COST")
    a(_hr())
    a(
        f"  Tokens bought per outcome : {fmt_num(result.tokens_per_outcome)}  "
        f"(= {cfg.early_pct:g}% of {fmt_num(cfg.total_supply)})"
    )
    a(f"  Spend per outcome         : {fmt_money(result.spend_per_outcome, quote)}")
    a(f"  Outcomes bought           : {cfg.num_outcomes}")
    a(f"  >> TOTAL SPEND            : {fmt_money(result.total_spend, quote)}")
    a(f"  Entry price / token       : {fmt_money(result.entry_price, quote)}")
    a(
        f"  Entry reserve / outcome   : {fmt_money(result.entry_reserve, quote)}  "
        f"(cumulative {quote} staked)"
    )
    a(
        f"  Entry market cap/outcome  : {fmt_money(result.entry_market_cap, quote)}  "
        "(price x supply)"
    )
    a("")

    a("STEP 3  -  PROFITABILITY AS RESERVE GROWS  (per single outcome held)")
    a(_hr())
    a(f"  reserve = cumulative {quote} staked ; market cap = price x supply")
    hdr = (
        f"  {'Reserve x':>9} | {'reserve':>12} | {'market cap':>12} | "
        f"{'your own %':>10} | {'redeem value':>14}"
    )
    a(hdr)
    a("  " + _hr(92))
    for s in result.stages:
        a(
            f"  {s.multiple:>8g}x | {fmt_num(s.reserve):>12} | {fmt_num(s.market_cap):>12} | "
            f"{fmt_pct(s.ownership_pct):>10} | {fmt_num(s.redeem_value):>14}"
        )
    a("")
    a(f"  redeem value = {quote} you actually get selling those units back into the curve")
    a("")

    a(
        f"STEP 3  -  AGGREGATE P&L  (all {cfg.num_outcomes} outcomes; spend "
        f"{fmt_money(result.total_spend, quote)})"
    )
    a(_hr())
    hdr2 = f"  {'Reserve x':>9} | {'agg spot':>16} | {'agg redeem':>16} | {'redeem ROI':>10}"
    a(hdr2)
    a("  " + _hr(79))
    for s in result.stages:
        a(
            f"  {s.multiple:>8g}x | {fmt_num(s.agg_spot_value):>16} | "
            f"{fmt_num(s.agg_redeem_value):>16} | {fmt_x(s.redeem_roi):>10}"
        )
    a("")

    a("STEP 3  -  SETTLEMENT (parimutuel) IF THE MARKET RESOLVES AT THIS STAGE")
    a(_hr())
    a(f"  If a held outcome WINS, its holders split the whole {quote} pot pro-rata.")
    a("  (Holdings in the other outcomes settle to zero.)")
    hdr3 = (
        f"  {'Reserve x':>9} | {'amount into mkt':>16} | {'your win payout':>16} | {'win ROI':>10}"
    )
    a(hdr3)
    a("  " + _hr(92))
    for s in result.stages:
        a(
            f"  {s.multiple:>8g}x | {fmt_num(s.total_pot):>16} | "
            f"{fmt_num(s.settle_payout):>16} | {fmt_x(s.settle_roi):>10}"
        )
    a("")
    a("=" * 96)
    a("OFFLINE / HYPOTHETICAL model on invented inputs (live analyzer parked).")
    if ft and not seeded:
        a("Curve is 42's modeled power curve; fee is an assumption. ROI/ownership are")
        a("scale-free; only the absolute amounts depend on --full-mcap ($ scale).")
    elif ft and seeded:
        a("Curve is 42's modeled power curve; fee is an assumption. With a house seed,")
        a("ROI and ownership depend on the $ scale (--full-mcap / --total-supply).")
    else:
        a("CUSTOM curve/params (above) - not 42's modeled curve. Dollar amounts, and")
        a("(with a house seed) ROI/ownership too, depend on the chosen scale.")
    a("=" * 96)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# input plumbing
# ---------------------------------------------------------------------------
def _build_curve(args):
    return PowerCurve(coefficient=args.coefficient, exponent=args.exponent)


def _parse_prior(spec, n):
    """Winner prior: 'uniform' -> None; 'skewed' -> geometric; or a comma list."""
    if spec is None or spec == "uniform":
        return None
    if spec == "skewed":
        w = [0.6**i for i in range(n)]
        return w
    try:
        parts = [float(p) for p in spec.replace(",", " ").split()]
    except ValueError:
        raise ValueError(
            f"--winner-prior must be 'uniform', 'skewed', or a numeric comma list; got {spec!r}"
        ) from None
    if len(parts) != n:
        raise ValueError(f"--winner-prior list has {len(parts)} values, need {n}")
    return parts


def render_mc(mc: McResult) -> str:
    cfg = mc.config
    quote = cfg.quote
    lines = []
    a = lines.append
    a("=" * 96)
    a(
        f"MONTE CARLO  -  {cfg.n_trials:,} trials  (random house seeds, uneven capital, "
        f"random winner)"
    )
    a(_hr())
    a(
        f"  House seed/outcome  : Uniform({cfg.seed_min:g}, {cfg.seed_max:g}) {quote}   "
        f"(MC_Sim default range)"
    )
    a(
        f"  Added capital       : Lognormal, mean {fmt_money(cfg.mean_added_pool, quote)} "
        f"(sigma {cfg.pool_sigma:g})"
    )
    a(
        f"  Winner prior        : {'uniform' if cfg.prior is None else 'custom/skewed'}"
        f"   |  capital concentration {cfg.concentration:g}"
    )
    a(f"  Avg total spend     : {fmt_money(mc.total_spend, quote)}")
    a("")
    a("  SETTLEMENT RETURN  (payout / spend, multiple)")
    a("  " + _hr(92))
    a(f"    mean   : {mc.mean_settle:>7.2f}x        P(profit) : {mc.prob_profit * 100:5.1f}%")
    a(f"    median : {mc.median_settle:>7.2f}x        5th pct  : {mc.p05_settle:>6.2f}x")
    a(f"    95th   : {mc.p95_settle:>7.2f}x")
    a("")
    a(f"  SELL-BACK NOW (redeem) RETURN : mean {mc.mean_redeem:.2f}x")
    a("=" * 96)
    return "\n".join(lines)


def _mc_chart_path(chart_path: str) -> str:
    if "." in chart_path:
        stem, ext = chart_path.rsplit(".", 1)
        return f"{stem}-montecarlo.{ext}"
    return chart_path + "-montecarlo.svg"


def _prompt(prompt_text, default, cast):
    raw = input(f"{prompt_text} [{default}]: ").strip()
    if raw == "":
        return default
    try:
        return cast(raw)
    except ValueError:
        print(f"  invalid value, using default {default}")
        return default


def _parse_multiples(text):
    return tuple(float(p) for p in text.replace(",", " ").split())


def parse_args(argv):
    p = argparse.ArgumentParser(description="42 / Event Rush early-buyer profitability simulator")
    p.add_argument("--outcomes", type=int, help="number of outcomes in the market")
    p.add_argument(
        "--early-pct",
        type=float,
        help="x: percent of each outcome's supply bought as an early buyer",
    )
    p.add_argument("--exponent", type=float, default=DEFAULTS["exponent"])
    p.add_argument("--coefficient", type=float, default=DEFAULTS["coefficient"])
    p.add_argument(
        "--full-mcap",
        type=float,
        default=DEFAULTS["full_mcap"],
        help="reference market cap (USDT) per outcome; sets the $ scale",
    )
    p.add_argument(
        "--total-supply",
        type=float,
        default=DEFAULTS["total_supply"],
        help="reference supply per outcome (overrides --full-mcap)",
    )
    p.add_argument(
        "--house-seed",
        type=float,
        default=DEFAULTS["house_seed"],
        help="USDT the house seeds each outcome with",
    )
    p.add_argument("--buy-fee", type=float, default=DEFAULTS["buy_fee"])
    p.add_argument("--sell-fee", type=float, default=DEFAULTS["sell_fee"])
    p.add_argument(
        "--redeem-tax",
        type=float,
        default=DEFAULTS["redeem_tax"],
        help="pre-kink dynamic redemption tax fraction (~0.001-0.05)",
    )
    p.add_argument("--quote", default=DEFAULTS["quote"])
    p.add_argument(
        "--multiples",
        type=str,
        default=None,
        help="space/comma separated market-cap multiples, e.g. '1 2 10 100'",
    )
    p.add_argument(
        "--chart",
        type=str,
        default=None,
        help="write an SVG chart (ownership + ROI vs growth) to this path",
    )
    p.add_argument(
        "--monte-carlo",
        action="store_true",
        help="run the Monte Carlo (random seeds, uneven capital, random winner)",
    )
    p.add_argument("--mc-trials", type=int, default=20_000)
    p.add_argument(
        "--mc-mean-pool",
        type=float,
        default=None,
        help="expected total later capital across all outcomes (default: full-mcap x outcomes)",
    )
    p.add_argument("--pool-sigma", type=float, default=0.6)
    p.add_argument(
        "--concentration",
        type=float,
        default=8.0,
        help="Dirichlet sharpness for capital allocation (higher = closer to prior)",
    )
    p.add_argument("--seed-min", type=float, default=0.10)
    p.add_argument("--seed-max", type=float, default=10.0)
    p.add_argument(
        "--winner-prior",
        type=str,
        default="uniform",
        help="'uniform', 'skewed', or a comma list of length=outcomes",
    )
    p.add_argument("--mc-seed", type=int, default=0)
    p.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="non-interactive: use flags/defaults without prompting",
    )

    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])
    try:
        return _run_offline(args)
    except ValueError as e:
        print(f"Invalid input: {e}", file=sys.stderr)
        return 2
    except OSError as e:
        print(f"Could not write output file: {e}", file=sys.stderr)
        return 2


def _run_offline(args) -> int:
    interactive = not args.yes and args.outcomes is None and args.early_pct is None
    if interactive:
        print("42 / Event Rush early-buyer simulator - press Enter to accept defaults.\n")
        args.outcomes = _prompt("Number of outcomes in the market", 4, int)
        args.early_pct = _prompt("Early buy: % of each outcome's supply", 1.0, float)
        args.full_mcap = _prompt("Reference market cap per outcome (USDT)", args.full_mcap, float)
        args.house_seed = _prompt("House seed per outcome (USDT, 0 = none)", args.house_seed, float)
        mraw = input(
            f"Market-cap multiples [{' '.join(str(m) for m in DEFAULT_MULTIPLES)}]: "
        ).strip()
        args.multiples = mraw if mraw else None

    if args.outcomes is None:
        args.outcomes = 4
    if args.early_pct is None:
        args.early_pct = 1.0

    curve = _build_curve(args)
    total_supply = (
        args.total_supply if args.total_supply else curve.supply_for_reserve(args.full_mcap)
    )

    multiples = _parse_multiples(args.multiples) if args.multiples else DEFAULT_MULTIPLES

    config = SimConfig(
        num_outcomes=args.outcomes,
        early_pct=args.early_pct,
        curve=curve,
        total_supply=total_supply,
        buy_fee=args.buy_fee,
        sell_fee=args.sell_fee,
        redeem_tax=args.redeem_tax,
        house_seed_mcap=args.house_seed,
        multiples=multiples,
        quote=args.quote,
    )
    result = simulate(config)
    print()
    print(render(result))

    if args.chart:
        with open(args.chart, "w") as fh:
            fh.write(ownership_and_roi_svg(result))
        print(f"\nWrote chart: {args.chart}")

    if args.monte_carlo:
        mc_cfg = McConfig(
            num_outcomes=args.outcomes,
            early_pct=args.early_pct,
            curve=curve,
            total_supply=total_supply,
            buy_fee=args.buy_fee,
            sell_fee=args.sell_fee,
            seed_min=args.seed_min,
            seed_max=args.seed_max,
            prior=_parse_prior(args.winner_prior, args.outcomes),
            mean_added_pool=(
                args.mc_mean_pool
                if args.mc_mean_pool
                else curve.reserve(total_supply) * args.outcomes
            ),
            pool_sigma=args.pool_sigma,
            concentration=args.concentration,
            n_trials=args.mc_trials,
            seed=args.mc_seed,
            quote=args.quote,
        )
        mc = run_montecarlo(mc_cfg)
        print()
        print(render_mc(mc))
        if args.chart:
            hp = _mc_chart_path(args.chart)
            with open(hp, "w") as fh:
                fh.write(mc_histogram_svg(mc))
            print(f"\nWrote chart: {hp}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
