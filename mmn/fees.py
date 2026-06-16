"""Protocol fee for 42 / Event Rush trades.

The protocol fee is **0.8% one-way** (charged on each trade) -> **1.6% round-trip**
(buy + sell). It is a per-market, governance-set rate in the contracts
(`FTControllerV2`, capped at `MAXIMUM_FEE_RATE`); 0.8% is the production value.

The dynamic redemption tax on selling back into the curve (RedeemMathV2) is modelled
separately in the simulator as a small pre-kink rate (~0.1%-5%); see mmn/simulator.py.
"""

from __future__ import annotations

# Production protocol fee per trade (one-way fraction); 1.6% round-trip.
DOCUMENTED_PROTOCOL_FEE = 0.008  # 0.8% one-way; per-market configurable on-chain
