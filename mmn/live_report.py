"""Buyer-facing text report for the live-market analyzer.

Every number is tagged with its provenance so a buyer knows what to trust:
  [API]   exact, straight from the 42 REST API
  [curve] exact under 42's power-curve math, given the API state
  [est]   estimate (depends on assumptions, e.g. redeem with dynamic tax)
  [you]   a user-provided assumption (budget, prior, gas, taxes, scenarios)
"""

from __future__ import annotations

from typing import List

from .ft_api import Market
from .live_simulator import LiveResult


def _money(x, q="USDT"):
    if x is None:
        return "n/a"
    if x == float("inf"):
        return "inf"
    return f"{x:,.2f} {q}" if abs(x) >= 1 else f"{x:,.6g} {q}"


def _num(x):
    if x is None:
        return "n/a"
    ax = abs(x)
    if ax >= 1000:
        return f"{x:,.0f}"
    if ax >= 1:
        return f"{x:,.2f}"
    return f"{x:.4g}"


def _pct(x):
    return "n/a" if x is None else f"{x:,.3f}%"


def _x(roi):
    return f"{roi + 1.0:,.2f}x"


def _hr(w=96):
    return "-" * w


def render_market_list(markets: List[Market], status: str) -> str:
    out = [f"42 / Event Rush markets (status={status}) - {len(markets)} shown", _hr()]
    if not markets:
        out.append("  (no markets returned)")
        return "\n".join(out)
    out.append(f"  {'#':>2}  {'outcomes':>8}  {'pot (USDT)':>14}  status      ref / title")
    out.append("  " + _hr(92))
    for i, m in enumerate(markets):
        ref = m.address or m.slug or "-"
        out.append(f"  {i+1:>2}  {m.num_outcomes:>8}  {_num(m.total_pot):>14}  "
                   f"{str(m.status or '-'):<10}  {ref}  {m.title[:40]}")
    out.append("")
    out.append("Use:  python -m mmn --market <ref> --budget <USDT>   for a buyer analysis")
    return "\n".join(out)


def render_live(r: LiveResult) -> str:
    m = r.market
    q = m.collateral or "USDT"
    L = []
    a = L.append
    a("=" * 96)
    a("42 / EVENT RUSH  -  LIVE BUYER ANALYSIS")
    a("=" * 96)
    a("Provenance tags:  [API] from 42 API   [curve] curve math   [est] estimate   "
      "[you] your assumption")
    a("")

    # -- Market summary -----------------------------------------------------
    a("MARKET SUMMARY")
    a(_hr())
    a(f"  Title         : {m.title}                       [API]")
    a(f"  Ref           : {m.address or m.slug or '-'}    [API]")
    a(f"  Status        : {m.status or '-'}               [API]")
    a(f"  Collateral    : {q}                              [API]")
    a(f"  Outcomes      : {m.num_outcomes}                 [API]")
    a(f"  Current pot   : {_money(r.pot_pre, q)}           [API]")
    a("")

    # -- Current outcomes ---------------------------------------------------
    a("CURRENT OUTCOMES  [API]")
    a(_hr())
    a(f"  {'#':>2}  {'outcome':<22} {'price':>12} {'market cap':>14} "
      f"{'minted qty':>14}")
    a("  " + _hr(92))
    for i, (o, oa) in enumerate(zip(m.outcomes, r.outcomes)):
        a(f"  {i+1:>2}  {oa.name[:22]:<22} {_num(o.price):>12} "
          f"{_num(o.market_cap):>14} {_num(o.minted_quantity):>14}")
    a("")

    # -- Buyer plan ---------------------------------------------------------
    a("BUYER PLAN  [you]")
    a(_hr())
    p = r.plan
    if p.target_ownership_pct is not None:
        a(f"  Goal          : reach {p.target_ownership_pct:g}% ownership per outcome")
    elif p.per_outcome_budget is not None:
        a(f"  Goal          : spend {_money(p.per_outcome_budget, q)} per outcome")
    else:
        a(f"  Goal          : spend {_money(p.budget, q)} total, allocation={p.allocation}")
    if r.added_capital:
        a(f"  Later capital : {_money(r.added_capital, q)} assumed to flow in before "
          f"resolution (split by prior)  [you]")
    a("")

    # -- Expenses -----------------------------------------------------------
    a("EXPENSES")
    a(_hr())
    a(f"  Total upfront spend : {_money(r.total_spend, q):>20}   [you/curve]")
    a(f"  Protocol fee        : {_money(r.total_fee, q):>20}   [est: "
      f"{r.fee_model.protocol_fee*100:g}% documented]")
    a(f"  Gas                 : {_money(r.gas, q):>20}   [you]")
    a(f"  TOTAL INVESTED      : {_money(r.total_invested, q):>20}")
    a("")

    # -- Ownership after buy ------------------------------------------------
    a("OWNERSHIP AFTER BUY  [curve]")
    a(_hr())
    a(f"  {'outcome':<22} {'spend':>12} {'tokens':>14} {'your %':>10} "
      f"{'post mkt cap':>14}")
    a("  " + _hr(92))
    for oa in r.outcomes:
        a(f"  {oa.name[:22]:<22} {_num(oa.spend_gross):>12} {_num(oa.tokens):>14} "
          f"{_pct(oa.ownership_pct):>10} {_num(oa.post_market_cap):>14}")
    a("")

    # -- Settlement payout by winning outcome -------------------------------
    a("SETTLEMENT PAYOUT BY WINNING OUTCOME  [curve]")
    a(_hr())
    a("  If the named outcome wins, you collect ownership x total pot "
      f"(pot now {_money(r.pot_post, q)}"
      + (f", {_money(r.pot_post + r.added_capital, q)} after later capital" if r.added_capital else "")
      + ").")
    a(f"  {'outcome':<22} {'payout':>16} {'ROI':>10} {'break-even pot':>18}")
    a("  " + _hr(92))
    for oa in r.outcomes:
        a(f"  {oa.name[:22]:<22} {_money(oa.payout_if_win, q):>16} "
          f"{_x(oa.roi_if_win):>10} {_money(oa.breakeven_pot, q):>18}")
    a("")

    # -- Expected profitability ---------------------------------------------
    a("EXPECTED PROFITABILITY")
    a(_hr())
    tag = "[you: prior]" if not r.prior_is_default else "[assumption: UNIFORM prior]"
    a(f"  Winner prior        : {', '.join(f'{x*100:.1f}%' for x in r.prior)}  {tag}")
    a(f"  Expected payout     : {_money(r.expected_payout, q)}   [est]")
    a(f"  Expected ROI        : {_x(r.expected_roi)}   [est]")
    a("")

    # -- Exit / redeem caveats ----------------------------------------------
    a("EXIT / REDEEM (SELL BACK NOW)  [est - APPROXIMATE]")
    a(_hr())
    a(f"  Approx. exit value  : {_money(r.redeem_value_approx, q)}  ({_x(r.redeem_roi_approx)})")
    a(f"  Redeem tax mode     : {r.fee_model.redeem_tax_mode}  "
      f"(rate applied {r.fee_model.redeem_tax_rate()*100:g}%)   [you]")
    a("  WARNING: 42's exact dynamic redemption tax is NOT implemented here; the exit")
    a("           value above is an approximation only. Do not treat it as exact.")
    a("")

    # -- Assumptions and warnings -------------------------------------------
    a("ASSUMPTIONS & WARNINGS")
    a(_hr())
    a(f"  - Curve: 42 power curve p(x)=x^(3/4)/2,000,000 (market cap = staked) [curve]")
    a(f"  - Protocol fee {r.fee_model.protocol_fee*100:g}% is the DOCUMENTED value; "
      "re-verify against live docs.")
    for w in r.warnings:
        a(f"  - {w}")
    a("=" * 96)
    return "\n".join(L)
