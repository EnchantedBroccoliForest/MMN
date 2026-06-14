"""Live-market buyer analyzer for 42 / Event Rush.

Given the CURRENT state of a real market (from ft_api.Market) and a buyer plan
(budget / per-outcome budget / target ownership), compute the practical numbers
a buyer cares about:

  * upfront spend, protocol fee, gas
  * tokens received and % ownership per outcome (minting from the CURRENT supply)
  * post-buy market cap per outcome and the new total pot
  * settlement payout and ROI if each outcome wins (parimutuel)
  * break-even total pot per outcome
  * expected ROI under a winner prior
  * an APPROXIMATE exit/redeem value (see fees.py caveats)

Buyers enter at the current curve state (using each outcome's ``minted_quantity``
as the starting supply), NOT "the first x% of supply" — that legacy framing lives
in the offline ``simulator`` module.

The curve used to convert spend -> tokens is 42's power curve (PowerCurve.ft()):
p(x)=x^(3/4)/2,000,000, with market cap = cumulative staked = reserve(x). The API
market cap is treated as authoritative and the buyer's net spend is added to it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from .curves import BondingCurve, PowerCurve
from .fees import FeeModel
from .ft_api import Market, Outcome


@dataclass
class BuyerPlan:
    budget: Optional[float] = None              # total collateral across all outcomes
    per_outcome_budget: Optional[float] = None  # fixed spend per outcome
    target_ownership_pct: Optional[float] = None
    allocation: str = "equal"                   # equal | custom
    custom_weights: Optional[List[float]] = None

    def __post_init__(self):
        if self.allocation not in ("equal", "custom"):
            raise ValueError("allocation must be 'equal' or 'custom'")
        provided = [x is not None for x in
                    (self.budget, self.per_outcome_budget, self.target_ownership_pct)]
        if sum(provided) != 1:
            raise ValueError("provide exactly one of budget / per_outcome_budget / "
                             "target_ownership_pct")
        if self.target_ownership_pct is not None and not (0 < self.target_ownership_pct < 100):
            raise ValueError("target_ownership_pct must be in (0, 100)")


@dataclass
class OutcomeAnalysis:
    name: str
    token_id: Optional[str]
    start_supply: float            # x0 (from API mintedQuantity, or derived)
    start_market_cap: float        # from API, or curve.reserve(x0)
    spend_gross: float
    fee: float
    net_to_curve: float
    tokens: float
    ownership_pct: float
    post_market_cap: float
    post_supply: float
    payout_if_win: float           # settlement payout if THIS outcome wins
    roi_if_win: float
    breakeven_pot: float           # total pot needed so a win just breaks even
    redeem_value_approx: float     # exit-now value (APPROXIMATE)
    supply_derived: bool = False   # start_supply came from market cap, not mintedQuantity


@dataclass
class LiveResult:
    market: Market
    curve: BondingCurve
    fee_model: FeeModel
    plan: BuyerPlan
    prior: List[float]
    prior_is_default: bool
    added_capital: float
    outcomes: List[OutcomeAnalysis]
    total_spend: float
    total_fee: float
    gas: float
    total_invested: float          # spend + gas
    pot_pre: float
    pot_post: float
    expected_payout: float
    expected_roi: float
    redeem_value_approx: float     # aggregate exit-now
    redeem_roi_approx: float
    warnings: List[str] = field(default_factory=list)


def _normalize_prior(prior: Optional[List[float]], n: int):
    if prior is None:
        return [1.0 / n] * n, True
    if len(prior) != n:
        raise ValueError(f"prior has {len(prior)} weights but market has {n} outcomes")
    if any(p < 0 for p in prior) or sum(prior) <= 0:
        raise ValueError("prior weights must be non-negative and sum to > 0")
    total = float(sum(prior))
    return [p / total for p in prior], False


def _start_supply(curve: BondingCurve, o: Outcome):
    """Current supply x0; prefer mintedQuantity, fall back to deriving from cap."""
    if o.minted_quantity and o.minted_quantity > 0:
        return o.minted_quantity, False
    if o.market_cap and o.market_cap > 0:
        return curve.supply_for_reserve(o.market_cap), True
    return 0.0, False


def _gross_spends(plan: BuyerPlan, n: int, start_supplies, curve, fee: FeeModel,
                  warnings: List[str]) -> List[float]:
    if plan.target_ownership_pct is not None:
        frac = plan.target_ownership_pct / 100.0
        spends = []
        for x0 in start_supplies:
            if x0 <= 0:
                warnings.append("An outcome has zero supply; target-ownership is "
                                "undefined there (any buy = ~100%); spent 0.")
                spends.append(0.0)
                continue
            # ownership = tokens/(x0+tokens) = frac  ->  tokens = frac/(1-frac) * x0
            tokens = frac / (1.0 - frac) * x0
            net = curve.cost(x0, x0 + tokens)
            spends.append(net / (1.0 - fee.protocol_fee))
        return spends
    if plan.per_outcome_budget is not None:
        return [plan.per_outcome_budget] * n
    # budget-based
    if plan.allocation == "custom":
        w = plan.custom_weights or []
        if len(w) != n:
            raise ValueError(f"custom allocation needs {n} weights, got {len(w)}")
        if any(x < 0 for x in w) or sum(w) <= 0:
            raise ValueError("custom weights must be non-negative and sum to > 0")
        tot = float(sum(w))
        return [plan.budget * (x / tot) for x in w]
    return [plan.budget / n] * n


def analyze(market: Market, plan: BuyerPlan, fee_model: FeeModel,
            curve: Optional[BondingCurve] = None,
            prior: Optional[List[float]] = None,
            added_capital: float = 0.0) -> LiveResult:
    if market.num_outcomes == 0:
        raise ValueError("market has no outcomes")
    curve = curve or PowerCurve.ft()
    n = market.num_outcomes
    prior_norm, prior_default = _normalize_prior(prior, n)
    warnings: List[str] = []

    start_supplies, start_caps, supply_derived = [], [], []
    for o in market.outcomes:
        x0, derived = _start_supply(curve, o)
        start_supplies.append(x0)
        supply_derived.append(derived)
        cap0 = o.market_cap if (o.market_cap is not None) else curve.reserve(x0)
        start_caps.append(cap0)
    if any(supply_derived):
        warnings.append("Some outcomes lacked mintedQuantity; supply was derived "
                        "from market cap via the curve (approximate).")

    gross = _gross_spends(plan, n, start_supplies, curve, fee_model, warnings)

    tokens_list, nets, post_supplies, post_caps = [], [], [], []
    for i in range(n):
        net = fee_model.net_to_curve(gross[i])
        x0 = start_supplies[i]
        tok = curve.tokens_for_spend(x0, net) if net > 0 else 0.0
        tokens_list.append(tok)
        nets.append(net)
        post_supplies.append(x0 + tok)
        post_caps.append(start_caps[i] + net)

    total_spend = sum(gross)
    total_fee = sum(g - nt for g, nt in zip(gross, nets))
    gas = fee_model.gas_usd
    total_invested = total_spend + gas
    pot_pre = sum(start_caps)
    pot_post = sum(post_caps)

    # Optional later-capital scenario: distribute by prior. Ownership stays on
    # the supply basis (mint the added capital on the curve from the current
    # supply) while the pot stays on the API cap basis (caps + added capital).
    # This keeps ownership and pot internally consistent even when the API's
    # marketCap and mintedQuantity are not exactly curve-consistent.
    final_supplies = list(post_supplies)
    if added_capital > 0:
        for i in range(n):
            a_i = added_capital * prior_norm[i]
            if a_i > 0:
                final_supplies[i] = post_supplies[i] + curve.tokens_for_spend(
                    post_supplies[i], a_i)
    final_pot = pot_post + added_capital

    redeem_rate = fee_model.redeem_tax_rate()

    analyses: List[OutcomeAnalysis] = []
    expected_payout = 0.0
    redeem_total = 0.0
    for i, o in enumerate(market.outcomes):
        # ownership at settlement (after any added capital dilution)
        own_final = (tokens_list[i] / final_supplies[i]) if final_supplies[i] > 0 else 0.0
        payout = own_final * final_pot
        own_now = (tokens_list[i] / post_supplies[i]) if post_supplies[i] > 0 else 0.0
        # Break-even pot uses the SAME ownership basis as the settlement payout
        # (post-dilution when later capital is assumed), so the two line up in
        # the report. With added_capital == 0, own_final == own_now.
        breakeven_pot = (total_invested / own_final) if own_final > 0 else float("inf")
        # exit-now: redeem your tokens back down the curve, minus protocol fee + tax
        gross_redeem = curve.cost(start_supplies[i], post_supplies[i])
        redeem_val = gross_redeem * (1.0 - redeem_rate)
        redeem_total += redeem_val
        expected_payout += prior_norm[i] * payout
        analyses.append(OutcomeAnalysis(
            name=o.name, token_id=o.token_id,
            start_supply=start_supplies[i], start_market_cap=start_caps[i],
            spend_gross=gross[i], fee=gross[i] - nets[i], net_to_curve=nets[i],
            tokens=tokens_list[i], ownership_pct=own_now * 100.0,
            post_market_cap=post_caps[i], post_supply=post_supplies[i],
            payout_if_win=payout, roi_if_win=(payout / total_invested - 1.0)
            if total_invested > 0 else 0.0,
            breakeven_pot=breakeven_pot, redeem_value_approx=redeem_val,
            supply_derived=supply_derived[i],
        ))

    warnings.append(fee_model.redeem_warning())
    if prior_default:
        warnings.append("No winner prior supplied; using a UNIFORM prior for "
                        "expected ROI (label only — not a real probability).")

    return LiveResult(
        market=market, curve=curve, fee_model=fee_model, plan=plan,
        prior=prior_norm, prior_is_default=prior_default, added_capital=added_capital,
        outcomes=analyses, total_spend=total_spend, total_fee=total_fee, gas=gas,
        total_invested=total_invested, pot_pre=pot_pre, pot_post=pot_post,
        expected_payout=expected_payout,
        expected_roi=(expected_payout / total_invested - 1.0) if total_invested > 0 else 0.0,
        redeem_value_approx=redeem_total,
        redeem_roi_approx=(redeem_total / total_invested - 1.0) if total_invested > 0 else 0.0,
        warnings=warnings,
    )
