"""Early-buyer profitability simulation over a 42 / Event Rush market.

Verified against MC_Sim/parimutuel_sim. The per-outcome curve is 42's exact
production curve p(x)=x^(3/4)/2_000_000, and "market cap" means what 42 means:
the CUMULATIVE USDT staked into that outcome (= the bonding-curve reserve =
its share of the parimutuel pot), NOT price*supply.

The user's three questions map to this module:

  1. How many outcomes?                      -> SimConfig.num_outcomes
  2. Buy x% of the EARLIEST part of every    -> SimConfig.early_pct (first x% of
     outcome's curve. Total spend?              each outcome's reference supply)
  3. As market cap grows, profitability &    -> stages at market-cap MULTIPLES of
     % ownership?                               the user's entry market cap

Three ways to value a held position are reported:

  * spot (mark-to-market): units * current price. Optimistic upper bound.
  * redeem (realisable):   USDT from selling the units back into the curve
    (42 supports redeem; MC_Sim itself is mint-and-hold).
  * settlement (parimutuel): if the market resolves now and this outcome WINS,
    payout = units * (total_pool / winning_supply) = ownership * total_pool.

Closed-form facts for the 42 curve (exponent n=3/4, so n+1=7/4):
  * ownership at market-cap multiple M  =  M^(-4/7)
  * settlement-win value / spend        =  M^( 3/7)
These are independent of the supply scale and the fee-free coefficient.
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
    curve: BondingCurve                    # per-outcome curve (default: PowerCurve.ft())
    total_supply: float = 1_000_000.0      # reference supply per outcome (sets $ scale)
    buy_fee: float = 0.002                 # 0.2% per buy  (confirmed)
    sell_fee: float = 0.002                # 0.2% per sell (confirmed)
    house_seed_mcap: float = 0.0           # USDT the house seeds each outcome with
    multiples: Sequence[float] = DEFAULT_MULTIPLES
    quote: str = "USDT"

    def __post_init__(self) -> None:
        if self.num_outcomes < 1:
            raise ValueError("num_outcomes must be >= 1")
        if not (0 < self.early_pct <= 100):
            raise ValueError("early_pct must be in (0, 100]")
        if self.total_supply <= 0:
            raise ValueError("total_supply must be > 0")
        if self.house_seed_mcap < 0:
            raise ValueError("house_seed_mcap must be >= 0")
        for f in (self.buy_fee, self.sell_fee):
            if not (0 <= f < 1):
                raise ValueError("fees must be in [0, 1)")


@dataclass
class StageRow:
    multiple: float            # market-cap multiple vs entry
    # --- per single outcome ---
    market_cap: float          # cumulative USDT staked in one outcome at this stage
    price: float               # marginal price of one outcome token
    supply: float              # circulating supply of one outcome
    ownership_pct: float       # user's share of that outcome's supply (%)
    spot_value: float          # mark-to-market value of the user's units, one outcome
    redeem_value: float        # realisable value selling back into the curve, one outcome
    # --- aggregate across ALL outcomes the user holds ---
    agg_spot_value: float
    agg_redeem_value: float
    redeem_roi: float          # aggregate redeem value / total spend - 1
    # --- settlement (parimutuel) if the market resolves at this stage ---
    total_pot: float           # USDT pooled across all outcomes
    settle_payout: float       # paid to user if a held outcome wins
    settle_roi: float          # settle_payout / total spend - 1


@dataclass
class SimResult:
    config: SimConfig
    tokens_per_outcome: float      # q = x% * total_supply  (units the user holds)
    seed_supply: float             # supply already present from the house seed
    spend_per_outcome: float       # USDT spent on one outcome (incl. buy fee)
    total_spend: float             # USDT spent across all outcomes
    entry_price: float
    entry_market_cap: float        # cumulative USDT staked in one outcome right after entry
    stages: List[StageRow] = field(default_factory=list)


def simulate(config: SimConfig) -> SimResult:
    curve = config.curve
    q = config.early_pct / 100.0 * config.total_supply

    # The house may have seeded the outcome before the user arrives; the user
    # mints the next q units on top of that seed.
    seed_supply = curve.supply_for_reserve(config.house_seed_mcap) if config.house_seed_mcap else 0.0
    entry_supply = seed_supply + q

    spend_per_outcome = curve.cost(seed_supply, entry_supply) * (1.0 + config.buy_fee)
    total_spend = config.num_outcomes * spend_per_outcome
    entry_price = curve.price(entry_supply)
    entry_mcap = curve.reserve(entry_supply)   # 42 market cap = cumulative staked

    result = SimResult(
        config=config,
        tokens_per_outcome=q,
        seed_supply=seed_supply,
        spend_per_outcome=spend_per_outcome,
        total_spend=total_spend,
        entry_price=entry_price,
        entry_market_cap=entry_mcap,
    )

    for m in config.multiples:
        if m < 1:
            raise ValueError("multiples must be >= 1 (market cap grows from entry)")
        target_mcap = m * entry_mcap
        s = curve.supply_for_reserve(target_mcap)
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
                redeem_roi=agg_redeem / total_spend - 1.0,
                total_pot=total_pot,
                settle_payout=settle_payout,
                settle_roi=settle_payout / total_spend - 1.0,
            )
        )

    return result
