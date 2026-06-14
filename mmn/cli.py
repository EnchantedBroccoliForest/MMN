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
import sys

from .curves import FT_ALPHA, FT_PRICE_SCALE, AffineCurve, PowerCurve
from .simulator import DEFAULT_MULTIPLES, SimConfig, SimResult, simulate

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
def render(result: SimResult) -> str:
    cfg = result.config
    quote = cfg.quote
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

    a("CONFIRMED FROM 42  (contracts IFTMarketV2/IFTCurve + MC_Sim/parimutuel_sim)")
    a(_hr())
    a("  - Collateral = USDT (BEP-20, 18 decimals); one market = many ERC-6909 ids")
    a("  - Curve: marginal price  p(x) = x^(3/4) / 2,000,000")
    a("  - Market cap = cumulative USDT staked = (4/7) * x^(7/4) / 2,000,000")
    a("  - Fee = 0.2% per side to treasury")
    a("  - Settlement = parimutuel: payout/unit = total_pool / winning_supply,")
    a("    i.e. winners split the whole USDT pot pro-rata")
    a("")
    a("ASSUMED  (only the $ scale - ROI and ownership do NOT depend on it)")
    a(_hr())
    a(f"  - Reference market cap per outcome sets the supply scale")
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
    a("Curve & fee are 42's confirmed production values. ROI and ownership are exact and")
    a("scale-free; only the absolute USDT amounts depend on --full-mcap (the $ scale).")
    a("=" * 96)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# input plumbing
# ---------------------------------------------------------------------------
def _build_curve(args):
    if args.curve == "affine":
        return AffineCurve(slope=args.slope, base=args.base)
    return PowerCurve(coefficient=args.coefficient, exponent=args.exponent)


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
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
