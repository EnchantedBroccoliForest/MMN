# MMN — 42 / Event Rush buyer toolkit

A dependency-free Python tool for analyzing **buyer profitability** on
[42.space](https://www.42.space/) / **Event Rush** markets (the 42-powered dApp
on BNB Chain). It has two modes:

- **Live analyzer (primary)** — pulls a real market's current state from the 42
  REST API and answers practical buyer questions: *if I spend X USDT now, what do
  I get, what do I own, what's my payout if each outcome wins, and what growth do
  I need to break even?*
- **Offline / hypothetical simulator (legacy)** — the original "buy the first x%
  of supply" what-if model. Useful for intuition, but it runs on **invented**
  inputs and is **not** a live market.

> **Fees:** 42's docs describe a **protocol fee (~0.8%)** plus a **dynamic
> redemption tax/spread**. An earlier version of this tool wrongly hard-coded
> "0.2% confirmed" — that claim is gone. The protocol fee now defaults to the
> documented **0.8%** (configurable), and the dynamic redemption tax is **not**
> reproduced exactly, so all redeem/exit figures are clearly flagged
> **approximate**.

---

## Live analyzer (use this for real markets)

```bash
# 1) Discover markets from the 42 API
python -m mmn --list-live --status live

# 2) Analyze a market by address or slug, spending 100 USDT split equally
python -m mmn --market mci-vs-cry-result --budget 100

# 3) Richer plan: reach 2% ownership in each outcome, with your own winner prior
python -m mmn --market 0x42...cd42 --target-ownership 2 --winner-prior 0.5,0.3,0.2

# 4) No network? Analyze a saved JSON snapshot of a market
python -m mmn --market-json examples/sample_market.json --budget 300 --winner-prior skewed
```

### What the live report shows

`[API]` = exact from the 42 API · `[curve]` = exact curve math · `[est]` =
estimate · `[you]` = your assumption.

- **Market summary** and **current outcomes** (price, market cap, minted qty) — `[API]`
- **Buyer plan** — your budget / per-outcome budget / target ownership
- **Expenses** — upfront spend, protocol fee, gas, total invested
- **Ownership after buy** — tokens received and your % of each outcome `[curve]`
- **Settlement payout by winning outcome** — `ownership × total pot`, ROI, and the
  break-even pot per outcome `[curve]`
- **Expected profitability** — under a winner prior (uniform if none given)
- **Exit / redeem** — an **approximate** sell-back value, with a loud caveat that
  42's dynamic redemption tax is not implemented
- **Assumptions & warnings**

### Live flags

| Flag | Meaning |
|------|---------|
| `--list-live` / `--status live\|resolved\|all` / `--limit N` | discover markets |
| `--market REF` | analyze a market by address or slug (REST API) |
| `--market-json PATH` | analyze a saved market snapshot (no network) |
| `--api-base URL` | override the API base (default `https://rest.ft.42.space/api/v1`) |
| `--budget USDT` | total spend, split per `--allocation` |
| `--per-outcome-budget USDT` | fixed spend on each outcome |
| `--target-ownership PCT` | buy until you own PCT% of each outcome |
| `--allocation equal\|custom` + `--weights a,b,c` | how `--budget` is split |
| `--protocol-fee PCT` | protocol fee percent (default **0.8**, documented) |
| `--gas-usd USD` | flat gas cost (default 0) |
| `--redeem-tax-mode documented\|ignore\|manual` + `--manual-redeem-tax PCT` | how the (approximate) redemption tax is applied |
| `--added-capital USDT` | later capital assumed to flow in before resolution |
| `--winner-prior uniform\|skewed\|a,b,c` | winner probabilities for expected ROI |

Network is required for `--list-live` / `--market`; use `--market-json` to run
fully offline against a snapshot (the API client is standard-library `urllib`).

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

### Verified curve (from `EnchantedBroccoliForest/MC_Sim`)

The per-outcome curve, verified against `parimutuel_sim/market.py` (the test
suite asserts an exact match to its `price` / `mcap` / `mint_units` /
`supply_for_mcap`):

```
marginal price   p(x) = x^(3/4) / 2,000,000
market cap       M(x) = (4/7)·x^(7/4) / 2,000,000   = cumulative USDT staked (= reserve)
mint units ($D)  (x^(7/4) + (7/4)·2,000,000·D)^(4/7) − x
```

Market cap is the **cumulative staked** collateral (the pot contribution), **not**
price×supply. The live analyzer mints from each outcome's **current**
`mintedQuantity` and treats the API `marketCap` as the pot.

---

## Offline / hypothetical simulator (legacy)

The original model: *buy the first x% of every outcome's supply, then watch the
market cap grow.* It runs on invented inputs — clearly labelled HYPOTHETICAL in
the report — and is handy for intuition and the Monte Carlo view.

```bash
python -m mmn --offline --outcomes 4 --early-pct 1 --yes
python -m mmn --offline --outcomes 3 --early-pct 0.5 --full-mcap 250000 --house-seed 5 --yes

# SVG charts + Monte Carlo (random house seeds, uneven capital, random winner)
python -m mmn --offline --outcomes 8 --early-pct 1 --monte-carlo --mc-trials 20000 \
    --winner-prior skewed --chart examples/early_buyer.svg --yes
```

Scale-free identities on the verified curve (no house seed): ownership at
market-cap multiple `M` is `M^(−4/7)`; settlement-win payout/spend is `M^(3/7)`.
With `--house-seed`, the seed is absolute, so ROI/ownership then depend on scale.
Charts and the Monte Carlo write dependency-free SVG (see `examples/`).

---

## Run the tests

```bash
pip install pytest
python -m pytest -q
```

## Project layout

```
mmn/
  ft_api.py        # 42 REST client (stdlib urllib; injectable transport for tests)
  fees.py          # protocol fee + (approximate) redemption tax model
  live_simulator.py# live buyer analyzer: spend, ownership, settlement, expected ROI
  live_report.py   # buyer-facing live report + market list
  curves.py        # PowerCurve / AffineCurve bonding-curve math (closed-form)
  simulator.py     # offline "buy first x%" model + parimutuel settlement
  montecarlo.py    # offline MC: random seeds + uneven capital + random winner
  chart.py         # dependency-free SVG charts
  cli.py           # live-first CLI; --offline for the hypothetical model
tests/
  test_ft_api.py     # API parsing, error handling, missing fields (mocked HTTP)
  test_live.py       # allocation, fees, target ownership, settlement, priors, report
  test_curves.py     # closed-form vs integration + EXACT match to MC_Sim formulas
  test_simulator.py  # offline identities (ownership=M^-4/7, win=M^3/7, fees)
  test_montecarlo.py # MC invariants + SVG well-formedness
  test_cli.py        # offline report provenance/labels
```

## A note on verification

This build was assembled in a sandbox **without** network access to
`rest.ft.42.space` or `docs.42.space`, so the live API shape and the exact fee
model could not be empirically re-verified here. The client is written to the
documented contract and parses defensively (multiple key spellings, missing
fields degrade gracefully); adjust `mmn/ft_api.py` `_FIELDS`/spellings and the
`--protocol-fee` default once you confirm against the live API and current docs.
Run a quick `python -m mmn --list-live` from a networked environment to validate.

## Sources

- [42 — Trade the Future](https://www.42.space/) · [42 Docs](https://docs.42.space/) · [REST API (alpha)](https://docs.42.space/for-developers/rest-api-alpha)
- [42 Markets](https://docs.42.space/getting-started/protocol-mechanics-101/42-markets) · [Power curves](https://docs.42.space/getting-started/protocol-mechanics-101/42-power-curves) · [Fees](https://docs.42.space/getting-started/protocol-mechanics-101/fees)
- `EnchantedBroccoliForest/MC_Sim` — `parimutuel_sim/market.py` (verified curve & settlement)
