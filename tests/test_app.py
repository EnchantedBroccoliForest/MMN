"""Web API tests (Quart async test client): /api/simulate and /api/montecarlo —
validation, the documented-fee default, the num_outcomes DoS cap, JSON safety."""

import pytest

import app as appmod


@pytest.fixture
def client():
    appmod.app.config["TESTING"] = True
    return appmod.app.test_client()


# ----------------------------- DoS / caps ---------------------------------
async def test_simulate_caps_num_outcomes(client):
    r = await client.post("/api/simulate", json={"num_outcomes": 10_000})
    assert r.status_code == 200
    assert (await r.get_json())["num_outcomes"] == appmod.MAX_NUM_OUTCOMES


async def test_montecarlo_caps_num_outcomes_and_trials(client):
    r = await client.post("/api/montecarlo", json={"num_outcomes": 10_000, "mc_trials": 10**9})
    assert r.status_code == 200
    d = await r.get_json()
    assert d["n_trials"] <= appmod.MAX_MC_TRIALS


# ------------------------ defaults / smoke --------------------------------
async def test_simulate_uses_production_defaults(client):
    d = await (await client.post("/api/simulate", json={})).get_json()
    assert d["buy_fee"] == pytest.approx(0.008)  # 0.8% one-way
    assert d["sell_fee"] == pytest.approx(0.008)
    assert d["redeem_tax"] == pytest.approx(0.05)
    assert d["is_production"] is True  # matches PowerCurveSet1 + 0.4% fee


async def test_simulate_returns_redeem_band(client):
    d = await (await client.post("/api/simulate", json={})).get_json()
    s = d["stages"][-1]  # deepest growth multiple
    # band: 0.1% tax (best) >= configured-tax redeem_roi >= 5% tax (worst)
    assert s["redeem_roi_band_hi"] >= s["redeem_roi"] >= s["redeem_roi_band_lo"]


async def test_simulate_rejects_bad_json(client):
    r = await client.post(
        "/api/simulate", data="not json", headers={"Content-Type": "application/json"}
    )
    assert r.status_code == 400


async def test_montecarlo_smoke(client):
    r = await client.post("/api/montecarlo", json={"num_outcomes": 3, "mc_trials": 500})
    assert r.status_code == 200
    assert "histogram" in await r.get_json()


async def test_montecarlo_output_is_json_safe(client):
    # no inf/nan leaks into the JSON payload
    r = await client.post("/api/montecarlo", json={"num_outcomes": 4, "mc_trials": 500})
    raw = await r.get_data(as_text=True)
    assert "Infinity" not in raw and "NaN" not in raw
