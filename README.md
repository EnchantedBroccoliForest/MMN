# MMN — 42 / Event Rush buyer toolkit

An **offline profitability sandbox** for
[42.space](https://www.42.space/) / **Event Rush** markets (the 42-powered dApp
on BNB Chain). The bonding-curve / parimutuel **math engine is standard-library
only**; the web app (Quart/ASGI) on uvicorn+uvloop is the only runtime layer.

It models the **"buy the first x% of supply, then watch the market cap grow"**
what-if: how your ownership dilutes, what you'd redeem, and your payout if a held
outcome wins at settlement — plus a Monte Carlo over random seeds, uneven capital
inflow, and a random winner. It runs on **invented** inputs (it is **not** a live
market). The curve is **verified against the on-chain contracts** (`ft-contracts`),
so absolute USDT now matches production (above the curve start); ROI/ownership
*multiples* are exact (scale-free).

> **Live-market analyzer:** a mode that analyzed a *real* 42 market (REST API +
> async httpx/HTTP-2 client) is **parked** — its intent and rebuild guide live in
> [`docs/live-analyzer.md`](docs/live-analyzer.md).

> **Fees:** the protocol fee is **0.8% one-way** (charged per trade → **1.6%
> round-trip**); per-market configurable on-chain. The dynamic
> **redemption tax** on selling back into the curve is modelled as a small
> pre-kink rate (~**0.1%–5%**; the Monte Carlo samples that range). On-chain it
> ramps toward **90%** near settlement (`RedeemMathV2`), which this tool does not
> reproduce, so redeem/exit figures hold only for early/small pre-settlement sells.

---


## How 42 / Event Rush works

- A **market** has **N outcomes**; each is its own **outcome token** on its own
  **bonding ("power") curve**, collateralised in **USDT** on BNB Chain. One market
  holds all outcomes as **ERC-6909 token ids**.
- **Buy (mint)** adds USDT and moves price up the curve; **sell (redeem)** burns
  tokens back into the curve (subject to the protocol fee and a dynamic
  redemption tax).
- At **resolution** the market settles **parimutuel**: the whole USDT pot is paid
  to winning-token holders pro-rata — `payout_per_unit = total_pool / winning_supply`.

### Production curve (verified against the contracts)

The per-outcome curve is **matched to the on-chain `ft-contracts`** — `PowerCurveSet1`
(`src/curves/config/PowerCurve.sol`) and `PowerMath.sol`:

```
market cap   M(x) = (x + start)^(c1+1) / c2          [= reserve = cumulative USDT staked]
price        p(x) = (c1+1) · (x + start)^c1 / c2
            with c1 = 0.75 (exponent), c2 = 2,000,000 (scale), start = 8.888 tokens
```

Both the **exponent (3/4) and the 2,000,000 scale are real on-chain parameters.**
MMN's `PowerCurve.ft()` reproduces this exactly (`k = (n+1)/c2 = 1.75/2,000,000`),
so absolute USDT figures match the contract above the curve start. **Not modelled**
(documented gaps): the `+start=8.888` offset (negligible above ~thousands of
tokens, divergent near zero); the per-curve-**set** exponent (Set1/Set4 = 0.75,
Set2 = 2/3, Set3 = 0.8); the opening-window **LDA premium** (first ~20s minters pay
up to 5×, `PowerLDACurveV2`); and the post-kink redemption tax (see fees note).
ROI / ownership *multiples* depend only on the exponent and are exact.

> See `docs/adr/0003-curve-calibration.md` and the cross-check in
> `docs/live-analyzer.md`. The 42 settlement is **parimutuel**: a winning outcome's
> holders split the whole pot pro-rata (`payout = ownership × total_pot`).

---

## Offline / hypothetical simulator (legacy)

The original model: *buy the first x% of every outcome's supply, then watch the
market cap grow.* It runs on invented inputs — clearly labelled HYPOTHETICAL in
the report — and is handy for intuition and the Monte Carlo view.

```bash
python -m mmn --outcomes 4 --early-pct 1 --yes
python -m mmn --outcomes 3 --early-pct 0.5 --full-mcap 250000 --house-seed 5 --yes

# SVG charts + Monte Carlo (random house seeds, uneven capital, random winner)
python -m mmn --outcomes 8 --early-pct 1 --monte-carlo --mc-trials 20000 \
    --winner-prior skewed --chart examples/early_buyer.svg --yes
```

Scale-free identities on the modelled curve (no house seed): ownership at
market-cap multiple `M` is `M^(−4/7)`; settlement-win payout/spend is `M^(3/7)`.
With `--house-seed`, the seed is absolute, so ROI/ownership then depend on scale.
Charts and the Monte Carlo write dependency-free SVG (see `examples/`).

---

## Tech stack & architecture

| Layer | Choice |
|-------|--------|
| Runtime / tooling | **uv** (deps + venv), **Python 3.14** (pinned via `.python-version`), **ruff** (lint+format), **ty** (type check) |
| Web | **Quart** (async, Flask-compatible API) on **ASGI**, served by **uvicorn** + **uvloop** |
| Event loop | **uvloop** (best-effort; `mmn/runtime.py` falls back to asyncio) |
| Math engine | standard-library only (`curves`, `simulator`, `montecarlo`, `fees`) |
| Frontend | server-rendered SPA + Chart.js (vendored CDN) |

**Async boundary:** the **CPU-bound** simulator / Monte Carlo run in a worker
thread via `asyncio.to_thread` so they never block the ASGI event loop; the curve
math itself is synchronous and microsecond-fast.

```
request ─▶ Quart handler (async)
            └─ await asyncio.to_thread(simulate / run_montecarlo) ─▶ JSON
```

> The parked live analyzer added an async **httpx/HTTP-2** API client + concurrent
> market fan-out; see [`docs/live-analyzer.md`](docs/live-analyzer.md).

## Commands (uv)

```bash
uv sync                              # install deps + dev tools (Python 3.14)
uv run python -m mmn --outcomes 4 --early-pct 1 --yes   # offline CLI
uv run uvicorn app:app --loop uvloop --port 3000        # web app (or: uv run python app.py)
uv run pytest -q                     # tests (async via pytest-asyncio)
uv run ruff check . && uv run ruff format --check .
uv run ty check                      # type check (first-party source)
```

## Project layout

```
mmn/
  runtime.py       # event-loop selection (uvloop name / asyncio fallback)
  curves.py        # PowerCurve / AffineCurve bonding-curve math (closed-form)
  fees.py          # protocol fee + (approximate) redemption tax model
  simulator.py     # offline "buy first x%" model + parimutuel settlement
  montecarlo.py    # offline MC: random seeds + uneven capital + random winner
  chart.py         # dependency-free SVG charts
  cli.py           # offline CLI (simulator + Monte Carlo)
app.py             # Quart (ASGI) web app: /api/simulate, /api/montecarlo
tests/             # async web tests + CLI/curve/sim/MC math tests
docs/
  adr/0001-async-stack.md      # async stack decision
  adr/0002-park-live-analyzer.md
  live-analyzer.md             # parked live-analyzer spec + rebuild guide
```

## A note on verification

The curve is **cross-checked against the `ft-contracts` Solidity** (the tests
assert `PowerCurve.ft()` reproduces `PowerCurveSet1` + `PowerMath` exactly). What
is **not** reproduced (documented gaps): the `+start` offset, the opening LDA
premium, and the post-kink redemption-tax saturation — so absolute USDT is exact
above the curve start but the earliest mints and late exits are idealised. The
parked live-market analyzer was never validated against the real 42 API; see
[`docs/live-analyzer.md`](docs/live-analyzer.md) and
[`docs/adr/0003-curve-calibration.md`](docs/adr/0003-curve-calibration.md).

## Sources

- [42 — Trade the Future](https://www.42.space/) · [42 Docs](https://docs.42.space/) · [REST API (alpha)](https://docs.42.space/for-developers/rest-api-alpha)
- **`ft-contracts`** — `src/curves/config/PowerCurve.sol`, `src/curves/math/PowerMath.sol`, `src/libraries/RedeemMathV2.sol`, `src/FTMarketV2.sol` (the on-chain ground truth this tool is calibrated to)
