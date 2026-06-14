"""Command-line front-end for the 42 early-buyer profitability simulator.

Run interactively:        python -m mmn
Run non-interactively:    python -m mmn --outcomes 4 --early-pct 1 --yes

The bonding-curve constants below the BIG NOTICE are PLACEHOLDERS. Replace them
with 42's real on-chain parameters (USDT collateral) to get exact numbers.
"""

from __future__ import annotations

import argparse
import sys

from .curves import AffineCurve, PowerCurve
from .simulator import DEFAULT_MULTIPLES, SimConfig, SimResult, simulate

# ============================================================================
#  >>> PASTE 42'S REAL CURVE PARAMETERS HERE <<<
#  These defaults are PLACEHOLDERS chosen to give readable round numbers. They
#  are NOT 42's on-chain constants. The shape (power curve p(s)=k*s^n) matches
#  the docs' "power curve" wording; swap in the verified contract's values.
# ============================================================================
DEFAULTS = {
    "curve": "power",            # "power" -> p(s)=k*s^n ; "affine" -> p(s)=m*s+b
    "exponent": 1.0,             # n for the power curve
    "total_supply": 1_000_000_000.0,   # tokens minted across the full curve, per outcome
    "mcap_at_full": 100_000.0,   # spot market cap (USDT) when supply == total_supply
    "coefficient": None,         # k; if set, overrides mcap_at_full
    "slope": 1e-13,              # m for the affine curve
    "base": 0.0,                 # b for the affine curve
    "buy_fee": 0.0,              # e.g. 0.005 for 0.5%
    "sell_fee": 0.0,
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
    # small numbers: show enough significant digits
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
    q = quote = cfg.quote
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
    a(f"  Total supply / outcome    : {fmt_num(cfg.total_supply)} tokens")
    a(f"  Buy / sell fee            : {cfg.buy_fee*100:g}% / {cfg.sell_fee*100:g}%")
    a(f"  Collateral                : {quote}")
    a("")

    a("CONFIRMED FROM 42's CONTRACTS  (IFTMarketV2 / IFTCurve)")
    a(_hr())
    a("  - Collateral = USDT (BEP-20, 18 decimals)")
    a("  - One market holds every outcome as an ERC-6909 token id")
    a("  - Buy  = mintCollateralToExactOt   Sell = redeemExactOtToCollateral")
    a("  - Curve = Hanson Market-Scoring-Rule AMM: cost C(supply), price = C'(supply)")
    a("  - Trading fee skimmed to a treasury on every buy/sell")
    a("  - Settlement = parimutuel claim(): winners split the USDT pot pro-rata")
    a("")
    a("ASSUMED  (no on-chain constants available - edit DEFAULTS in mmn/cli.py)")
    a(_hr())
    a("  - Exact curve shape & constants: using power curve p(s)=k*s^n as a stand-in")
    a("  - Total supply per outcome, fee bps, and full-supply market cap")
    a("  The MACHINERY is exact; swap in real constants for 42-accurate figures.")
    a("")

    a("STEP 1-2  -  ENTRY COST")
    a(_hr())
    a(f"  Tokens bought per outcome : {fmt_num(result.tokens_per_outcome)}  "
      f"(= {cfg.early_pct:g}% of {fmt_num(cfg.total_supply)})")
    a(f"  Spend per outcome         : {fmt_money(result.spend_per_outcome, quote)}")
    a(f"  Outcomes bought           : {cfg.num_outcomes}")
    a(f"  >> TOTAL SPEND            : {fmt_money(result.total_spend, quote)}")
    a(f"  Entry price / token       : {fmt_money(result.entry_price, quote)}")
    a(f"  Entry market cap/outcome  : {fmt_money(result.entry_market_cap, quote)}")
    a("")

    a("STEP 3  -  PROFITABILITY AS MARKET CAP GROWS  (per single outcome held)")
    a(_hr())
    hdr = (f"  {'MCcap x':>7} | {'mkt cap':>14} | {'price':>12} | "
           f"{'your own %':>10} | {'spot value':>14} | {'redeem value':>14}")
    a(hdr)
    a("  " + _hr(92))
    for s in result.stages:
        a(f"  {s.multiple:>6g}x | {fmt_num(s.market_cap):>14} | {fmt_num(s.price):>12} | "
          f"{fmt_pct(s.ownership_pct):>10} | {fmt_num(s.spot_value):>14} | "
          f"{fmt_num(s.redeem_value):>14}")
    a("")
    a("  spot value  = tokens x current price (mark-to-market, ignores sell slippage)")
    a("  redeem value= USDT you actually get selling those tokens back into the curve")
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
    a("NOTE: curve constants are PLACEHOLDERS unless you pasted 42's real on-chain")
    a("values into mmn/cli.py (DEFAULTS) or passed them as flags. The MATH is exact;")
    a("only the constants need to be the real ones for the numbers to be 42-accurate.")
    a("=" * 96)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# input plumbing
# ---------------------------------------------------------------------------
def _build_curve(args):
    if args.curve == "affine":
        return AffineCurve(slope=args.slope, base=args.base)
    if args.coefficient is not None:
        return PowerCurve(coefficient=args.coefficient, exponent=args.exponent)
    return PowerCurve.from_full_mcap(
        total_supply=args.total_supply,
        mcap_at_full=args.mcap_at_full,
        exponent=args.exponent,
    )


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
    p.add_argument("--total-supply", type=float, default=DEFAULTS["total_supply"])
    p.add_argument("--mcap-at-full", type=float, default=DEFAULTS["mcap_at_full"])
    p.add_argument("--coefficient", type=float, default=DEFAULTS["coefficient"])
    p.add_argument("--slope", type=float, default=DEFAULTS["slope"])
    p.add_argument("--base", type=float, default=DEFAULTS["base"])
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
        args.curve = _prompt("Curve type (power/affine)", args.curve, str)
        if args.curve == "power":
            args.exponent = _prompt("  power-curve exponent n", args.exponent, float)
            args.total_supply = _prompt("  total supply per outcome",
                                        args.total_supply, float)
            args.mcap_at_full = _prompt("  market cap (USDT) at full supply",
                                        args.mcap_at_full, float)
        else:
            args.slope = _prompt("  affine slope m", args.slope, float)
            args.base = _prompt("  affine base b", args.base, float)
        args.buy_fee = _prompt("Buy fee fraction (0.005 = 0.5%)", args.buy_fee, float)
        args.sell_fee = _prompt("Sell fee fraction", args.sell_fee, float)
        mraw = input(f"Market-cap multiples "
                     f"[{' '.join(str(m) for m in DEFAULT_MULTIPLES)}]: ").strip()
        args.multiples = mraw if mraw else None

    if args.outcomes is None:
        args.outcomes = 4
    if args.early_pct is None:
        args.early_pct = 1.0

    multiples = (_parse_multiples(args.multiples)
                 if args.multiples else DEFAULT_MULTIPLES)

    config = SimConfig(
        num_outcomes=args.outcomes,
        early_pct=args.early_pct,
        curve=_build_curve(args),
        total_supply=args.total_supply,
        buy_fee=args.buy_fee,
        sell_fee=args.sell_fee,
        multiples=multiples,
        quote=args.quote,
    )
    result = simulate(config)
    print()
    print(render(result))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
