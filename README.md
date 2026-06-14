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

### The model

Per-outcome bonding curve, instantaneous price at circulating supply `s`:

```
power curve:   p(s) = k · s^n          (n = exponent, k = coefficient)
affine curve:  p(s) = m · s + b        (alternative shape)
```

Everything else is derived from the integral of the price:

| Quantity            | Power curve                         |
|---------------------|-------------------------------------|
| reserve (locked USDT) `R(s)` | `k/(n+1) · s^(n+1)`        |
| spot market cap `M(s)`       | `p(s)·s = k·s^(n+1) = (n+1)·R(s)` |
| cost to mint `a → b`         | `R(b) − R(a)`              |
| redeem proceeds `b → a`      | `R(b) − R(a)`              |

**Step 1–2 (spend).** Buying the first **x%** of supply means buying tokens
`q = x% · total_supply`. Spend per outcome = `R(0 → q)`; total spend =
`N · R(0 → q)` (× `1 + buy_fee`).

**Step 3 (growth).** Stages are **market-cap multiples** of your entry market
cap `M(q)`. At multiple `M`, supply rises to `s = q · M^(1/(n+1))`, so for a
power curve:

- **% ownership** = `q / s = M^(−1/(n+1))` — your stake dilutes as others buy.
- **spot value** (mark-to-market) = `q · p(s) = M(q) · M^(n/(n+1))`.
- **redeem value** (realisable) = USDT from selling your `q` tokens back into
  the curve = `R(s) − R(s−q)`. This is what you could actually cash out.
- **settlement payout** (if it resolves here and your outcome wins) =
  `ownership × total_pot`, where `total_pot = N · R(s)`.

---

## Usage

No third-party dependencies are required to run it (Python 3.9+).

```bash
# Interactive — prompts for outcomes, x%, curve params, multiples
python -m mmn

# Non-interactive
python -m mmn --outcomes 4 --early-pct 1 --yes

# Override the curve / fees / growth stages
python -m mmn --outcomes 3 --early-pct 0.5 \
    --curve power --exponent 1 --total-supply 1e9 --mcap-at-full 100000 \
    --buy-fee 0.005 --sell-fee 0.005 \
    --multiples "1 2 5 10 50 100 1000" --yes
```

### Run the tests

```bash
pip install pytest
python -m pytest -q
```

---

## ⚠️ Plug in 42's real constants

The curve constants in `mmn/cli.py` (`DEFAULTS`) are **placeholders** chosen to
produce readable round numbers — they are **not** 42's on-chain values. The
**math is exact**; only the constants need to be real for the output to be
42-accurate. Replace them with the verified contract's parameters:

- `exponent` (n) and `coefficient` (k) — or `total_supply` + `mcap_at_full`
- `buy_fee`, `sell_fee` (spread)
- pick `--curve affine` (slope `m`, base `b`) if 42's curve is linear-with-base

> The verified 42 contracts live on BscScan (collateral = USDT
> `0x55d3...7955`). I was unable to fetch them from this sandbox (network egress
> is blocked), so paste the contract's `buy`/`sell` pricing function + constants
> and the defaults can be set exactly.

---

## Project layout

```
mmn/
  curves.py      # PowerCurve / AffineCurve bonding-curve math (closed-form)
  simulator.py   # spend, growth stages, ownership, P&L, parimutuel settlement
  cli.py         # interactive + flag-driven front-end and report rendering
  __main__.py    # `python -m mmn`
tests/
  test_curves.py     # closed-form vs numerical integration + identities
  test_simulator.py  # economic identities (ownership law, settlement, fees)
```

## Sources

- [42 — Trade the Future](https://www.42.space/)
- [42 Docs — 42 Markets](https://docs.42.space/getting-started/protocol-mechanics-101/42-markets)
- [Binance Wallet Event Rush turns on-chain events into tradable markets — crypto.news](https://crypto.news/binance-wallet-event-rush-turns-on-chain-events-into-tradable-markets/)
- [Binance Wallet Launches Event Rush — DailyCoin](https://dailycoin.com/binance-wallet-event-rush-trade-real-world-events)
- [42 V2 Launches on BNB Chain introducing Eventcoins — BlockchainReporter](https://blockchainreporter.net/42-v2-launches-on-bnb-chain-introducing-eventcoins-as-a-new-tradable-asset-class)
