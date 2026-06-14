#!/usr/bin/env python3
"""Generate REPORT.md (a detailed buyer analytics report) from a market snapshot.

Runs the live analyzer across several buyer plans, a market-implied prior, an
added-capital scenario, and a calibrated Monte Carlo, then writes REPORT.md with
embedded SVG charts. All numbers are produced by the mmn package so the report is
reproducible:

    python examples/build_report.py            # uses examples/sample_market.json
    python examples/build_report.py path.json
"""

from __future__ import annotations

import datetime as _dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # repo root on path

from mmn.chart import mc_histogram_svg, ownership_and_roi_svg
from mmn.curves import PowerCurve
from mmn.fees import FeeModel
from mmn.ft_api import market_from_json
from mmn.live_simulator import BuyerPlan, analyze
from mmn.montecarlo import McConfig, run_montecarlo
from mmn.simulator import SimConfig, simulate

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "examples" / "sample_market.json"
GAS = 0.50
PROTOCOL_FEE = 0.008


def money(x):
    if x == float("inf"):
        return "n/a"
    return f"{x:,.2f}" if abs(x) >= 1 else f"{x:,.6g}"


def pct(x):
    return f"{x:,.3f}%"


def mult(roi):
    return f"{roi + 1:,.2f}x"


def fee_model():
    return FeeModel(protocol_fee=PROTOCOL_FEE, redeem_tax_mode="documented",
                    manual_redeem_tax=0.0, gas_usd=GAS)


def plan_section(title, note, market, plan, prior, added=0.0):
    r = analyze(market, plan, fee_model(), prior=prior, added_capital=added)
    L = [f"### {title}", "", note, "",
         f"- **Total upfront spend:** {money(r.total_spend)} USDT  "
         f"· **protocol fee:** {money(r.total_fee)} · **gas:** {money(r.gas)} "
         f"· **total invested:** **{money(r.total_invested)} USDT**",
         f"- **Pot after your buy:** {money(r.pot_post)} USDT"
         + (f" · **+later capital:** {money(r.pot_post + r.added_capital)} USDT" if added else ""),
         f"- **Expected ROI** (prior shown below): **{mult(r.expected_roi)}**"
         f" · **exit-now (approx):** {mult(r.redeem_roi_approx)}",
         "",
         "| Outcome | Spend | Tokens | Your % | Payout if win | ROI if win | Break-even pot |",
         "|---|--:|--:|--:|--:|--:|--:|"]
    for o in r.outcomes:
        L.append(f"| {o.name} | {money(o.spend_gross)} | {money(o.tokens)} | "
                 f"{pct(o.ownership_pct)} | {money(o.payout_if_win)} | "
                 f"{mult(o.roi_if_win)} | {money(o.breakeven_pot)} |")
    L.append("")
    return r, "\n".join(L)


def main():
    market = market_from_json(json.loads(SNAPSHOT.read_text()))
    pot = market.total_pot
    # Market-implied prior = each outcome's share of the current pot.
    implied = [(o.market_cap or 0.0) / pot for o in market.outcomes]
    names = [o.name for o in market.outcomes]

    out = []
    w = out.append
    w("# 42 / Event Rush — Buyer Analytics Report")
    w("")
    w(f"_Generated {_dt.date.today().isoformat()} by `examples/build_report.py` from "
      f"`{SNAPSHOT.relative_to(ROOT)}`._")
    w("")
    w("Provenance tags: **[API]** exact from the 42 API · **[curve]** exact curve "
      "math · **[est]** estimate · **[you]** your assumption.")
    w("")
    w("> ⚠️ This report is built from a **saved market snapshot** (the sandbox has no "
      "live API access). The curve (`p(x)=x^(3/4)/2,000,000`, verified vs `MC_Sim`) and "
      "the parimutuel settlement are exact; the **0.8% protocol fee is the documented "
      "value** and 42's **dynamic redemption tax is not modelled**, so exit/redeem "
      "figures are approximate.")
    w("")

    # -- Market summary -----------------------------------------------------
    w("## 1. Market summary  [API]")
    w("")
    w(f"- **Title:** {market.title}")
    w(f"- **Ref:** `{market.address or market.slug}`")
    w(f"- **Status:** {market.status} · **Collateral:** {market.collateral} · "
      f"**Outcomes:** {market.num_outcomes}")
    w(f"- **Current total pot:** **{money(pot)} {market.collateral}**")
    w("")
    w("## 2. Current outcomes  [API]")
    w("")
    w("Implied probability = outcome market cap ÷ total pot.")
    w("")
    w("| Outcome | Price | Market cap | Minted qty | Implied prob |")
    w("|---|--:|--:|--:|--:|")
    for o, p in zip(market.outcomes, implied):
        w(f"| {o.name} | {money(o.price)} | {money(o.market_cap)} | "
          f"{money(o.minted_quantity)} | {pct(p*100)} |")
    w("")

    # -- Buyer plans --------------------------------------------------------
    w("## 3. Buyer plans analysed  [curve / you]")
    w("")
    w("All plans use the documented **0.8% protocol fee** and **0.50 USDT gas**. "
      "Buys mint from each outcome's current supply. ‘Payout if win’ is parimutuel: "
      "`your ownership × total pot`.")
    w("")

    results = {}
    rA, sA = plan_section(
        "Plan A — 300 USDT, equal split, uniform prior",
        "Spread 300 USDT evenly across all outcomes; assume each is equally likely.",
        market, BuyerPlan(budget=300.0), prior=None)
    results["A"] = rA; w(sA)

    rB, sB = plan_section(
        "Plan B — 300 USDT, equal split, market-implied prior",
        "Same buy as A, but expected ROI uses the **market-implied** prior "
        f"({', '.join(f'{n} {pct(p*100)}' for n, p in zip(names, implied))}).",
        market, BuyerPlan(budget=300.0), prior=implied)
    results["B"] = rB; w(sB)

    rC, sC = plan_section(
        "Plan C — target 2% ownership in every outcome",
        "Buy until you hold 2% of each outcome; cost is driven by the curve and "
        "each outcome's current size.",
        market, BuyerPlan(target_ownership_pct=2.0), prior=implied)
    results["C"] = rC; w(sC)

    rD, sD = plan_section(
        "Plan D — 300 USDT, contrarian (weighted to the underdog)",
        f"Custom allocation 1:1:4 toward **{names[-1]}**, the lowest-priced outcome.",
        market, BuyerPlan(budget=300.0, allocation="custom", custom_weights=[1, 1, 4]),
        prior=implied)
    results["D"] = rD; w(sD)

    rE, sE = plan_section(
        "Plan E — 300 USDT equal, with +200,000 USDT later capital",
        "Same buy as B, but assume 200,000 USDT of later capital flows in (split by "
        "the implied prior) before resolution — diluting ownership and growing the pot.",
        market, BuyerPlan(budget=300.0), prior=implied, added=200_000.0)
    results["E"] = rE; w(sE)

    # -- Comparison ---------------------------------------------------------
    w("## 4. Plan comparison")
    w("")
    w("| Plan | Invested | Expected ROI | Payout if favourite wins | Payout if underdog wins |")
    w("|---|--:|--:|--:|--:|")
    fav, dog = 0, len(names) - 1
    for key in ("A", "B", "C", "D", "E"):
        r = results[key]
        w(f"| {key} | {money(r.total_invested)} | {mult(r.expected_roi)} | "
          f"{money(r.outcomes[fav].payout_if_win)} ({names[fav]}) | "
          f"{money(r.outcomes[dog].payout_if_win)} ({names[dog]}) |")
    w("")
    w("**Reading it:** spreading evenly (A/B) makes you hold the winner whatever "
      "happens, but you also fund the losers — expected ROI is below 1.0x once fees "
      "are paid, so profit needs the pot to **grow** after you enter. Concentrating on "
      "the cheap underdog (D) raises the upside if it wins and the downside if it "
      "doesn't. Later capital (E) dilutes your ownership but enlarges the pot.")
    w("")

    # -- Charts -------------------------------------------------------------
    # Calibrated Monte Carlo: 3 outcomes, market-implied prior, seeds spanning the
    # current outcome caps, later capital centred on the current pot.
    caps = sorted((o.market_cap or 0.0) for o in market.outcomes)
    mc = run_montecarlo(McConfig(
        num_outcomes=market.num_outcomes, early_pct=1.0, prior=implied,
        seed_min=caps[0], seed_max=caps[-1], mean_added_pool=pot,
        n_trials=20000, seed=42, quote=market.collateral))
    (ROOT / "examples" / "report_montecarlo.svg").write_text(mc_histogram_svg(mc))

    # Illustrative ownership/ROI vs growth (offline curve model).
    sim = simulate(SimConfig(num_outcomes=market.num_outcomes, early_pct=1.0,
                             curve=PowerCurve.ft(),
                             total_supply=PowerCurve.ft().supply_for_reserve(pot / 3),
                             multiples=(1, 2, 5, 10, 25, 100)))
    (ROOT / "examples" / "report_growth.svg").write_text(ownership_and_roi_svg(sim))

    w("## 5. Distribution & growth charts")
    w("")
    w("**Calibrated Monte Carlo** — settlement return over 20,000 trials with random "
      "house seeds (spanning current outcome caps), uneven later capital averaging the "
      "current pot, and a random winner drawn from the implied prior:")
    w("")
    w("![Monte Carlo settlement return](examples/report_montecarlo.svg)")
    w("")
    w(f"- Mean **{mult(mc.mean_settle - 1)}**, median **{mult(mc.median_settle - 1)}**, "
      f"5th–95th pct **{mult(mc.p05_settle - 1)} – {mult(mc.p95_settle - 1)}**, "
      f"P(profit) **{mc.prob_profit*100:.1f}%**.")
    w("")
    w("**Ownership & return vs market-cap growth** (illustrative, offline curve model): "
      "your % ownership decays as growthᐟ and your return multiple rises with it.")
    w("")
    w("![Ownership and ROI vs growth](examples/report_growth.svg)")
    w("")

    # -- Exit / caveats -----------------------------------------------------
    w("## 6. Exit / redeem  [est — APPROXIMATE]")
    w("")
    w(f"Selling back into the curve immediately recovers roughly the net you put in "
      f"minus fees. For Plan B that is about **{money(rB.redeem_value_approx)} USDT** "
      f"({mult(rB.redeem_roi_approx)} of invested).")
    w("")
    w("> **Warning:** 42 applies a **dynamic redemption tax/spread** that is **not "
      "implemented** here. Real exit value is lower than shown. Use "
      "`--redeem-tax-mode manual --manual-redeem-tax PCT` to stress-test your own "
      "estimate.")
    w("")

    # -- Assumptions --------------------------------------------------------
    w("## 7. Assumptions & warnings")
    w("")
    w("- **Curve [curve]:** 42 power curve `p(x)=x^(3/4)/2,000,000`; market cap = "
      "cumulative staked = reserve. Verified against `MC_Sim/parimutuel_sim/market.py`.")
    w("- **Settlement [curve]:** parimutuel — winners split the whole pot pro-rata "
      "(`payout_per_unit = pot / winning_supply`).")
    w("- **Fee [est]:** 0.8% protocol fee (documented; re-verify against live docs).")
    w("- **Redemption tax [est]:** dynamic tax NOT modelled → exit values approximate.")
    w("- **Prior [you]:** ‘market-implied’ = current pot shares; not a guaranteed "
      "probability. Uniform where stated.")
    w("- **Source [API-shaped]:** a saved snapshot, not a live API pull.")
    w("")
    w("## 8. Reproduce")
    w("")
    w("```bash")
    w("python examples/build_report.py            # regenerate this report")
    w("python -m mmn --market-json examples/sample_market.json --budget 300 \\")
    w("    --winner-prior 0.696,0.248,0.056 --gas-usd 0.5   # one plan, live-style CLI")
    w("```")
    w("")

    (ROOT / "REPORT.md").write_text("\n".join(out) + "\n")
    print(f"Wrote {ROOT/'REPORT.md'} and 2 chart SVGs.")


if __name__ == "__main__":
    main()
