# 42 / Event Rush — Early-Buyer Profitability Simulator

A small, dependency-free Python tool that models the profitability and ownership
of being an **early buyer** on a [42.space](https://www.42.space/) /
**Event Rush** market (the 42-powered dApp in Binance Wallet on BNB Chain).

It answers the three questions:

1. **How many outcomes** are in the market?
2. If you buy **x% of the earliest part of every outcome's bonding curve**, how
   much do you **spend in total**?
3. As the **market cap of every outcome grows**, what is your **profitability**
   and **% ownership** at each stage?

The bonding-curve math is closed-form and **cross-checked against numerical
integration** in the test suite, so the numbers are exact for the parameters you
give it.

---

## How 42 / Event Rush works (the mechanism this models)

Sourced from 42's docs and Event Rush coverage (links at the bottom):

- A **market** has **N possible outcomes**.
- Each outcome is its own **outcome token** (eventcoin) on its **own bonding
  curve** (the docs call it a *power curve*), collateralised in **USDT** on BSC.
- **Buy (mint):** you add USDT, the curve mints tokens to you and the price
  moves **up** the curve. **Sell (redeem):** you burn tokens back into the curve,
  receive USDT from the reserve, and the price moves **down**.
- Trading is **continuous** — price reflects relative supply / where capital is
  flowing, not a fixed probability. You can exit any time **before** resolution
  by selling back into the curve.
- At **resolution** the market settles to a **single winning outcome**
  (**parimutuel**): all USDT collateral locked in the **losing** outcomes is
  pooled and paid out **pro-rata to holders of the winning token**. Your payout
  on a win = `your share of the winning token × total USDT pot`.

### Confirmed from 42 (contracts + MC_Sim)

Corroborated by 42's contract interfaces (`IFTMarketV2`, `IFTCurve`) **and the
exact formulas in `EnchantedBroccoliForest/MC_Sim`** (`parimutuel_sim/market.py`):

- **Collateral = USDT** (BEP-20, 18 decimals); one market holds every outcome as
  an **ERC-6909 token id**.
- **Production curve (exact):** marginal price `p(x) = x^(3/4) / 2,000,000`.
- **Market cap = cumulative USDT staked** in an outcome
  `= (4/7)·x^(7/4) / 2,000,000` (equal to the bonding-curve reserve — **not**
  price×supply).
- **Buy** = `mintCollateralToExactOt`, **Sell** = `redeemExactOtToCollateral`;
  **fee = 0.2% per side** to treasury.
- **Settlement = parimutuel:** `payout_per_unit = total_pool / winning_supply`,
  so winning-token holders split the whole USDT pot pro-rata.
- Each outcome may carry a small **house seed** of initial market cap.

The curve and fee are therefore 42's **real production values**, not placeholders.
The only free parameter is the **dollar scale** (`--full-mcap`, a reference market
cap per outcome); ROI and ownership are independent of it.

### The model

42's per-outcome production curve, marginal price at supply `x`:

```
p(x) = x^(3/4) / 2,000,000          (a power curve: k = 1/2,000,000, n = 3/4)
```

Derived quantities (with `n = 3/4`, so `n+1 = 7/4`):

| Quantity            | Formula                                   |
|---------------------|-------------------------------------------|
| **market cap** = cumulative USDT staked `M(x)` | `(4/7)·x^(7/4) / 2,000,000` |
| cost to mint `a → b`         | `M(b) − M(a)`                    |
| redeem proceeds `b → a`      | `M(b) − M(a)`                    |
| mint units for `$D` from `x` | `(x^(7/4) + (7/4)·2,000,000·D)^(4/7) − x` |

(`market cap = reserve` here — this is the parimutuel pot contribution, not
price×supply.)

**Step 1–2 (spend).** Buying the first **x%** of supply means `q = x% · S` units
(`S` set by `--full-mcap`). Spend per outcome = `M(0 → q)` × `(1 + 0.2%)`; total
spend = `N ×` that.

**Step 3 (growth).** Stages are **market-cap multiples** of your entry market cap.
At multiple `M` the supply rises to `s = q · M^(4/7)`, giving these **scale-free**
results (true for any `--full-mcap`):

- **% ownership** = `q / s = M^(−4/7)` — your stake dilutes as others stake.
- **redeem value** (sell back into the curve) = `M(s) − M(s−q)`, times `1 − 0.2%`.
- **settlement (win) payout** = `ownership × total_pot` with `total_pot = N · M(s)`;
  payout / spend = **`M^(3/7)`**.

---

## Usage

No third-party dependencies are required to run it (Python 3.9+).

```bash
# Interactive — prompts for outcomes, x%, reference market cap, multiples
python -m mmn

# Non-interactive (defaults to 42's confirmed curve + 0.2% fee)
python -m mmn --outcomes 4 --early-pct 1 --yes

# Tune the scenario
python -m mmn --outcomes 3 --early-pct 0.5 \
    --full-mcap 250000 --house-seed 5 \
    --multiples "1 2 5 10 50 100 1000" --yes

# Write SVG charts + run the Monte Carlo
python -m mmn --outcomes 8 --early-pct 1 --monte-carlo --mc-trials 20000 \
    --winner-prior skewed --chart examples/early_buyer.svg --yes
```

## Charts & Monte Carlo

- **`--chart PATH.svg`** writes a dependency-free SVG (renders on GitHub / any
  browser): two panels — your **% ownership** and your **return multiple**
  (sell-back and settlement) vs market-cap growth. See
  [`examples/early_buyer.svg`](examples/early_buyer.svg).
- **`--monte-carlo`** samples the realistic picture the deterministic table
  can't: a random **house seed** per outcome (Uniform 0.10–10 USDT, MC_Sim's
  range), **uneven later capital** (favourites attract more, via a Dirichlet
  split around the winner prior), and a **random winner**. Because you hold the
  same early slice of *every* outcome, your settlement payout is
  `ownership_in_winner × total_pot` — a distribution, reported as mean / median /
  5th / 95th percentile and P(profit). With `--chart` it also writes a histogram
  ([`examples/early_buyer-montecarlo.svg`](examples/early_buyer-montecarlo.svg)).

  Knobs: `--mc-trials`, `--mc-mean-pool`, `--pool-sigma`, `--concentration`,
  `--seed-min/--seed-max`, `--winner-prior {uniform|skewed|comma-list}`, `--mc-seed`.

### Run the tests

```bash
pip install pytest
python -m pytest -q
```

---

## Calibration

The curve (`p(x) = x^(3/4)/2,000,000`) and fee (0.2%/side) in `mmn/cli.py`
(`DEFAULTS`) are 42's **confirmed production values**, verified against
`EnchantedBroccoliForest/MC_Sim` (`parimutuel_sim/market.py`) — the test suite
asserts an exact match to its `price` / `mcap` / `mint_units` / `supply_for_mcap`.

The only thing you set is the **dollar scale**:

- `--full-mcap` — a reference market cap per outcome (defaults to 100,000 USDT)
- `--house-seed` — optional initial market cap the house seeds each outcome with

ROI and ownership are **scale-free**, so they're exact regardless of `--full-mcap`.

---

## Project layout

```
mmn/
  curves.py      # PowerCurve / AffineCurve bonding-curve math (closed-form)
  simulator.py   # spend, growth stages, ownership, P&L, parimutuel settlement
  montecarlo.py  # random seeds + uneven capital + random winner -> ROI distribution
  chart.py       # dependency-free SVG charts (ownership/ROI + MC histogram)
  cli.py         # interactive + flag-driven front-end and report rendering
  __main__.py    # `python -m mmn`
tests/
  test_curves.py      # closed-form vs integration + EXACT match to MC_Sim formulas
  test_simulator.py   # economic identities (ownership=M^-4/7, win=M^3/7, fees, scale-free)
  test_montecarlo.py  # MC invariants + SVG well-formedness
```

## Sources

- [42 — Trade the Future](https://www.42.space/)
- [42 Docs — 42 Markets](https://docs.42.space/getting-started/protocol-mechanics-101/42-markets)
- [Binance Wallet Event Rush turns on-chain events into tradable markets — crypto.news](https://crypto.news/binance-wallet-event-rush-turns-on-chain-events-into-tradable-markets/)
- [Binance Wallet Launches Event Rush — DailyCoin](https://dailycoin.com/binance-wallet-event-rush-trade-real-world-events)
- [42 V2 Launches on BNB Chain introducing Eventcoins — BlockchainReporter](https://blockchainreporter.net/42-v2-launches-on-bnb-chain-introducing-eventcoins-as-a-new-tradable-asset-class)
- `EnchantedBroccoliForest/MC_Sim` — `parimutuel_sim/market.py` (exact curve & settlement)
