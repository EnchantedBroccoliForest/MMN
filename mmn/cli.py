"""Command-line front-end for the 42 early-buyer profitability simulator.

Run interactively:        python -m mmn
Run non-interactively:    python -m mmn --outcomes 4 --early-pct 1 --yes

Curve and fee are 42's CONFIRMED production values (verified against MC_Sim):
    price p(x) = x^(3/4) / 2_000_000 ,  fee 0.2% per side.
The only free knob is the $ scale, set by --full-mcap (a reference market cap
per outcome). ROI and ownership are independent of it.
"""

from __future__ import annotations

import argparse
import math
import sys

from .curves import FT_ALPHA, FT_PRICE_SCALE, AffineCurve, PowerCurve
from .simulator import DEFAULT_MULTIPLES, SimConfig, SimResult, simulate
from .montecarlo import McConfig, McResult, run_montecarlo
from .chart import mc_histogram_svg, ownership_and_roi_svg

# ============================================================================
#  42 PRODUCTION DEFAULTS (verified against MC_Sim/parimutuel_sim/market.py)
#    price p(x) = x^(3/4) / 2_000_000  ->  PowerCurve(k=1/2_000_000, n=3/4)
#    market cap = cumulative USDT staked = (4/7)*x^(7/4)/2_000_000
#    fee = 0.2% per side ; parimutuel settlement.
# ============================================================================
DEFAULTS = {
    "curve": "power",
    "exponent": FT_ALPHA,                 # 0.75
    "coefficient": 1.0 / FT_PRICE_SCALE,  # 5e-7
    "slope": 1e-13,                       # affine alt only
    "base": 0.0,
    "full_mcap": 100_000.0,               # reference market cap per outcome (sets $ scale)
    "total_supply": None,                 # derived from full_mcap unless set explicitly
    "house_seed": 0.0,                    # USDT the house seeds each outcome with
    "buy_fee": 0.002,                     # 0.2% per buy  (confirmed)
    "sell_fee": 0.002,                    # 0.2% per sell (confirmed)
    "quote": "USDT",
}
# ============================================================================


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
    """True iff the run uses 42's exact production curve and the 0.2% fees."""
    c = cfg.curve
    return (isinstance(c, PowerCurve)
            and math.isclose(c.k, 1.0 / FT_PRICE_SCALE, rel_tol=1e-9)
            and math.isclose(c.n, FT_ALPHA, rel_tol=1e-9)
            and math.isclose(cfg.buy_fee, 0.002, rel_tol=1e-9)
            and math.isclose(cfg.sell_fee, 0.002, rel_tol=1e-9))


def _curve_formula(c) -> str:
    if isinstance(c, PowerCurve):
        return f"p(x) = {c.k:g} * x^{c.n:g}"
    if isinstance(c, AffineCurve):
        return f"p(x) = {c.m:g} * x + {c.b:g}"
    return "custom curve"


def render(result: SimResult) -> str:
    cfg = result.config
    quote = cfg.quote
    ft = _is_ft_production(cfg)
    seeded = bool(cfg.house_seed_mcap)
    lines = []
    a = lines.append

    a("=" * 96)
    a("42 / EVENT RUSH  -  EARLY-BUYER PROFITABILITY SIMULATOR")
    a("=" * 96)
    a("")
    a("INPUTS")
    a(_hr())
    a(f"  Outcomes in market        : {cfg.num_outcomes}")
    a(f"  Early buy (% of supply)   : {cfg.early_pct:g}%  (the cheapest, earliest tokens)")
    a(f"  Per-outcome curve         : {cfg.curve!r}")
    a(f"  Reference supply / outcome: {fmt_num(cfg.total_supply)} tokens")
    if cfg.house_seed_mcap:
        a(f"  House seed / outcome      : {fmt_money(cfg.house_seed_mcap, quote)}")
    a(f"  Buy / sell fee            : {cfg.buy_fee*100:g}% / {cfg.sell_fee*100:g}%")
    a(f"  Collateral                : {quote}")
    a("")

    if ft:
        a("CONFIRMED FROM 42  (contracts IFTMarketV2/IFTCurve + MC_Sim/parimutuel_sim)")
        a(_hr())
        a("  - Collateral = USDT (BEP-20, 18 decimals); one market = many ERC-6909 ids")
        a("  - Curve: marginal price  p(x) = x^(3/4) / 2,000,000")
        a("  - Market cap = cumulative USDT staked = (4/7) * x^(7/4) / 2,000,000")
        a("  - Fee = 0.2% per side to treasury")
        a("  - Settlement = parimutuel: payout/unit = total_pool / winning_supply,")
        a("    i.e. winners split the whole USDT pot pro-rata")
    else:
        a("CUSTOM SCENARIO  (NOT 42's confirmed production calibration)")
        a(_hr())
        a(f"  - Curve: marginal price  {_curve_formula(cfg.curve)}")
        a("  - Market cap = cumulative collateral staked (integral of price)")
        a(f"  - Fee = {cfg.buy_fee*100:g}% buy / {cfg.sell_fee*100:g}% sell")
        a("  - Settlement = parimutuel: winners split the pot pro-rata")
        a("  These are YOUR parameters; 42's production values are p(x)=x^(3/4)/2,000,000")
        a("  with 0.2% per-side fees.")
    a("")
    a("ASSUMPTIONS / SCALE")
    a(_hr())
    if seeded:
        a("  - A house seed is set: it is an ABSOLUTE amount, so ROI and ownership")
        a("    DO depend on the $ scale here (they are scale-free only when seed = 0).")
    else:
        a("  - ROI and ownership are scale-free: they do NOT depend on the $ scale")
        a("    (reference market cap / supply); only the USDT amounts scale with it.")
    a("  - MC_Sim is mint-and-hold; redeem values assume 42's sell-back is available")
    a("")

    a("STEP 1-2  -  ENTRY COST")
    a(_hr())
    a(f"  Tokens bought per outcome : {fmt_num(result.tokens_per_outcome)}  "
      f"(= {cfg.early_pct:g}% of {fmt_num(cfg.total_supply)})")
    a(f"  Spend per outcome         : {fmt_money(result.spend_per_outcome, quote)}")
    a(f"  Outcomes bought           : {cfg.num_outcomes}")
    a(f"  >> TOTAL SPEND            : {fmt_money(result.total_spend, quote)}")
    a(f"  Entry price / token       : {fmt_money(result.entry_price, quote)}")
    a(f"  Entry market cap/outcome  : {fmt_money(result.entry_market_cap, quote)}  "
      f"(cumulative USDT staked)")
    a("")

    a("STEP 3  -  PROFITABILITY AS MARKET CAP GROWS  (per single outcome held)")
    a(_hr())
    a("  market cap = cumulative USDT staked in that outcome")
    hdr = (f"  {'MCcap x':>7} | {'mkt cap':>14} | {'price':>12} | "
           f"{'your own %':>10} | {'spot value':>14} | {'redeem value':>14}")
    a(hdr)
    a("  " + _hr(92))
    for s in result.stages:
        a(f"  {s.multiple:>6g}x | {fmt_num(s.market_cap):>14} | {fmt_num(s.price):>12} | "
          f"{fmt_pct(s.ownership_pct):>10} | {fmt_num(s.spot_value):>14} | "
          f"{fmt_num(s.redeem_value):>14}")
    a("")
    a("  spot value  = units x current price (mark-to-market, ignores sell slippage)")
    a("  redeem value= USDT you actually get selling those units back into the curve")
    a("")

    a(f"STEP 3  -  AGGREGATE P&L  (all {cfg.num_outcomes} outcomes; spend "
      f"{fmt_money(result.total_spend, quote)})")
    a(_hr())
    hdr2 = (f"  {'MCcap x':>7} | {'agg spot':>16} | {'spot ROI':>10} | "
            f"{'agg redeem':>16} | {'redeem ROI':>10}")
    a(hdr2)
    a("  " + _hr(92))
    for s in result.stages:
        a(f"  {s.multiple:>6g}x | {fmt_num(s.agg_spot_value):>16} | {fmt_x(s.spot_roi):>10} | "
          f"{fmt_num(s.agg_redeem_value):>16} | {fmt_x(s.redeem_roi):>10}")
    a("")

    a("STEP 3  -  SETTLEMENT (parimutuel) IF THE MARKET RESOLVES AT THIS STAGE")
    a(_hr())
    a("  If a held outcome WINS, its holders split the whole USDT pot pro-rata.")
    a("  (Holdings in the other outcomes settle to zero.)")
    hdr3 = (f"  {'MCcap x':>7} | {'total pot':>16} | {'your win payout':>16} | "
            f"{'win ROI':>10}")
    a(hdr3)
    a("  " + _hr(92))
    for s in result.stages:
        a(f"  {s.multiple:>6g}x | {fmt_num(s.total_pot):>16} | "
          f"{fmt_num(s.settle_payout):>16} | {fmt_x(s.settle_roi):>10}")
    a("")
    a("=" * 96)
    if ft and not seeded:
        a("Curve & fee are 42's confirmed production values. ROI and ownership are exact")
        a("and scale-free; only the absolute USDT amounts depend on --full-mcap ($ scale).")
    elif ft and seeded:
        a("Curve & fee are 42's confirmed production values. With a house seed, ROI and")
        a("ownership depend on the $ scale (--full-mcap / --total-supply).")
    else:
        a("CUSTOM parameters (above) - not 42's production calibration. Dollar amounts,")
        a("and (with a house seed) ROI/ownership too, depend on the chosen scale.")
    a("=" * 96)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# input plumbing
# ---------------------------------------------------------------------------
def _build_curve(args):
    if args.curve == "affine":
        return AffineCurve(slope=args.slope, base=args.base)
    return PowerCurve(coefficient=args.coefficient, exponent=args.exponent)


def _parse_prior(spec, n):
    """Winner prior: 'uniform' -> None; 'skewed' -> geometric; or a comma list."""
    if spec is None or spec == "uniform":
        return None
    if spec == "skewed":
        w = [0.6 ** i for i in range(n)]
        return w
    parts = [float(p) for p in spec.replace(",", " ").split()]
    if len(parts) != n:
        raise SystemExit(f"--winner-prior list has {len(parts)} values, need {n}")
    return parts


def render_mc(mc: McResult) -> str:
    cfg = mc.config
    q = cfg.quote = getattr(cfg, "quote", "USDT")
    lines = []
    a = lines.append
    a("=" * 96)
    a(f"MONTE CARLO  -  {cfg.n_trials:,} trials  (random house seeds, uneven capital, "
      f"random winner)")
    a(_hr())
    a(f"  House seed/outcome  : Uniform({cfg.seed_min:g}, {cfg.seed_max:g}) USDT   "
      f"(MC_Sim default range)")
    a(f"  Added capital       : Lognormal, mean {fmt_money(cfg.mean_added_pool)} "
      f"(sigma {cfg.pool_sigma:g})")
    a(f"  Winner prior        : {'uniform' if cfg.prior is None else 'custom/skewed'}"
      f"   |  capital concentration {cfg.concentration:g}")
    a(f"  Avg total spend     : {fmt_money(mc.total_spend)}")
    a("")
    a("  SETTLEMENT RETURN  (payout / spend, multiple)")
    a("  " + _hr(92))
    a(f"    mean   : {mc.mean_settle:>7.2f}x        P(profit) : {mc.prob_profit*100:5.1f}%")
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
    p = argparse.ArgumentParser(
        description="42 / Event Rush early-buyer profitability simulator")
    p.add_argument("--outcomes", type=int, help="number of outcomes in the market")
    p.add_argument("--early-pct", type=float,
                   help="x: percent of each outcome's supply bought as an early buyer")
    p.add_argument("--curve", choices=["power", "affine"], default=DEFAULTS["curve"])
    p.add_argument("--exponent", type=float, default=DEFAULTS["exponent"])
    p.add_argument("--coefficient", type=float, default=DEFAULTS["coefficient"])
    p.add_argument("--slope", type=float, default=DEFAULTS["slope"])
    p.add_argument("--base", type=float, default=DEFAULTS["base"])
    p.add_argument("--full-mcap", type=float, default=DEFAULTS["full_mcap"],
                   help="reference market cap (USDT) per outcome; sets the $ scale")
    p.add_argument("--total-supply", type=float, default=DEFAULTS["total_supply"],
                   help="reference supply per outcome (overrides --full-mcap)")
    p.add_argument("--house-seed", type=float, default=DEFAULTS["house_seed"],
                   help="USDT the house seeds each outcome with")
    p.add_argument("--buy-fee", type=float, default=DEFAULTS["buy_fee"])
    p.add_argument("--sell-fee", type=float, default=DEFAULTS["sell_fee"])
    p.add_argument("--quote", default=DEFAULTS["quote"])
    p.add_argument("--multiples", type=str, default=None,
                   help="space/comma separated market-cap multiples, e.g. '1 2 10 100'")
    p.add_argument("--chart", type=str, default=None,
                   help="write an SVG chart (ownership + ROI vs growth) to this path")
    p.add_argument("--monte-carlo", action="store_true",
                   help="run the Monte Carlo (random seeds, uneven capital, random winner)")
    p.add_argument("--mc-trials", type=int, default=20_000)
    p.add_argument("--mc-mean-pool", type=float, default=None,
                   help="expected total later capital across all outcomes "
                        "(default: full-mcap x outcomes)")
    p.add_argument("--pool-sigma", type=float, default=0.6)
    p.add_argument("--concentration", type=float, default=8.0,
                   help="Dirichlet sharpness for capital allocation (higher = closer to prior)")
    p.add_argument("--seed-min", type=float, default=0.10)
    p.add_argument("--seed-max", type=float, default=10.0)
    p.add_argument("--winner-prior", type=str, default="uniform",
                   help="'uniform', 'skewed', or a comma list of length=outcomes")
    p.add_argument("--mc-seed", type=int, default=0)
    p.add_argument("-y", "--yes", action="store_true",
                   help="non-interactive: use flags/defaults without prompting")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])

    interactive = not args.yes and args.outcomes is None and args.early_pct is None
    if interactive:
        print("42 / Event Rush early-buyer simulator - press Enter to accept defaults.\n")
        args.outcomes = _prompt("Number of outcomes in the market", 4, int)
        args.early_pct = _prompt("Early buy: % of each outcome's supply", 1.0, float)
        args.full_mcap = _prompt("Reference market cap per outcome (USDT)",
                                 args.full_mcap, float)
        args.house_seed = _prompt("House seed per outcome (USDT, 0 = none)",
                                  args.house_seed, float)
        mraw = input(f"Market-cap multiples "
                     f"[{' '.join(str(m) for m in DEFAULT_MULTIPLES)}]: ").strip()
        args.multiples = mraw if mraw else None

    if args.outcomes is None:
        args.outcomes = 4
    if args.early_pct is None:
        args.early_pct = 1.0

    curve = _build_curve(args)
    total_supply = (args.total_supply if args.total_supply
                    else curve.supply_for_reserve(args.full_mcap))

    multiples = (_parse_multiples(args.multiples)
                 if args.multiples else DEFAULT_MULTIPLES)

    config = SimConfig(
        num_outcomes=args.outcomes,
        early_pct=args.early_pct,
        curve=curve,
        total_supply=total_supply,
        buy_fee=args.buy_fee,
        sell_fee=args.sell_fee,
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
            mean_added_pool=(args.mc_mean_pool if args.mc_mean_pool
                             else curve.reserve(total_supply) * args.outcomes),
            pool_sigma=args.pool_sigma,
            concentration=args.concentration,
            n_trials=args.mc_trials,
            seed=args.mc_seed,
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
