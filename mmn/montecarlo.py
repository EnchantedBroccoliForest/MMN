"""Monte Carlo of an early buyer's outcome on a 42 / Event Rush market.

Why a Monte Carlo? The deterministic tables in ``simulator`` assume every
outcome grows by the same market-cap multiple and then ask "what if THIS one
wins". Reality is messier and that messiness is the whole story for an early
buyer who holds a slice of EVERY outcome:

  * the house seeds each outcome with a small, random market cap (MC_Sim uses
    Uniform(0.10, 10.0) USDT),
  * later capital floods in unevenly - favourites attract more money (so your
    % ownership there ends up smaller), and
  * exactly one outcome wins, drawn from a prior.

Because the buyer holds the same early slice ``q`` of every outcome, on a win
they collect ``ownership_in_winner * total_pot``. When a thinly-funded outcome
wins their ownership there is high (big payout); when a heavily-funded
favourite wins it is low. This module samples that distribution.

Model per trial (all in USDT, curve = 42's production curve):
  seed_i      ~ Uniform(seed_min, seed_max)                      house seed
  q            = early_pct% * total_supply                        early units (per outcome)
  spend_i      = cost(seed_supply_i, seed_supply_i + q)*(1+fee)
  added_pool   ~ Lognormal(mean = mean_added_pool, sigma)         later capital
  w            ~ Dirichlet(concentration * prior)                 how it splits (mean = prior)
  final_mcap_i = entry_mcap_i + added_pool * w_i
  winner       ~ Categorical(prior)
  payout       = (q / supply(final_mcap_winner)) * sum(final_mcap)
  settle_mult  = payout / sum(spend_i)
"""

from __future__ import annotations

import math
import random
from collections.abc import Sequence
from dataclasses import dataclass, field

from .curves import BondingCurve, PowerCurve


@dataclass
class McConfig:
    num_outcomes: int
    early_pct: float
    curve: BondingCurve = field(default_factory=PowerCurve.ft)
    total_supply: float = 1_000_000.0
    buy_fee: float = 0.008  # 42's 0.8% one-way protocol fee
    sell_fee: float = 0.008  # 0.8% out -> 1.6% round-trip
    # dynamic redemption tax (RedeemMathV2): sampled per trial across the PRE-KINK
    # range, since the exact rate depends on size/time. Uniform(redeem_tax_min, max).
    redeem_tax_min: float = 0.001  # 0.1%
    redeem_tax_max: float = 0.05  # 5%
    seed_min: float = 0.10  # house seed range (USDT market cap) - MC_Sim default
    seed_max: float = 10.0
    prior: Sequence[float] | None = None  # winner probs (len N); None -> uniform
    mean_added_pool: float = 100_000.0  # expected total later capital across all outcomes
    pool_sigma: float = 0.6  # lognormal sigma of the added pool
    concentration: float = 8.0  # Dirichlet sharpness (higher -> closer to prior)
    n_trials: int = 20_000
    seed: int = 0
    quote: str = "USDT"

    def __post_init__(self) -> None:
        if self.num_outcomes < 1:
            raise ValueError("num_outcomes must be >= 1")
        if not (0 < self.early_pct <= 100):
            raise ValueError("early_pct must be in (0, 100]")
        if self.seed_min < 0 or self.seed_max < self.seed_min:
            raise ValueError("require 0 <= seed_min <= seed_max")
        if not (0 <= self.redeem_tax_min <= self.redeem_tax_max < 1):
            raise ValueError("require 0 <= redeem_tax_min <= redeem_tax_max < 1")
        if self.mean_added_pool <= 0:
            raise ValueError("mean_added_pool must be > 0")
        if self.n_trials < 1:
            raise ValueError("n_trials must be >= 1")
        if self.prior is not None:
            if len(self.prior) != self.num_outcomes:
                raise ValueError("prior length must equal num_outcomes")
            if any(p < 0 for p in self.prior) or sum(self.prior) <= 0:
                raise ValueError("prior must be non-negative and sum to > 0")

    def normalized_prior(self) -> list[float]:
        if self.prior is None:
            return [1.0 / self.num_outcomes] * self.num_outcomes
        total = float(sum(self.prior))
        return [p / total for p in self.prior]


@dataclass
class McResult:
    config: McConfig
    settle_mult: list[float]  # settlement payout / total spend, per trial
    redeem_mult: list[float]  # sell-everything-back / total spend, per trial
    total_spend: float  # deterministic given seeds? no - mean across trials
    prob_profit: float  # P(settlement payout > spend)
    mean_settle: float
    median_settle: float
    p05_settle: float
    p95_settle: float
    mean_redeem: float


def _percentile(sorted_vals: list[float], pct: float) -> float:
    if not sorted_vals:
        return float("nan")
    k = (len(sorted_vals) - 1) * pct
    lo = math.floor(k)
    hi = math.ceil(k)
    if lo == hi:
        return sorted_vals[int(k)]
    return sorted_vals[lo] * (hi - k) + sorted_vals[hi] * (k - lo)


def _dirichlet(alpha: list[float], rng: random.Random) -> list[float]:
    gammas = [rng.gammavariate(a, 1.0) if a > 0 else 0.0 for a in alpha]
    total = sum(gammas)
    if total <= 0:
        n = len(alpha)
        return [1.0 / n] * n
    return [g / total for g in gammas]


def _categorical(prior: list[float], rng: random.Random) -> int:
    r = rng.random()
    acc = 0.0
    for i, p in enumerate(prior):
        acc += p
        if r <= acc:
            return i
    return len(prior) - 1


def run_montecarlo(config: McConfig) -> McResult:
    rng = random.Random(config.seed)
    curve = config.curve
    n = config.num_outcomes
    q = config.early_pct / 100.0 * config.total_supply
    prior = config.normalized_prior()
    alpha = [config.concentration * p * n for p in prior]

    # lognormal params so that E[added_pool] == mean_added_pool
    sigma = config.pool_sigma
    mu = math.log(config.mean_added_pool) - 0.5 * sigma * sigma

    settle_mult: list[float] = []
    redeem_mult: list[float] = []
    spend_accum = 0.0
    profit_count = 0

    for _ in range(config.n_trials):
        # Per-outcome house seed -> entry state and spend.
        entry_mcaps = []
        entry_supplies = []
        total_spend = 0.0
        for _i in range(n):
            seed_mcap = rng.uniform(config.seed_min, config.seed_max)
            seed_supply = curve.supply_for_reserve(seed_mcap) if seed_mcap > 0 else 0.0
            entry_supply = seed_supply + q
            total_spend += curve.cost(seed_supply, entry_supply) * (1.0 + config.buy_fee)
            entry_mcaps.append(curve.reserve(entry_supply))
            entry_supplies.append(entry_supply)
        spend_accum += total_spend

        added = rng.lognormvariate(mu, sigma)
        weights = _dirichlet(alpha, rng)

        final_supplies = []
        total_pot = 0.0
        for i in range(n):
            final_mcap = entry_mcaps[i] + added * weights[i]
            total_pot += final_mcap
            final_supplies.append(curve.supply_for_reserve(final_mcap))

        # Realisable value if the buyer sold everything back into the curves now.
        # Redemption tax sampled across the pre-kink range; proceeds = gross *
        # (1 - redeem_tax) * (1 - sell_fee), matching the contract.
        redeem_tax = rng.uniform(config.redeem_tax_min, config.redeem_tax_max)
        redeem_value = 0.0
        for i in range(n):
            s = final_supplies[i]
            redeem_value += (
                curve.cost(max(s - q, 0.0), s) * (1.0 - redeem_tax) * (1.0 - config.sell_fee)
            )
        redeem_mult.append(redeem_value / total_spend)

        # Settlement: one winner; buyer holds q of it.
        w = _categorical(prior, rng)
        ownership_w = q / final_supplies[w]
        payout = ownership_w * total_pot
        mult = payout / total_spend
        settle_mult.append(mult)
        if payout > total_spend:
            profit_count += 1

    settle_sorted = sorted(settle_mult)
    return McResult(
        config=config,
        settle_mult=settle_mult,
        redeem_mult=redeem_mult,
        total_spend=spend_accum / config.n_trials,
        prob_profit=profit_count / config.n_trials,
        mean_settle=sum(settle_mult) / config.n_trials,
        median_settle=_percentile(settle_sorted, 0.50),
        p05_settle=_percentile(settle_sorted, 0.05),
        p95_settle=_percentile(settle_sorted, 0.95),
        mean_redeem=sum(redeem_mult) / config.n_trials,
    )
