"""Fee / redemption modelling for 42 buys and sells.

What is documented (per 42 docs, https://docs.42.space/.../fees) and used here:
  * a PROTOCOL FEE on trades. 42's current docs describe ~0.8% (this replaces the
    earlier, incorrect "0.2% confirmed" assumption). It is configurable.
  * a DYNAMIC REDEMPTION TAX / spread on selling back into the curve. Its exact
    formula is not reproduced from public docs/API in this build, so we DO NOT
    fake it: redeem figures are flagged approximate and a warning is emitted.

Redeem tax modes:
  * "ignore"     -> no redemption tax (protocol fee only). Clearly understates
                    real exit cost; still flagged approximate.
  * "manual"     -> apply ``manual_redeem_tax`` as a flat % (your own estimate).
  * "documented" -> use ``manual_redeem_tax`` as a stand-in for the documented
                    dynamic tax (default 0 unless you set it) and warn loudly
                    that the exact dynamic formula is NOT implemented.
"""

from __future__ import annotations

from dataclasses import dataclass

# Current documented protocol fee (fraction). NOT 0.2% — that earlier value was
# wrong. Override with --protocol-fee once you re-verify against live docs.
DOCUMENTED_PROTOCOL_FEE = 0.008  # 0.8%

REDEEM_TAX_MODES = ("documented", "ignore", "manual")


@dataclass
class FeeModel:
    protocol_fee: float = DOCUMENTED_PROTOCOL_FEE
    redeem_tax_mode: str = "documented"
    manual_redeem_tax: float = 0.0      # fraction, used by manual/documented modes
    gas_usd: float = 0.0

    def __post_init__(self) -> None:
        if not (0 <= self.protocol_fee < 1):
            raise ValueError("protocol_fee must be in [0, 1)")
        if self.redeem_tax_mode not in REDEEM_TAX_MODES:
            raise ValueError(f"redeem_tax_mode must be one of {REDEEM_TAX_MODES}")
        if not (0 <= self.manual_redeem_tax < 1):
            raise ValueError("manual_redeem_tax must be in [0, 1)")
        if self.gas_usd < 0:
            raise ValueError("gas_usd must be >= 0")

    # -- buying -------------------------------------------------------------
    def net_to_curve(self, gross_spend: float) -> float:
        """Collateral that actually reaches the curve after the protocol fee."""
        return gross_spend * (1.0 - self.protocol_fee)

    def buy_fee(self, gross_spend: float) -> float:
        return gross_spend * self.protocol_fee

    # -- selling / redeeming ------------------------------------------------
    def redeem_tax_rate(self) -> float:
        """Total fraction removed from gross curve proceeds when redeeming.

        Combines the protocol fee with the (approximate) redemption tax.
        """
        if self.redeem_tax_mode == "ignore":
            extra = 0.0
        else:  # manual or documented (documented uses manual as a stand-in)
            extra = self.manual_redeem_tax
        return min(self.protocol_fee + extra, 0.999)

    def redeem_is_approximate(self) -> bool:
        """Redeem is only 'exact' if no dynamic tax is in play and we ignore it."""
        return self.redeem_tax_mode != "ignore" or True  # always approximate today

    def redeem_warning(self) -> str:
        if self.redeem_tax_mode == "ignore":
            return ("Redeem assumes NO dynamic redemption tax (protocol fee only); "
                    "42 applies a dynamic tax, so real exit value is lower.")
        if self.redeem_tax_mode == "manual":
            return (f"Redeem uses your manual tax of {self.manual_redeem_tax*100:g}% "
                    f"plus {self.protocol_fee*100:g}% protocol fee (your estimate).")
        return ("Redeem uses a documented-tax stand-in "
                f"({self.manual_redeem_tax*100:g}% + {self.protocol_fee*100:g}% "
                "protocol fee). 42's exact dynamic redemption tax is NOT implemented; "
                "treat redeem values as approximate.")
