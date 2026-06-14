"""Profitability simulator for early buyers on 42.space-style bonding-curve markets.

42 / Event Rush mechanism (BNB Chain, collateral = USDT):

  * A *market* has N possible *outcomes*.
  * Each outcome is its own *outcome token* sitting on its own bonding ("power")
    curve. Buying mints tokens and pushes price up the curve; selling redeems
    tokens back into the curve and pushes price down.
  * Trading is continuous. You can exit any time before resolution by selling
    back into the curve, OR hold to settlement.
  * At resolution the market settles to a single winning outcome (parimutuel):
    the USDT collateral locked in every losing outcome is pooled and paid out
    pro-rata to holders of the winning token.

This package models all of the above with closed-form bonding-curve math so the
numbers are exact (cross-checked against numerical integration in the tests).
"""

from .curves import BondingCurve, PowerCurve, AffineCurve
from .simulator import SimConfig, SimResult, StageRow, simulate

__all__ = [
    "BondingCurve",
    "PowerCurve",
    "AffineCurve",
    "SimConfig",
    "SimResult",
    "StageRow",
    "simulate",
]
