"""Offline profitability sandbox for 42.space-style bonding-curve markets.

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

This package models the above with closed-form bonding-curve math (cross-checked
against numerical integration in the tests). Note: absolute USDT figures depend
on an assumed curve scale and are estimates; ROI/ownership multiples are scale-free.

The live-market analyzer is parked — see docs/live-analyzer.md.
"""

from .chart import mc_histogram_svg, ownership_and_roi_svg
from .curves import BondingCurve, PowerCurve
from .fees import DOCUMENTED_PROTOCOL_FEE
from .montecarlo import McConfig, McResult, run_montecarlo
from .simulator import SimConfig, SimResult, StageRow, simulate

__all__ = [
    "BondingCurve",
    "PowerCurve",
    "SimConfig",
    "SimResult",
    "StageRow",
    "simulate",
    "McConfig",
    "McResult",
    "run_montecarlo",
    "ownership_and_roi_svg",
    "mc_histogram_svg",
    "DOCUMENTED_PROTOCOL_FEE",
]
