"""Minimal 42 / Event Rush REST API client (standard library only).

Base URL (alpha): https://rest.ft.42.space/api/v1

Endpoints used (see https://docs.42.space/for-developers/rest-api-alpha):
  GET /markets?status=live|resolved|all&limit=N      -> list markets
  GET /markets/{address_or_slug}                     -> one market
  GET /market-data/prices?market={address_or_slug}   -> current outcome prices

The shape of the alpha API is not 100% pinned in public docs, and this sandbox
cannot reach the API to introspect it, so parsing is intentionally defensive:
every field is read through a list of likely key spellings and missing values
degrade to ``None`` rather than raising. Adjust ``_FIELDS`` if the live schema
differs.

Network is isolated for testability: ``FtClient`` takes a ``transport`` callable
``(url, timeout) -> str``. The default uses urllib; tests inject a fake.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

DEFAULT_BASE_URL = "https://rest.ft.42.space/api/v1"
Transport = Callable[[str, float], str]


class FtApiError(Exception):
    """Raised for any transport, HTTP, or payload problem talking to the API."""


# ---------------------------------------------------------------------------
# defensive field extraction
# ---------------------------------------------------------------------------
def _first(d: Dict[str, Any], *keys: str) -> Any:
    for k in keys:
        if isinstance(d, dict) and k in d and d[k] is not None:
            return d[k]
    return None


def _num(v: Any) -> Optional[float]:
    if v is None or isinstance(v, bool):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _unwrap_list(payload: Any) -> List[dict]:
    """Markets endpoints may return a bare list or wrap it under a key."""
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict):
        for key in ("data", "markets", "items", "results", "rows"):
            v = payload.get(key)
            if isinstance(v, list):
                return [x for x in v if isinstance(x, dict)]
        # a single market object
        if any(k in payload for k in ("address", "slug", "outcomes", "marketId")):
            return [payload]
    return []


def _unwrap_obj(payload: Any) -> dict:
    if isinstance(payload, dict):
        for key in ("data", "market", "result"):
            v = payload.get(key)
            if isinstance(v, dict):
                return v
        return payload
    if isinstance(payload, list) and payload and isinstance(payload[0], dict):
        return payload[0]
    raise FtApiError("expected a market object in response")


# ---------------------------------------------------------------------------
# data models
# ---------------------------------------------------------------------------
@dataclass
class Outcome:
    token_id: Optional[str]
    name: str
    price: Optional[float]          # current marginal price (collateral / token)
    market_cap: Optional[float]     # cumulative collateral staked (42 "market cap")
    volume: Optional[float]
    payout: Optional[float]         # current per-token settlement estimate, if provided
    minted_quantity: Optional[float]
    raw: dict = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, d: dict, index: int = 0) -> "Outcome":
        return cls(
            token_id=_first(d, "tokenId", "token_id", "id", "outcomeId"),
            name=str(_first(d, "name", "outcome", "title", "label", "outcomeName")
                     or f"Outcome {index}"),
            price=_num(_first(d, "price", "currentPrice", "marginalPrice", "lastPrice")),
            market_cap=_num(_first(d, "marketCap", "market_cap", "mcap", "reserve",
                                   "collateral", "tvl")),
            volume=_num(_first(d, "volume", "volume24h", "totalVolume")),
            payout=_num(_first(d, "payout", "payoutPerToken", "redemptionValue")),
            minted_quantity=_num(_first(d, "mintedQuantity", "minted_quantity",
                                        "supply", "totalSupply", "quantity")),
            raw=d,
        )


@dataclass
class Market:
    address: Optional[str]
    slug: Optional[str]
    title: str
    status: Optional[str]
    collateral: str
    outcomes: List[Outcome]
    raw: dict = field(default_factory=dict, repr=False)

    @property
    def num_outcomes(self) -> int:
        return len(self.outcomes)

    @property
    def total_pot(self) -> float:
        """Sum of staked collateral across outcomes (the parimutuel pot)."""
        return sum(o.market_cap or 0.0 for o in self.outcomes)

    @property
    def ref(self) -> str:
        return self.address or self.slug or self.title

    @classmethod
    def from_dict(cls, d: dict) -> "Market":
        raw_outcomes = (_first(d, "outcomes", "outcomeTokens", "tokens", "options")
                        or [])
        outcomes = [Outcome.from_dict(o, i)
                    for i, o in enumerate(raw_outcomes) if isinstance(o, dict)]
        return cls(
            address=_first(d, "address", "marketAddress", "contractAddress"),
            slug=_first(d, "slug", "marketSlug"),
            title=str(_first(d, "title", "name", "question", "marketTitle")
                      or "Untitled market"),
            status=_first(d, "status", "state", "phase"),
            collateral=str(_first(d, "collateral", "collateralSymbol",
                                  "quote", "currency") or "USDT"),
            outcomes=outcomes,
            raw=d,
        )


# ---------------------------------------------------------------------------
# transport
# ---------------------------------------------------------------------------
def _urllib_transport(url: str, timeout: float) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "mmn-ft-client/1.0",
                                               "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (https only by base)
        charset = resp.headers.get_content_charset() or "utf-8"
        return resp.read().decode(charset)


# ---------------------------------------------------------------------------
# client
# ---------------------------------------------------------------------------
class FtClient:
    def __init__(self, base_url: str = DEFAULT_BASE_URL, timeout: float = 15.0,
                 transport: Optional[Transport] = None):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._transport = transport or _urllib_transport

    def _get(self, path: str, params: Optional[dict] = None) -> Any:
        url = self.base_url + path
        if params:
            clean = {k: v for k, v in params.items() if v is not None}
            if clean:
                url += "?" + urllib.parse.urlencode(clean)
        try:
            body = self._transport(url, self.timeout)
        except urllib.error.HTTPError as e:
            raise FtApiError(f"HTTP {e.code} from {url}") from e
        except urllib.error.URLError as e:
            raise FtApiError(f"network error reaching {url}: {e.reason}") from e
        except Exception as e:  # transport-defined failures
            raise FtApiError(f"request to {url} failed: {e}") from e
        if not body or not body.strip():
            raise FtApiError(f"empty response body from {url}")
        try:
            return json.loads(body)
        except (ValueError, TypeError) as e:
            raise FtApiError(f"malformed JSON from {url}") from e

    # -- public API ---------------------------------------------------------
    def list_markets(self, status: str = "live", limit: Optional[int] = None
                     ) -> List[Market]:
        """List markets. ``status`` is one of live|resolved|all."""
        params = {"limit": limit}
        if status and status != "all":
            params["status"] = status
        payload = self._get("/markets", params)
        return [Market.from_dict(m) for m in _unwrap_list(payload)]

    def get_market(self, address_or_slug: str) -> Market:
        """Fetch one market by address or slug."""
        ref = urllib.parse.quote(str(address_or_slug), safe="")
        payload = self._get(f"/markets/{ref}")
        return Market.from_dict(_unwrap_obj(payload))

    def get_outcome_prices(self, address_or_slug: str) -> List[Outcome]:
        """Current outcome-token prices/state for a market.

        Per the REST docs ("Get current outcome token prices") this is the
        ``/market-data/prices`` endpoint filtered by market, NOT a nested
        ``/markets/{ref}/...`` route. The exact filter key isn't pinned in the
        public docs from here; ``market`` is used and should be confirmed live.
        """
        payload = self._get("/market-data/prices", {"market": address_or_slug})
        items = _unwrap_list(payload)
        return [Outcome.from_dict(o, i) for i, o in enumerate(items)]


def market_from_json(payload: Any) -> Market:
    """Build a Market from an already-decoded JSON object (offline snapshots)."""
    return Market.from_dict(_unwrap_obj(payload))
