"""Command-line front-end for the MMN 42 / Event Rush buyer toolkit.

Two modes:

  LIVE analyzer (primary) - uses real 42 market data from the REST API:
      python -m mmn --list-live
      python -m mmn --market <address-or-slug> --budget 100
      python -m mmn --market-json snapshot.json --budget 100   (offline snapshot)

  OFFLINE / HYPOTHETICAL simulator (legacy "buy first x% of supply" model):
      python -m mmn --offline --outcomes 4 --early-pct 1 --yes

The offline model is explicitly a what-if; only the LIVE analyzer reflects a
real market's current state. Fees default to 42's DOCUMENTED protocol fee
(~0.8%), not the earlier (incorrect) 0.2%. The dynamic redemption tax is not
reproduced exactly, so redeem figures are flagged approximate.
"""

from __future__ import annotations

import argparse
import json
import math
import sys

from .curves import FT_ALPHA, FT_PRICE_SCALE, AffineCurve, PowerCurve
from .simulator import DEFAULT_MULTIPLES, SimConfig, SimResult, simulate
from .montecarlo import McConfig, McResult, run_montecarlo
from .chart import mc_histogram_svg, ownership_and_roi_svg
from .fees import DOCUMENTED_PROTOCOL_FEE, REDEEM_TAX_MODES, FeeModel
from .ft_api import DEFAULT_BASE_URL, FtApiError, FtClient, market_from_json
from .live_simulator import BuyerPlan, analyze
from .live_report import render_live, render_market_list

# Offline/hypothetical model defaults. The curve is 42's verified power curve;
# the fee here is the DOCUMENTED protocol fee (configurable), NOT a confirmed
# 0.2% (that earlier claim was wrong).
DEFAULTS = {
    "curve": "power",
    "exponent": FT_ALPHA,                 # 0.75
    "coefficient": 1.0 / FT_PRICE_SCALE,  # 5e-7
    "slope": 1e-13,                       # affine alt only
    "base": 0.0,
    "full_mcap": 100_000.0,               # reference market cap per outcome (sets $ scale)
    "total_supply": None,                 # derived from full_mcap unless set explicitly
    "house_seed": 0.0,
    "buy_fee": DOCUMENTED_PROTOCOL_FEE,   # 0.8% documented protocol fee (assumption)
    "sell_fee": DOCUMENTED_PROTOCOL_FEE,
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
    """True iff the run uses 42's verified production curve and USDT collateral.

    Fees are NOT part of this check: 42's exact fee/redemption model is not
    reproduced offline, so the report never asserts a specific fee as confirmed.
    """
    c = cfg.curve
    return (isinstance(c, PowerCurve)
            and cfg.quote == "USDT"
            and math.isclose(c.k, 1.0 / FT_PRICE_SCALE, rel_tol=1e-9)
            and math.isclose(c.n, FT_ALPHA, rel_tol=1e-9))


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
    a("42 / EVENT RUSH  -  OFFLINE / HYPOTHETICAL EARLY-BUYER MODEL")
    a("=" * 96)
    a("  This is a WHAT-IF model on invented inputs, NOT a live market. For real")
    a("  market numbers use:  python -m mmn --market <ref> --budget <USDT>")
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
        a("VERIFIED CURVE  (42 power curve, from MC_Sim/parimutuel_sim)")
        a(_hr())
        a("  - Collateral = USDT (BEP-20, 18 decimals); one market = many ERC-6909 ids")
        a("  - Curve: marginal price  p(x) = x^(3/4) / 2,000,000")
        a("  - Market cap = cumulative USDT staked = (4/7) * x^(7/4) / 2,000,000")
        a("  - Settlement = parimutuel: payout/unit = total_pool / winning_supply")
        a(f"  - Fee modelled here: {cfg.buy_fee*100:g}% buy / {cfg.sell_fee*100:g}% sell "
          "(ASSUMPTION; 42 docs describe ~0.8% protocol fee + a dynamic redemption")
        a("    tax that is NOT reproduced here).")
    else:
        a("CUSTOM CURVE  (NOT 42's verified production curve)")
        a(_hr())
        a(f"  - Curve: marginal price  {_curve_formula(cfg.curve)}")
        a("  - Market cap = cumulative collateral staked (integral of price)")
        a(f"  - Fee modelled here: {cfg.buy_fee*100:g}% buy / {cfg.sell_fee*100:g}% sell "
          "(your assumption)")
        a("  - Settlement = parimutuel: winners split the pot pro-rata")
        a("  These are YOUR parameters; 42's verified curve is p(x)=x^(3/4)/2,000,000.")
    a("")
    a("ASSUMPTIONS / SCALE")
    a(_hr())
    if seeded:
        a("  - A house seed is set: it is an ABSOLUTE amount, so ROI and ownership")
        a("    DO depend on the $ scale here (they are scale-free only when seed = 0).")
    else:
        a("  - ROI and ownership are scale-free: they do NOT depend on the $ scale")
        a(f"    (reference market cap / supply); only the {quote} amounts scale with it.")
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
      f"(cumulative {quote} staked)")
    a("")

    a("STEP 3  -  PROFITABILITY AS MARKET CAP GROWS  (per single outcome held)")
    a(_hr())
    a(f"  market cap = cumulative {quote} staked in that outcome")
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
    a(f"  redeem value= {quote} you actually get selling those units back into the curve")
    a("")

    a(f"STEP 3  -  AGGREGATE P&L  (all {cfg.num_outcomes} outcomes; spend "
      f"{fmt_money(result.total_spend, quote)})")
    a(_hr())
    hdr2 = (f"  {'MCcap x':>7} | {'agg spot':>16} | "
            f"{'agg redeem':>16} | {'redeem ROI':>10}")
    a(hdr2)
    a("  " + _hr(79))
    for s in result.stages:
        a(f"  {s.multiple:>6g}x | {fmt_num(s.agg_spot_value):>16} | "
          f"{fmt_num(s.agg_redeem_value):>16} | {fmt_x(s.redeem_roi):>10}")
    a("")

    a("STEP 3  -  SETTLEMENT (parimutuel) IF THE MARKET RESOLVES AT THIS STAGE")
    a(_hr())
    a(f"  If a held outcome WINS, its holders split the whole {quote} pot pro-rata.")
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
    a("OFFLINE / HYPOTHETICAL model on invented inputs - use --market for live data.")
    if ft and not seeded:
        a("Curve is 42's verified power curve; fee is an assumption. ROI/ownership are")
        a("scale-free; only the absolute amounts depend on --full-mcap ($ scale).")
    elif ft and seeded:
        a("Curve is 42's verified power curve; fee is an assumption. With a house seed,")
        a("ROI and ownership depend on the $ scale (--full-mcap / --total-supply).")
    else:
        a("CUSTOM curve/params (above) - not 42's verified curve. Dollar amounts, and")
        a("(with a house seed) ROI/ownership too, depend on the chosen scale.")
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
    quote = cfg.quote
    lines = []
    a = lines.append
    a("=" * 96)
    a(f"MONTE CARLO  -  {cfg.n_trials:,} trials  (random house seeds, uneven capital, "
      f"random winner)")
    a(_hr())
    a(f"  House seed/outcome  : Uniform({cfg.seed_min:g}, {cfg.seed_max:g}) {quote}   "
      f"(MC_Sim default range)")
    a(f"  Added capital       : Lognormal, mean {fmt_money(cfg.mean_added_pool, quote)} "
      f"(sigma {cfg.pool_sigma:g})")
    a(f"  Winner prior        : {'uniform' if cfg.prior is None else 'custom/skewed'}"
      f"   |  capital concentration {cfg.concentration:g}")
    a(f"  Avg total spend     : {fmt_money(mc.total_spend, quote)}")
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

    # -- live-market analyzer (primary mode) --------------------------------
    live = p.add_argument_group("live market analyzer")
    live.add_argument("--offline", action="store_true",
                      help="run the offline/hypothetical model instead of live data")
    live.add_argument("--list-live", action="store_true",
                      help="list markets from the 42 API and exit")
    live.add_argument("--market", type=str, default=None,
                      help="analyze a market by address or slug (uses the 42 API)")
    live.add_argument("--market-json", type=str, default=None,
                      help="analyze a market from a saved JSON snapshot (offline)")
    live.add_argument("--status", choices=["live", "resolved", "all"], default="live")
    live.add_argument("--limit", type=int, default=20, help="--list-live row limit")
    live.add_argument("--api-base", type=str, default=DEFAULT_BASE_URL)
    live.add_argument("--budget", type=float, default=None,
                      help="total collateral to spend across all outcomes")
    live.add_argument("--per-outcome-budget", type=float, default=None,
                      help="fixed collateral to spend on each outcome")
    live.add_argument("--target-ownership", type=float, default=None,
                      help="buy until you own this %% of each outcome")
    live.add_argument("--allocation", choices=["equal", "custom"], default="equal")
    live.add_argument("--weights", type=str, default=None,
                      help="custom allocation weights (comma list, len = outcomes)")
    live.add_argument("--protocol-fee", type=float, default=DOCUMENTED_PROTOCOL_FEE * 100,
                      help="protocol fee PERCENT (default %(default)s = documented 0.8%%)")
    live.add_argument("--gas-usd", type=float, default=0.0)
    live.add_argument("--redeem-tax-mode", choices=list(REDEEM_TAX_MODES),
                      default="documented")
    live.add_argument("--manual-redeem-tax", type=float, default=0.0,
                      help="redeem tax PERCENT for manual/documented modes")
    live.add_argument("--added-capital", type=float, default=0.0,
                      help="later capital (collateral) assumed to flow in before resolution")
    return p.parse_args(argv)


def _parse_weights(text):
    return [float(x) for x in text.replace(",", " ").split()]


def _client(args):
    return FtClient(base_url=args.api_base)


def _load_market(args):
    if args.market_json:
        with open(args.market_json) as fh:
            return market_from_json(json.load(fh))
    return _client(args).get_market(args.market)


def _fee_model(args):
    return FeeModel(
        protocol_fee=args.protocol_fee / 100.0,
        redeem_tax_mode=args.redeem_tax_mode,
        manual_redeem_tax=args.manual_redeem_tax / 100.0,
        gas_usd=args.gas_usd,
    )


def _build_plan(args):
    return BuyerPlan(
        budget=args.budget,
        per_outcome_budget=args.per_outcome_budget,
        target_ownership_pct=args.target_ownership,
        allocation=args.allocation,
        custom_weights=_parse_weights(args.weights) if args.weights else None,
    )


_USAGE = """\
MMN - 42 / Event Rush buyer toolkit. Pick a mode:

  Live market data (primary):
    python -m mmn --list-live
    python -m mmn --market <address-or-slug> --budget 100
    python -m mmn --market <ref> --target-ownership 2 --winner-prior skewed
    python -m mmn --market-json snapshot.json --budget 100   (offline snapshot)

  Offline / hypothetical model (legacy 'buy first x% of supply'):
    python -m mmn --offline --outcomes 4 --early-pct 1 --yes

Run with -h for all flags."""


def main(argv=None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])

    if args.list_live:
        try:
            markets = _client(args).list_markets(status=args.status, limit=args.limit)
        except FtApiError as e:
            print(f"Could not list markets: {e}", file=sys.stderr)
            return 2
        print(render_market_list(markets, args.status))
        return 0

    if args.market or args.market_json:
        try:
            market = _load_market(args)
        except FtApiError as e:
            print(f"Could not load market: {e}", file=sys.stderr)
            return 2
        except (OSError, ValueError) as e:
            print(f"Could not read market snapshot: {e}", file=sys.stderr)
            return 2
        if (args.budget is None and args.per_outcome_budget is None
                and args.target_ownership is None):
            print("Specify a buyer plan: --budget, --per-outcome-budget, or "
                  "--target-ownership.", file=sys.stderr)
            return 2
        try:
            result = analyze(
                market, _build_plan(args), _fee_model(args),
                prior=_parse_prior(args.winner_prior, market.num_outcomes),
                added_capital=args.added_capital,
            )
        except ValueError as e:
            print(f"Invalid analysis input: {e}", file=sys.stderr)
            return 2
        print(render_live(result))
        return 0

    if not args.offline:
        print(_USAGE)
        return 0

    return _run_offline(args)


def _run_offline(args) -> int:
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
