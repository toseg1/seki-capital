# Seki Capital — broker/investment firm dataset

**Seki Capital** is a fictional mid-size broker/investment firm. This is its
raw, row-level operational data — who its clients are, what it trades, what
happened on the market each day, and every order it ever executed — loaded
into **PostgreSQL** for practice building dashboards in **Metabase**.

It is deliberately just the source-of-truth rows a firm's systems would
actually log: a client book, an instrument master, daily price bars, an FX
table, a fee rate card, and a trade blotter. It follows the table model from
the Data Skills Learning Hub (`clients`, `securities`, `prices`, `trades`),
so the example queries on those pages run against it unchanged.

**There is no positions table, and no pre-built calculated columns or views.**
Nothing this firm's systems wouldn't hand you directly — holdings, average
cost, market value, AUM, per-trade commission, P&L — is stored. `trades` is
the only source of truth for what a client owns, exactly like a real trade
blotter; deriving "what does client X hold today, and what is it worth, and
what would we bill them" with SQL is the point of the exercise. The one
exception is `commission_schedule`: a genuine reference table (the firm's fee
rate card by client segment), not a derived value, so unlike positions it
earns its own table — see [What you'll need to calculate](#what-youll-need-to-calculate).

Everything here has been loaded into PostgreSQL 16 and verified: all six
tables load with strict constraints enabled, and all six data-quality checks
pass.

| Table | Rows | What one row is |
|---|---:|---|
| `clients` | 120 | A client of the firm |
| `securities` | 67 | A tradable instrument |
| `fx_rates` | 3,455 | One currency on one business day |
| `prices` | 46,297 | One instrument's OHLCV bar on one day |
| `trades` | 40,296 | One executed order |
| `commission_schedule` | 3 | One client segment's fee rate and per-ticket minimum |

Coverage: **2024-01-01 → 2026-09-09**, 691 trading days. About 5.2 MB of CSV,
20 MB once loaded into Postgres with indexes.

Those figures are what the default `config.toml` produces. Change the dates
or the sizes there and everything scales accordingly — every run writes
`data/_manifest.json` recording the exact configuration and the row counts it
generated, so you can always tell which settings produced the CSVs you have.

---

## Requirements

- **Python 3.11 or newer.** The generator reads `config.toml` with `tomllib`,
  which entered the standard library in 3.11. No third-party packages are
  needed. Check with `python3 --version`.
- **Docker** (Docker Desktop on macOS or Windows) for the quick start below.

---

## Quick start

### Option A — everything in Docker (recommended)

**Step 1 — generate the dataset.** The CSVs are not committed to this
repository, so this is required, not optional: the database load in step 2
reads them off disk and fails without them. The script creates `data/` for
you and takes about three seconds.

```bash
python3 generate_data.py
```

**Step 2 — start Postgres.**

```bash
docker compose up -d
docker compose logs -f postgres     # watch the load and the checks
```

Postgres builds the schema, loads the CSVs and runs the quality checks on
first start. When you see `Seki Capital is ready.`, the database is up on
`localhost:5432`.

Already running Postgres on port 5432? Change the mapping in
`docker-compose.yml` to `"55432:5432"` and use `55432` from the host instead
(both here and in the Metabase connection settings below).

#### Metabase — run it as its own, separate stack

Metabase is deliberately **not** in the root `docker-compose.yml`. It lives in
[`metabase/docker-compose.yml`](metabase/docker-compose.yml) as its own
compose project (you can also move it outside of this repo to make it even cleaner), 
started once and left running:

```bash
cd metabase
docker compose up -d
```

Open <http://localhost:3000>, create your account (first run only), and add
the database:

| Setting | Value |
|---|---|
| Database type | PostgreSQL |
| Host | **`host.docker.internal`** |
| Port | `5432` |
| Database name | `seki` |
| Username | `seki` |
| Password | `seki` |
| Schemas | `seki` |

> **The one thing that trips everyone up:** the host is `host.docker.internal`,
> not `localhost` or `postgres`. Postgres and Metabase are now two independent
> compose projects with no shared Docker network, so Metabase reaches Postgres
> the same way your own machine does — through the port published on the host.

**Why bother with two stacks?** Regenerating the dataset means wiping
Postgres's volume (`docker compose down -v` in this folder). If Metabase lived
in the same file, that command would also wipe *its* app database — your
account, dashboards and saved questions — forcing you to recreate them from
scratch every time. Keeping Metabase in its own project means it just keeps
running: reload the data underneath it, or point it at a completely different
practice database later, and your Metabase account is untouched either way.

Day to day: `cd metabase && docker compose up -d` once, and leave it running.
`docker compose down` (no `-v`) stops it without losing anything; only
`docker compose down -v` from *inside* `metabase/` would reset your Metabase
account — the root project can never do that to it.

### Option B — your own local PostgreSQL

Run from the **repo root**, because the load script uses relative paths:

```bash
python3 generate_data.py                               # step 1: writes data/*.csv
createdb seki
psql -v ON_ERROR_STOP=1 -d seki -f sql/01_schema.sql
psql -v ON_ERROR_STOP=1 -d seki -f sql/02_load.sql
psql -v ON_ERROR_STOP=1 -d seki -f sql/03_checks.sql   # all rows should say PASS
```

Then point Metabase at `host.docker.internal:5432` (macOS/Windows) if Metabase
is in Docker and Postgres is on the host.

---

## What's in the box

```
seki-capital/
├── config.toml              Every generation parameter — seed, dates, sizes, fees
├── docker-compose.yml       Postgres 16 — the dataset itself
├── metabase/
│   └── docker-compose.yml   Standalone Metabase — its own project/volume
├── docker/init.sh           Runs on first container start
├── generate_data.py         Seeded generator — driven entirely by config.toml
├── data/*.csv               The six tables (generated locally, not committed)
└── sql/
    ├── 01_schema.sql        DDL: keys, constraints, indexes, comments
    ├── 02_load.sql          \copy the CSVs in dependency order
    └── 03_checks.sql        Six data-quality assertions
```

There are no pre-built views — the whole point is for the trainee to write the
joins and aggregations themselves in Metabase's SQL editor.

The schema lives in a `seki` schema, and the database's default
`search_path` is set to it, so `SELECT * FROM trades` works without qualifying
anything.

---

## The data model

```
clients ─────┐                    securities ─────┬──── prices
    │        │                                    │       (price_date, ticker)
    │        └──── trades ────────────────────────┤
    │                (trade_date, ticker) ─────────┴──── FK into prices
    │
    └──── segment ──── commission_schedule

fx_rates (rate_date, currency)  ── used to value everything in USD
```

`trades` is the only fact table. Everything else — clients, securities,
`fx_rates` and `commission_schedule` — is reference data. `commission_schedule`
joins on `clients.segment`, not a foreign key (a client's segment is a value,
not an id), so nothing stops it from silently dropping a segment that has no
matching row — that's exactly what check #6 in `03_checks.sql` guards against.

Two design decisions worth knowing about:

**Currency.** Instruments are quoted in their home currency — `prices.close_px`
and `trades.price` are in EUR for `TTE`, CHF for `NESN`, JPY for `7203`, and so
on. Summing those across instruments would be meaningless, so `fx_rates` carries
a daily rate into USD — join to it and multiply to get a USD figure that's safe
to sum. `USD` is present in `fx_rates` with a rate of exactly `1.0`, so joins
never need a special case.

**Holdings are not stored, they're derived.** What a client owns as of any
date is the running net of BUY and SELL quantities in `trades` for that
client/ticker, and its average cost is the running weighted average of the
BUY prices. Check #2 in `03_checks.sql` validates the "never negative"
invariant directly against `trades` — reproducing that same running-net logic
in SQL is the core exercise this dataset is built around.

### Deliberate quirks

These are intentional, not bugs — they give you something to demonstrate:

- **7 clients have never traded.** They only appear if you `LEFT JOIN` from
  `clients`. An `INNER JOIN` silently loses them.
- **Some securities are never traded by anyone**, so the same asymmetry exists
  on the securities side.
- **A client's running net quantity in a ticker can fall back to zero** after
  a full exit. Filter those out when you derive "current holdings" — a real
  positions table would never show a flat position either.
- **August and late December are quiet; quarter-ends are busy.** Seasonality is
  built in, so the monthly time series has a shape rather than being flat noise.

---

## What you'll need to calculate

There is no positions table and no pre-built views. These are the queries
you'll write yourself in Metabase's SQL editor (or as custom columns/
aggregations in the notebook editor) to get to the dashboards below.

| You want | Build it from |
|---|---|
| Current quantity held, per client/ticker | `trades`, `SUM(CASE WHEN side='BUY' THEN quantity ELSE -quantity END)` grouped by `client_id, ticker`, filtered to `HAVING SUM(...) > 0` to drop closed-out positions |
| Average cost, per client/ticker | Weighted average of BUY-side trades only: `SUM(price * quantity) / SUM(quantity)` over `side = 'BUY'` rows, grouped by `client_id, ticker` (a stretch version resets the running average to zero whenever quantity hits zero, for clients who fully exited and rebought) |
| `market_value_usd` for a holding | join the quantity above to `prices` (latest `price_date`) and `fx_rates` (on `currency`, same date) → `quantity * close_px * rate_to_usd` |
| `notional_usd` for a trade | `trades` ⋈ `securities` ⋈ `fx_rates` (on `currency`, `trade_date` = `rate_date`) → `quantity * price * rate_to_usd` |
| `cost_basis_usd` for a holding | `quantity * avg_cost * rate_to_usd` (same joins as market value) |
| `unrealised_pnl_usd` | `market_value_usd - cost_basis_usd` |
| Client AUM | `SUM(market_value_usd)` across a client's current holdings |
| `commission_usd` for a trade | join `trades` ⋈ `clients` (for `segment`) ⋈ `commission_schedule` (on `segment`) → `GREATEST(min_usd, notional_usd * bps / 10000)` |
| Net client flow | signed notional: `+notional_usd` on `BUY`, `-notional_usd` on `SELL` |

`sql/03_checks.sql` shows a working example of the running-net-quantity logic
if you get stuck — it computes it to validate the data, it just never stores
the result.

---

## Dashboard ideas that hold up in an interview

Boring dashboards get boring questions. These force a real answer:

1. **AUM and net flow by month** — line for calculated client AUM (sum of
   `market_value_usd`, derived from `trades` as of each month-end), bars for
   net flow. Shows you understand that a book can grow while clients
   withdraw.
2. **Sector allocation drift** — stacked area of `market_value_usd` by sector,
   recomputed at each month-end from the running position. Was the shift from
   flows, or from prices moving?
3. **Client leaderboard** — one row per client, sorted by calculated
   `unrealised_pnl_usd`, with `trade_count` alongside (`LEFT JOIN` from
   `clients` so the never-traded ones show up too). The most-traded accounts
   are usually not the best-performing ones.
4. **Commission realisation by segment** — calculated `commission_usd`
   (joined through `commission_schedule`), summed or averaged as bps of
   notional, grouped by segment. The pricing tiers live in a table you have
   to join to, not a column you can just group by — closer to how a real fee
   analysis works.
5. **Drawdown chart** — cumulative return computed from `prices.close_px`
   with a window function. There are three engineered drawdowns (Aug 2024,
   Apr 2025, Feb 2026), the largest about −16% on an equal-weighted index.
6. **Trade price vs daily range** — scatter of execution price against that
   day's high/low. Every trade sits inside its bar; that is check #1.

---

## Regenerating

Every parameter lives in [`config.toml`](config.toml) — the seed, the date
range, how many clients and trades, the price and FX models, the client mix,
and the fee rate card. The generator is seeded, so the same config always
produces the same dataset, byte for byte.

```bash
python3 generate_data.py                                  # uses config.toml
python3 generate_data.py --clients 500                    # CLI overrides the file
python3 generate_data.py --config scenarios/large.toml    # a different scenario
```

Precedence is **command line > config file > built-in default**. The flags
`--clients`, `--trades-per-day`, `--out` and `--config` are the only ones;
anything else is a value in the file.

| To change | Where |
|---|---|
| A different random draw, same shape | `seed` under `[run]` |
| Date range and number of trading days | `start_date`, `end_date` under `[run]` |
| Number of clients, trades per day | `[run]`, or the matching CLI flag |
| Volatility, drift, engineered drawdowns | `[market]` |
| Currencies and their volatility | `[fx]` |
| Country and segment mix, dormant share, mandate sizes | `[clients]` |
| Ticket sizes, buy/sell balance, seasonality | `[trades]` |
| Commission rates and per-ticket minimums | `[fees]` |

One caveat worth knowing: randomness is consumed in the order the file is
read, so **reordering** keys inside a table (the countries, the segments, the
currencies) changes the dataset even when the seed does not. Changing values
is safe; reordering is a deliberate act.

The instrument list, the five documented hub clients and the name pools are
deliberately *not* in the config — they are fixture data rather than
parameters, and they stay in `generate_data.py` where they read as a table.

After regenerating, reload. With Docker that means wiping Postgres's volume,
since the init script only runs on a fresh data directory — this resets the
dataset only, not your Metabase account, since Metabase lives in its own
compose project (see [Metabase — run it as its own, separate
stack](#metabase--run-it-as-its-own-separate-stack)):

```bash
python3 generate_data.py
docker compose down -v && docker compose up -d
```

Standard library only — no dependencies. Runs in about 3 seconds at the
default size.

---

## Data quality checks

`sql/03_checks.sql` returns six rows, all of which must say `PASS`:

| # | Check |
|---|---|
| 1 | Every execution price sits inside that day's low/high range |
| 2 | No client ever holds a negative quantity (running net of trades) |
| 3 | No trade occurs before the client onboarded |
| 4 | Every security has a price on every trading day |
| 5 | FX is complete and USD is exactly 1.0 |
| 6 | Every client segment has a `commission_schedule` entry |

Run them after any regeneration. Being able to say "I wrote tests for my test
data" is a better answer than "I trusted the script".

---

## A note on realism

Prices come from a factor model — a market factor with volatility clustering and
three engineered drawdowns, a daily sector factor, and per-security idiosyncratic
noise with a beta between 0.6 and 1.55. Over the 2.7-year window the median
instrument returns about +45% with roughly 25% annualised volatility, and the
spread runs from −33% to +320%. Sectors move together, which they should.

Instrument names and tickers are real large caps so the data reads naturally,
but **every number is synthetic**. Do not present these as actual market prices.

---

## Questions / feedback

This is a personal project shared for anyone practicing SQL and Metabase.
Found a bug in the data, have a suggestion, or built something cool with it?
Reach out at **theoseguin.data@gmail.com**.
