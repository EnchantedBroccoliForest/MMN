"""Bonding-curve math for a single outcome token.

All curves expose the same interface so the simulator does not care about the
concrete shape. 42's production curve is the power curve:

    PowerCurve   p(s) = k * s ** n          (42's on-chain "power curve")

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

from abc import ABC, abstractmethod

# 42.space / Event Rush production power curve, VERIFIED against the on-chain
# contracts (ft-contracts: src/curves/config/PowerCurve.sol PowerCurveSet1 and
# src/curves/math/PowerMath.sol). The contract math (per outcome token) is:
#     cost / market cap   mcap(x) = (x + start)^(c1+1) / c2          [== reserve(x)]
#     marginal price      p(x)    = (c1+1) * (x + start)^c1 / c2
# with PowerCurveSet1: c1 = 0.75 (the exponent), c2 = 2_000_000 (FT_PRICE_SCALE),
# start = 8.888... tokens.
#
# So both the exponent (3/4) AND the 2,000,000 scale are REAL on-chain parameters,
# not invented. Note: c2 scales the COST integral (not the marginal price), so the
# price carries the (c1+1) = 7/4 factor -- PowerCurve.ft() encodes this by using
# k = (n+1)/FT_PRICE_SCALE (see ft()). Caveats this module does NOT model:
#   * the +start (8.888) offset -- negligible above ~thousands of tokens, divergent
#     near zero supply;
#   * the exponent is per-curve-SET (Set1/Set4 = 0.75, Set2 = 2/3, Set3 = 0.8);
#   * the opening-window LDA premium (first ~20s) and the dynamic redemption tax
#     (handled approximately in fees / the simulator, see RedeemMathV2).
# ROI and ownership *multiples* depend only on the exponent and are exact; absolute
# USDT now matches the contract (above ~start supply).
FT_PRICE_SCALE = 2_000_000.0  # PowerCurveSet1.C2 (config/PowerCurve.sol:54)
FT_ALPHA = 0.75  # PowerCurveSet1.C1 (config/PowerCurve.sol:53)


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
    def ft(cls) -> PowerCurve:
        """42.space production power curve, matched to the on-chain contract.

        Contract (PowerCurveSet1, PowerMath.sol): market cap = reserve(x) =
        x^(n+1)/c2 and marginal price = (n+1)*x^n/c2, with n = 0.75 and
        c2 = FT_PRICE_SCALE = 2,000,000. In this class price(s) = k*s^n and
        reserve(s) = k/(n+1)*s^(n+1), so we set ``k = (n+1)/c2`` to reproduce both:
        price = (n+1)/c2 * s^n and reserve = s^(n+1)/c2 -- EXACTLY the contract
        (ignoring the +start=8.888 offset, negligible above ~thousands of tokens).
        """
        return cls(coefficient=(1.0 + FT_ALPHA) / FT_PRICE_SCALE, exponent=FT_ALPHA)

    @classmethod
    def from_full_mcap(
        cls, total_supply: float, mcap_at_full: float, exponent: float = 1.0
    ) -> PowerCurve:
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
        return self.k * s**self.n

    def reserve(self, s: float) -> float:
        if s <= 0:
            return 0.0
        return self.k / (self.n + 1) * s ** (self.n + 1)

    def supply_for_spot_market_cap(self, mcap: float) -> float:
        # spot mcap = k * s ** (n + 1)
        if mcap <= 0:  # guard: negative -> complex result, violating -> float
            return 0.0
        return (mcap / self.k) ** (1.0 / (self.n + 1))

    def supply_for_reserve(self, reserve: float) -> float:
        # reserve = k / (n + 1) * s ** (n + 1)
        if reserve <= 0:  # guard: negative -> complex result, violating -> float
            return 0.0
        return ((self.n + 1) * reserve / self.k) ** (1.0 / (self.n + 1))

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return f"PowerCurve(k={self.k:.6g}, n={self.n:g})"
