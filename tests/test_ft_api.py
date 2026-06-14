"""Tests for the 42 REST client using a mocked transport (no network)."""

import urllib.error

import pytest

from mmn.ft_api import FtApiError, FtClient, Market, market_from_json

MARKET = {
    "address": "0xabc", "slug": "demo", "title": "Demo market", "status": "live",
    "collateral": "USDT",
    "outcomes": [
        {"tokenId": "1", "name": "Yes", "price": 0.5, "marketCap": 1000.0,
         "volume": 10.0, "payout": 1.2, "mintedQuantity": 200000.0},
        {"tokenId": "2", "name": "No", "price": 0.5, "marketCap": 900.0,
         "mintedQuantity": 180000.0},
    ],
}


def client_returning(body, capture=None):
    def transport(url, timeout):
        if capture is not None:
            capture.append(url)
        return body
    return FtClient(transport=transport)


def test_list_markets_wrapped_in_data():
    import json
    c = client_returning(json.dumps({"data": [MARKET]}))
    markets = c.list_markets(status="live")
    assert len(markets) == 1
    m = markets[0]
    assert m.title == "Demo market" and m.num_outcomes == 2
    assert m.outcomes[0].name == "Yes" and m.outcomes[0].minted_quantity == 200000.0
    assert m.total_pot == pytest.approx(1900.0)


def test_list_markets_bare_list():
    import json
    c = client_returning(json.dumps([MARKET, MARKET]))
    assert len(c.list_markets()) == 2


def test_get_market_object_and_status_param():
    import json
    cap = []
    c = client_returning(json.dumps(MARKET), capture=cap)
    m = c.get_market("0xabc")
    assert m.address == "0xabc" and m.collateral == "USDT"
    assert "/markets/0xabc" in cap[0]


def test_list_status_all_omits_param():
    import json
    cap = []
    c = client_returning(json.dumps({"data": []}), capture=cap)
    c.list_markets(status="all")
    assert "status=" not in cap[0]


def test_alternate_field_spellings():
    import json
    payload = {"title": "Alt", "outcomeTokens": [
        {"id": "9", "outcome": "Maybe", "currentPrice": 0.3,
         "market_cap": 500.0, "totalSupply": 12345.0}]}
    m = market_from_json(payload)
    o = m.outcomes[0]
    assert o.token_id == "9" and o.name == "Maybe"
    assert o.price == 0.3 and o.market_cap == 500.0 and o.minted_quantity == 12345.0


def test_missing_fields_degrade_to_none():
    m = market_from_json({"title": "Sparse", "outcomes": [{"name": "X"}]})
    o = m.outcomes[0]
    assert o.price is None and o.market_cap is None and o.minted_quantity is None
    assert m.total_pot == 0.0


def test_empty_results():
    import json
    c = client_returning(json.dumps({"data": []}))
    assert c.list_markets() == []


def test_http_error_becomes_ftapierror():
    def transport(url, timeout):
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
    with pytest.raises(FtApiError):
        FtClient(transport=transport).get_market("missing")


def test_url_error_becomes_ftapierror():
    def transport(url, timeout):
        raise urllib.error.URLError("no route")
    with pytest.raises(FtApiError):
        FtClient(transport=transport).list_markets()


def test_malformed_json_becomes_ftapierror():
    with pytest.raises(FtApiError):
        client_returning("<html>not json</html>").list_markets()


def test_empty_body_becomes_ftapierror():
    with pytest.raises(FtApiError):
        client_returning("   ").list_markets()


def test_unnamed_outcomes_get_index_names():
    m = market_from_json({"outcomes": [{}, {}]})
    assert m.outcomes[0].name == "Outcome 0" and m.outcomes[1].name == "Outcome 1"
