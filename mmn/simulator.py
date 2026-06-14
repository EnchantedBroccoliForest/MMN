"""Early-buyer profitability simulation over a 42 / Event Rush market.

The user's three questions, mapped to this module:

  1. How many outcomes?                      -> SimConfig.num_outcomes
  2. Buy x% of the EARLIEST part of every    -> SimConfig.early_pct  (first x% of
     outcome's curve. Total spend?              each outcome's total token supply)
  3. As market cap grows, what is the         -> stages at market-cap MULTIPLES of
     profitability and % ownership?             the user's entry market cap

Two ways to value a held position are reported, because on a bonding curve they
differ:

  * spot (mark-to-market): tokens_held * current_price. Optimistic - it ignores
    that selling walks the price back down the curve.
  * redeem (realisable):   proceeds from actually selling the held tokens back
    into the curve. This is what you could really cash out pre-resolution.

A third lens is settlement: if the market resolved at that growth stage, the
winning outcome's holders split the entire USDT pot (collateral from all
outcomes). The user holds the same fraction of every outcome, so on a win they
receive `ownership_fraction * total_pot`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Sequence

from .curves import BondingCurve, PowerCurve

DEFAULT_MULTIPLES: tuple = (1, 2, 5, 10, 25, 50, 100, 500, 1000)


@dataclass
class SimConfig:
    num_outcomes: int
    early_pct: float                       # x: user buys first x% of each outcome's supply
    curve: BondingCurve                    # the per-outcome bonding curve (assumed identical)
    total_supply: float = 1_000_000_000.0  # total/graduation token supply per outcome
    buy_fee: float = 0.0                   # fraction added on buys (e.g. 0.005 = 0.5%)
    sell_fee: float = 0.0                  # fraction taken on sells
    multiples: Sequence[float] = DEFAULT_MULTIPLES
    quote: str = "USDT"

    def __post_init__(self) -> None:
        if self.num_outcomes < 1:
            raise ValueError("num_outcomes must be >= 1")
        if not (0 < self.early_pct <= 100):
            raise ValueError("early_pct must be in (0, 100]")
        if self.total_supply <= 0:
            raise ValueError("total_supply must be > 0")
        for f in (self.buy_fee, self.sell_fee):
            if not (0 <= f < 1):
                raise ValueError("fees must be in [0, 1)")


@dataclass
class StageRow:
    multiple: float            # market cap multiple vs entry
    # --- per single outcome ---
    market_cap: float          # spot market cap of one outcome at this stage
    price: float               # spot price of one outcome token
    supply: float              # circulating supply of one outcome
    ownership_pct: float       # user's share of that outcome's supply (%)
    spot_value: float          # mark-to-market value of the user's tokens, one outcome
    redeem_value: float        # realisable value selling back into the curve, one outcome
    # --- aggregate across ALL outcomes the user holds ---
    agg_spot_value: float
    agg_redeem_value: float
    spot_roi: float            # aggregate spot value / total spend - 1
    redeem_roi: float          # aggregate redeem value / total spend - 1
    # --- settlement (parimutuel) if the market resolved at this stage ---
    total_pot: float           # USDT collateral pooled across all outcomes
    settle_payout: float       # paid to user if a held outcome wins
    settle_roi: float          # settle_payout / total spend - 1


@dataclass
class SimResult:
    config: SimConfig
    tokens_per_outcome: float      # q = x% * total_supply
    spend_per_outcome: float       # USDT spent on one outcome (incl. buy fee)
    total_spend: float             # USDT spent across all outcomes
    entry_price: float
    entry_market_cap: float        # spot market cap of one outcome right after entry
    stages: List[StageRow] = field(default_factory=list)


def simulate(config: SimConfig) -> SimResult:
    curve = config.curve
    q = config.early_pct / 100.0 * config.total_supply

    spend_per_outcome = curve.cost(0.0, q) * (1.0 + config.buy_fee)
    total_spend = config.num_outcomes * spend_per_outcome
    entry_price = curve.price(q)
    entry_mcap = curve.market_cap(q)

    result = SimResult(
        config=config,
        tokens_per_outcome=q,
        spend_per_outcome=spend_per_outcome,
        total_spend=total_spend,
        entry_price=entry_price,
        entry_market_cap=entry_mcap,
    )

    for m in config.multiples:
        if m < 1:
            raise ValueError("multiples must be >= 1 (market cap grows from entry)")
        target_mcap = m * entry_mcap
        s = curve.supply_for_market_cap(target_mcap)
        price = curve.price(s)
        ownership = q / s

        spot_value = q * price
        redeem_value = curve.cost(s - q, s) * (1.0 - config.sell_fee)

        agg_spot = config.num_outcomes * spot_value
        agg_redeem = config.num_outcomes * redeem_value

        total_pot = config.num_outcomes * curve.reserve(s)
        settle_payout = ownership * total_pot

        result.stages.append(
            StageRow(
                multiple=m,
                market_cap=target_mcap,
                price=price,
                supply=s,
                ownership_pct=ownership * 100.0,
                spot_value=spot_value,
                redeem_value=redeem_value,
                agg_spot_value=agg_spot,
                agg_redeem_value=agg_redeem,
                spot_roi=agg_spot / total_spend - 1.0,
                redeem_roi=agg_redeem / total_spend - 1.0,
                total_pot=total_pot,
                settle_payout=settle_payout,
                settle_roi=settle_payout / total_spend - 1.0,
            )
        )

    return result
