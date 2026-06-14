"""Bonding-curve math for a single outcome token.

All curves expose the same interface so the simulator does not care which
concrete shape 42 uses on-chain. Two families are provided:

    PowerCurve   p(s) = k * s ** n          (the docs call it a "power curve")
    AffineCurve  p(s) = m * s + b           (linear with a base price)

`s` is the circulating supply of one outcome token (in whole tokens) and prices
are denominated in the collateral currency (USDT for Event Rush).

Key quantities, all derived from the instantaneous price p(s):

    price(s)            p(s)                         -- price of the next token
    reserve(s)          integral of p from 0..s      -- 42's market cap = collateral staked
    spot_market_cap(s)  p(s) * s                      -- generic spot value, NOT 42 mcap
    cost(a, b)          reserve(b) - reserve(a)       -- USDT to mint supply a -> b

The reserve is exactly the USDT that can be paid back out when redeeming, which
is why selling the whole supply back into the curve is always solvent. 42's
"market cap" is this reserve (cumulative staked), not the spot price * supply.
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod


# 42.space / Event Rush production curve, verified against MC_Sim/parimutuel_sim
# (market.py):
#     marginal price   p(x) = x^(3/4) / 2_000_000
#     market cap       mcap(x) = (4/7) * x^(7/4) / 2_000_000   (== reserve(x))
# i.e. a PowerCurve with coefficient k = 1/2_000_000 and exponent n = 3/4.
FT_PRICE_SCALE = 2_000_000.0
FT_ALPHA = 0.75


class BondingCurve(ABC):
    """Abstract single-outcome bonding curve."""

    @abstractmethod
    def price(self, s: float) -> float:
        """Instantaneous price of the next token at circulating supply ``s``."""

    @abstractmethod
    def reserve(self, s: float) -> float:
        """Collateral locked in the curve after minting ``s`` tokens from zero."""

    @abstractmethod
    def supply_for_spot_market_cap(self, mcap: float) -> float:
        """Circulating supply at which the SPOT market cap (price*supply) equals ``mcap``.

        NOTE: 42's "market cap" is the cumulative collateral staked = ``reserve``
        (use ``supply_for_reserve``). This spot quantity is a different, generic
        bonding-curve measure; it is ``(n+1)`` x the 42 market cap for a power curve.
        """

    @abstractmethod
    def supply_for_reserve(self, reserve: float) -> float:
        """Circulating supply at which the locked reserve equals ``reserve``."""

    # ---- shared, derived from the abstract methods above -------------------

    def spot_market_cap(self, s: float) -> float:
        """Spot market cap = price(s) * s.

        This is NOT 42's market cap. 42 defines market cap as cumulative
        collateral staked, which is ``reserve(s)`` (= spot/(n+1) for a power
        curve). Kept for completeness / generic bonding-curve analysis.
        """
        return self.price(s) * s

    def cost(self, a: float, b: float) -> float:
        """Collateral required to mint supply from ``a`` up to ``b`` (b >= a).

        Reused for redeeming: proceeds from selling ``b -> a`` equal cost(a, b).
        """
        if b < a:
            raise ValueError("cost expects b >= a")
        return self.reserve(b) - self.reserve(a)

    def tokens_for_spend(self, s0: float, spend: float) -> float:
        """Tokens obtained by spending ``spend`` collateral starting at supply ``s0``."""
        return self.supply_for_reserve(self.reserve(s0) + spend) - s0


class PowerCurve(BondingCurve):
    """p(s) = k * s ** n.

    n = 0 -> flat price, n = 1 -> linear, n = 2 -> quadratic, ...

    Closed forms (n != -1):
        reserve(s)         = k / (n + 1) * s ** (n + 1)   <- 42's market cap
        spot_market_cap(s) = k * s ** (n + 1) = (n + 1) * reserve(s)
    """

    def __init__(self, coefficient: float, exponent: float = 1.0):
        if coefficient <= 0:
            raise ValueError("coefficient (k) must be > 0")
        if exponent < 0:
            raise ValueError("exponent (n) must be >= 0")
        self.k = float(coefficient)
        self.n = float(exponent)

    @classmethod
    def ft(cls) -> "PowerCurve":
        """The exact 42.space production curve: p(x) = x^(3/4) / 2_000_000.

        Verified against MC_Sim's market.py: reserve(x) here equals 42's
        mcap(x) = (4/7) * x^(7/4) / 2_000_000, and tokens_for_spend / cost /
        supply_for_reserve reproduce its mint_units / cost_to_mint /
        supply_for_mcap exactly.
        """
        return cls(coefficient=1.0 / FT_PRICE_SCALE, exponent=FT_ALPHA)

    @classmethod
    def from_full_mcap(
        cls, total_supply: float, mcap_at_full: float, exponent: float = 1.0
    ) -> "PowerCurve":
        """Build a curve by pinning the spot market cap at the full supply.

        Lets you parameterise with intuitive numbers (total supply + the market
        cap when the curve is fully minted, e.g. the graduation FDV) instead of
        the raw coefficient k.

            mcap_at_full = k * total_supply ** (n + 1)
        """
        k = mcap_at_full / total_supply ** (exponent + 1)
        return cls(coefficient=k, exponent=exponent)

    def price(self, s: float) -> float:
        if s <= 0:  # guard tiny negative supply from float error -> avoids complex
            return 0.0
        return self.k * s ** self.n

    def reserve(self, s: float) -> float:
        if s <= 0:
            return 0.0
        return self.k / (self.n + 1) * s ** (self.n + 1)

    def supply_for_spot_market_cap(self, mcap: float) -> float:
        # spot mcap = k * s ** (n + 1)
        return (mcap / self.k) ** (1.0 / (self.n + 1))

    def supply_for_reserve(self, reserve: float) -> float:
        # reserve = k / (n + 1) * s ** (n + 1)
        return ((self.n + 1) * reserve / self.k) ** (1.0 / (self.n + 1))

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return f"PowerCurve(k={self.k:.6g}, n={self.n:g})"


class AffineCurve(BondingCurve):
    """p(s) = m * s + b  (slope m >= 0, base price b >= 0).

    Closed forms:
        reserve(s)         = m/2 * s ** 2 + b * s   <- 42's market cap
        spot_market_cap(s) = m * s ** 2 + b * s
    """

    def __init__(self, slope: float, base: float = 0.0):
        if slope < 0 or base < 0:
            raise ValueError("slope (m) and base (b) must be >= 0")
        if slope == 0 and base == 0:
            raise ValueError("slope and base cannot both be zero")
        self.m = float(slope)
        self.b = float(base)

    def price(self, s: float) -> float:
        if s <= 0:
            return self.b
        return self.m * s + self.b

    def reserve(self, s: float) -> float:
        if s <= 0:
            return 0.0
        return self.m / 2.0 * s * s + self.b * s

    def supply_for_spot_market_cap(self, mcap: float) -> float:
        # spot mcap: m s^2 + b s - mcap = 0
        if self.m == 0:
            return mcap / self.b
        disc = self.b * self.b + 4 * self.m * mcap
        return (-self.b + math.sqrt(disc)) / (2 * self.m)

    def supply_for_reserve(self, reserve: float) -> float:
        # m/2 s^2 + b s - reserve = 0
        if self.m == 0:
            return reserve / self.b
        disc = self.b * self.b + 2 * self.m * reserve
        return (-self.b + math.sqrt(disc)) / self.m

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return f"AffineCurve(m={self.m:.6g}, b={self.b:.6g})"
