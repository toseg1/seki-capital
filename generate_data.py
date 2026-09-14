#!/usr/bin/env python3
"""
Seki Capital - synthetic dataset generator.

Produces six internally consistent CSV files of raw, row-level data for a
fictional broker/investment firm - Seki Capital - matching the table model
used in the Data Skills Learning Hub:

    clients, securities, prices, trades   (+ fx_rates and commission_schedule,
    two small reference tables)

There is no positions table and no calculated columns (market_value,
aum_usd, holdings, commission...). Everything past the raw rows and the two
reference tables - current holdings, average cost, market value, AUM,
per-trade commission, P&L - is something the trainee derives themselves with
SQL in Metabase. `trades` is the only source of truth for what a client owns,
and commission is never stored per trade: only the fee schedule
(commission_schedule) is, exactly like a real firm would only keep the rate
card, not a pre-computed number on every ticket.

Design rules that make the data hold together:
  * Prices are a factor model (market + sector + idiosyncratic), so sectors
    correlate and OHLC bars are internally valid.
  * Every trade happens on a day the instrument actually traded, and its
    execution price sits inside that day's low/high range.
  * Nobody sells stock they do not hold. A running per-client-per-ticker book
    is tracked internally as trades are generated purely to enforce that -
    it is not exported. Reproducing it in SQL (a running net of BUY/SELL,
    partitioned by client and ticker, ordered by date) is the core exercise.

Deterministic: the same config.toml gives the same dataset every time.

All generation parameters live in config.toml; this module keeps only the
fixture data (the instrument list, the documented hub clients, the name
pools), which is reference material rather than something you tune per run.

Usage:
    python3 generate_data.py                       # reads config.toml
    python3 generate_data.py --clients 500         # CLI overrides the file
    python3 generate_data.py --config scenarios/large.toml
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import random
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

try:
    import tomllib                     # standard library, Python 3.11+
except ModuleNotFoundError:            # Python 3.10 and older
    import tomli as tomllib            # pip install tomli

# --------------------------------------------------------------------------
# Fixture data
#
# Every tunable parameter lives in config.toml. What stays below is reference
# material: the tradable universe, the five clients documented in the Learning
# Hub, and the name pools used to invent the rest.
# --------------------------------------------------------------------------

CONFIG_PATH = Path(__file__).parent / "config.toml"

EXCHANGE_CCY = {
    "NASDAQ": "USD", "NYSE": "USD", "EPA": "EUR", "XETR": "EUR",
    "AMS": "EUR", "BIT": "EUR", "BME": "EUR", "LSE": "GBP",
    "SIX": "CHF", "TSE": "JPY",
}

# (ticker, name, sector, exchange, starting price in local currency, size tier)
# The first five are the exact rows documented in the Learning Hub, so every
# example query on those pages returns data against this database.
SECURITIES = [
    ("AAPL", "Apple Inc.",              "Technology",             "NASDAQ", 185.0,  3),
    ("MSFT", "Microsoft Corp.",         "Technology",             "NASDAQ", 375.0,  3),
    ("JPM",  "JPMorgan Chase",          "Financials",             "NYSE",   170.0,  3),
    ("TTE",  "TotalEnergies SE",        "Energy",                 "EPA",     62.0,  2),
    ("NESN", "Nestle SA",               "Staples",                "SIX",     97.0,  2),

    ("NVDA", "NVIDIA Corp.",            "Technology",             "NASDAQ", 495.0,  3),
    ("GOOGL","Alphabet Inc.",           "Communication Services", "NASDAQ", 140.0,  3),
    ("AMZN", "Amazon.com Inc.",         "Consumer Discretionary", "NASDAQ", 152.0,  3),
    ("META", "Meta Platforms Inc.",     "Communication Services", "NASDAQ", 355.0,  3),
    ("AVGO", "Broadcom Inc.",           "Technology",             "NASDAQ", 112.0,  3),
    ("ADBE", "Adobe Inc.",              "Technology",             "NASDAQ", 600.0,  2),
    ("CRM",  "Salesforce Inc.",         "Technology",             "NYSE",   265.0,  2),
    ("ORCL", "Oracle Corp.",            "Technology",             "NYSE",   105.0,  2),
    ("CSCO", "Cisco Systems Inc.",      "Technology",             "NASDAQ",  50.0,  2),
    ("INTC", "Intel Corp.",             "Technology",             "NASDAQ",  48.0,  2),
    ("AMD",  "Advanced Micro Devices",  "Technology",             "NASDAQ", 148.0,  2),
    ("TXN",  "Texas Instruments",       "Technology",             "NASDAQ", 170.0,  2),
    ("QCOM", "Qualcomm Inc.",           "Technology",             "NASDAQ", 145.0,  2),

    ("BAC",  "Bank of America Corp.",   "Financials",             "NYSE",    33.0,  3),
    ("WFC",  "Wells Fargo & Co.",       "Financials",             "NYSE",    49.0,  2),
    ("GS",   "Goldman Sachs Group",     "Financials",             "NYSE",   385.0,  2),
    ("MS",   "Morgan Stanley",          "Financials",             "NYSE",    93.0,  2),
    ("AXP",  "American Express Co.",    "Financials",             "NYSE",   187.0,  2),
    ("BLK",  "BlackRock Inc.",          "Financials",             "NYSE",   811.0,  2),
    ("V",    "Visa Inc.",               "Financials",             "NYSE",   260.0,  3),
    ("MA",   "Mastercard Inc.",         "Financials",             "NYSE",   426.0,  3),

    ("XOM",  "Exxon Mobil Corp.",       "Energy",                 "NYSE",   100.0,  3),
    ("CVX",  "Chevron Corp.",           "Energy",                 "NYSE",   149.0,  2),
    ("COP",  "ConocoPhillips",          "Energy",                 "NYSE",   116.0,  2),
    ("SLB",  "Schlumberger NV",         "Energy",                 "NYSE",    52.0,  1),
    ("SHEL", "Shell plc",               "Energy",                 "LSE",   2570.0,  2),
    ("BP",   "BP plc",                  "Energy",                 "LSE",    465.0,  1),

    ("JNJ",  "Johnson & Johnson",       "Healthcare",             "NYSE",   157.0,  3),
    ("UNH",  "UnitedHealth Group",      "Healthcare",             "NYSE",   526.0,  3),
    ("LLY",  "Eli Lilly & Co.",         "Healthcare",             "NYSE",   583.0,  3),
    ("PFE",  "Pfizer Inc.",             "Healthcare",             "NYSE",    28.0,  2),
    ("MRK",  "Merck & Co.",             "Healthcare",             "NYSE",   109.0,  2),
    ("ABBV", "AbbVie Inc.",             "Healthcare",             "NYSE",   155.0,  2),
    ("NOVN", "Novartis AG",             "Healthcare",             "SIX",     90.0,  2),
    ("ROG",  "Roche Holding AG",        "Healthcare",             "SIX",    245.0,  2),
    ("SAN",  "Sanofi SA",               "Healthcare",             "EPA",     90.0,  2),
    ("AZN",  "AstraZeneca plc",         "Healthcare",             "LSE",  10560.0,  2),

    ("PG",   "Procter & Gamble Co.",    "Staples",                "NYSE",   146.0,  3),
    ("KO",   "Coca-Cola Co.",           "Staples",                "NYSE",    59.0,  2),
    ("PEP",  "PepsiCo Inc.",            "Staples",                "NASDAQ", 170.0,  2),
    ("WMT",  "Walmart Inc.",            "Staples",                "NYSE",    52.0,  3),
    ("COST", "Costco Wholesale Corp.",  "Staples",                "NASDAQ", 660.0,  2),
    ("UL",   "Unilever plc",            "Staples",                "LSE",   3820.0,  2),
    ("OR",   "L'Oreal SA",              "Staples",                "EPA",    450.0,  2),

    ("HD",   "Home Depot Inc.",         "Consumer Discretionary", "NYSE",   347.0,  2),
    ("MCD",  "McDonald's Corp.",        "Consumer Discretionary", "NYSE",   297.0,  2),
    ("NKE",  "Nike Inc.",               "Consumer Discretionary", "NYSE",   108.0,  2),
    ("MC",   "LVMH SE",                 "Consumer Discretionary", "EPA",    733.0,  2),
    ("RMS",  "Hermes International",    "Consumer Discretionary", "EPA",   1925.0,  1),

    ("CAT",  "Caterpillar Inc.",        "Industrials",            "NYSE",   296.0,  2),
    ("BA",   "Boeing Co.",              "Industrials",            "NYSE",   261.0,  2),
    ("HON",  "Honeywell International", "Industrials",            "NASDAQ", 210.0,  2),
    ("SIE",  "Siemens AG",              "Industrials",            "XETR",   169.0,  2),
    ("AIR",  "Airbus SE",               "Industrials",            "EPA",    140.0,  2),
    ("ASML", "ASML Holding NV",         "Technology",             "AMS",    755.0,  3),

    ("LIN",  "Linde plc",               "Materials",              "NASDAQ", 411.0,  2),
    ("BHP",  "BHP Group Ltd",           "Materials",              "LSE",   2340.0,  2),
    ("NEE",  "NextEra Energy Inc.",     "Utilities",              "NYSE",    61.0,  2),
    ("IBE",  "Iberdrola SA",            "Utilities",              "BME",     11.9,  2),
    ("ENEL", "Enel SpA",                "Utilities",              "BIT",      6.7,  1),
    ("7203", "Toyota Motor Corp.",      "Consumer Discretionary", "TSE",   2600.0,  2),
    ("6758", "Sony Group Corp.",        "Technology",             "TSE",  13400.0,  2),
]

# The first five clients are the exact rows documented in the Learning Hub.
HUB_CLIENTS = [
    ("C001", "Aurora Pension Fund",   "FR", "Institutional", date(2018, 3, 14)),
    ("C002", "Beaumont Family Office","FR", "Private",       date(2020, 11, 2)),
    ("C003", "Castellan Insurance",   "DE", "Institutional", date(2016, 7, 21)),
    ("C004", "Delacroix Wealth",      "CH", "Private",       date(2019, 9, 4)),
    ("C005", "Eurofin Asset Mgmt",    "LU", "Wholesale",     date(2021, 5, 30))
]

CLIENT_PREFIX = [
    "Aurora", "Beaumont", "Castellan", "Delacroix", "Eurofin", "Fairmont", "Granville",
    "Helvetia", "Ironbridge", "Jourdain", "Kingsley", "Lauterbrunnen", "Meridian",
    "Northgate", "Oakhaven", "Pemberton", "Quintessa", "Rothbury", "Stavanger", "Thornfield",
    "Ullswater", "Valmont", "Westbourne", "Ysbrand", "Zermatt", "Ardenne", "Blackwood",
    "Cavendish", "Dunmore", "Elmsworth", "Fontenay", "Glencairn", "Harrowgate", "Inverness",
    "Joliette", "Kaltenbach", "Langeais", "Montclair", "Norbury", "Ostend", "Perreaux",
    "Quiberon", "Ravenscroft", "Sandhurst", "Trevelyan", "Uppsala", "Verbier", "Wexford",
    "Yvoire", "Zetland", "Alderney", "Brantome", "Chamonix", "Draycott", "Estaing",
    "Fitzwilliam", "Gstaad", "Hohenzollern", "Illkirch", "Josselin",
]
CLIENT_SUFFIX = {
    "Institutional": ["Pension Fund", "Insurance", "Retirement Trust", "Endowment",
                      "Superannuation", "Foundation", "Provident Fund"],
    "Private":       ["Family Office", "Wealth", "Private Holdings", "Capital Partners",
                      "Trust", "Estates"],
    "Wholesale":     ["Asset Mgmt", "Investment Managers", "Capital", "Fund Services",
                      "Advisers", "Partners LLP"],
}

# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Config:
    """Everything config.toml supplies, resolved against the command line."""
    seed: int
    start_date: date
    end_date: date
    n_clients: int
    trades_per_day: int
    out_dir: Path
    market: dict
    fx: dict
    clients: dict
    trades: dict
    fees: dict
    source: Path


def load_config(path: Path = CONFIG_PATH, *, clients: int | None = None,
                trades_per_day: int | None = None, out: Path | None = None) -> Config:
    """Read config.toml. Command line beats the file; the file beats nothing."""
    try:
        with path.open("rb") as fh:
            raw = tomllib.load(fh)
    except FileNotFoundError:
        raise SystemExit(f"config not found: {path}")
    except tomllib.TOMLDecodeError as exc:
        raise SystemExit(f"{path} is not valid TOML: {exc}")

    try:
        run = raw["run"]
        cfg = Config(
            seed=run["seed"],
            start_date=run["start_date"],
            end_date=run["end_date"],
            n_clients=run["clients"] if clients is None else clients,
            trades_per_day=run["trades_per_day"] if trades_per_day is None else trades_per_day,
            out_dir=Path(out) if out else Path(__file__).parent / run["out_dir"],
            market=raw["market"], fx=raw["fx"], clients=raw["clients"],
            trades=raw["trades"], fees=raw["fees"], source=path,
        )
    except KeyError as exc:
        raise SystemExit(f"{path.name} is missing required key: {exc}")

    validate(cfg)
    return cfg


def validate(cfg: Config) -> None:
    """Fail loudly and specifically, instead of with an IndexError 200 lines in."""
    errs = []

    if cfg.end_date <= cfg.start_date:
        errs.append(f"end_date ({cfg.end_date}) must be after start_date ({cfg.start_date})")
    if cfg.n_clients < len(HUB_CLIENTS):
        errs.append(f"clients must be at least {len(HUB_CLIENTS)} (the documented hub clients)")
    if cfg.trades_per_day < 1:
        errs.append("trades_per_day must be at least 1")

    segments = set(cfg.clients["segments"])
    for name, table in (("fees", cfg.fees),
                        ("clients.aum.centre", cfg.clients["aum"]["centre"]),
                        ("clients.mandate", cfg.clients["mandate"])):
        if set(table) != segments:
            errs.append(f"[{name}] keys {sorted(table)} do not match "
                        f"the segments {sorted(segments)}")
    missing_suffix = segments - set(CLIENT_SUFFIX)
    if missing_suffix:
        errs.append(f"no name suffixes defined for segment(s): {sorted(missing_suffix)}")

    if set(cfg.fx["base"]) != set(cfg.fx["vol"]):
        errs.append("[fx.base] and [fx.vol] must list the same currencies")
    if cfg.fx["base"].get("USD") != 1.0 or cfg.fx["vol"].get("USD") != 0.0:
        errs.append("USD must be present with base 1.0 and vol 0.0 (data-quality check #5)")
    unpriced = set(EXCHANGE_CCY.values()) - set(cfg.fx["base"])
    if unpriced:
        errs.append(f"[fx.base] has no rate for currency/currencies: {sorted(unpriced)}")

    if not 0.0 <= cfg.clients["dormant_rate"] < 1.0:
        errs.append("clients.dormant_rate must be in [0, 1)")
    if cfg.clients["onboard_to"] <= cfg.clients["onboard_from"]:
        errs.append("clients.onboard_to must be after clients.onboard_from")
    for seg, bounds in cfg.clients["mandate"].items():
        if len(bounds) != 2 or bounds[0] > bounds[1]:
            errs.append(f"clients.mandate.{seg} must be [min, max] with min <= max")

    for w in cfg.market["shock"]["windows"]:
        if not cfg.start_date <= w["start"] <= cfg.end_date:
            errs.append(f"drawdown window {w['start']} falls outside the date range")

    if errs:
        raise SystemExit(f"{cfg.source.name} is invalid:\n  - " + "\n  - ".join(errs))


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def business_days(start: date, end: date) -> list[date]:
    """Weekdays between start and end, minus a short list of common holidays."""
    holidays = set()
    for year in range(start.year, end.year + 1):
        holidays.update({
            date(year, 1, 1),    # New Year
            date(year, 5, 1),    # Labour Day (Europe)
            date(year, 12, 25),  # Christmas
            date(year, 12, 26),  # Boxing Day
            date(year, 7, 4),    # US Independence Day
        })
    out, cur = [], start
    while cur <= end:
        if cur.weekday() < 5 and cur not in holidays:
            out.append(cur)
        cur += timedelta(days=1)
    return out


def round_lot(raw: float) -> int:
    """Round a desired quantity to a sensible trading lot, minimum 100."""
    if raw >= 50_000:
        step = 1_000
    elif raw >= 5_000:
        step = 500
    elif raw >= 1_000:
        step = 100
    else:
        step = 50
    return max(step, int(round(raw / step)) * step)


# --------------------------------------------------------------------------
# Generation
# --------------------------------------------------------------------------

def generate(cfg: Config) -> dict[str, list]:
    rng = random.Random(cfg.seed)
    days = business_days(cfg.start_date, cfg.end_date)
    day_index = {d: i for i, d in enumerate(days)}

    # Unpack the config once, so the model below reads as a model.
    mkt, tr = cfg.market, cfg.trades
    countries = list(cfg.clients["countries"])
    country_w = list(cfg.clients["countries"].values())
    segments = list(cfg.clients["segments"])
    segment_w = list(cfg.clients["segments"].values())
    fx_base, fx_vol = cfg.fx["base"], cfg.fx["vol"]
    aum_cfg = cfg.clients["aum"]
    season = tr["seasonality"]
    min_ticket_usd = tr["min_ticket_usd"]

    # ---- clients ---------------------------------------------------------
    # AUM is lognormal, with institutions an order of magnitude larger. It is
    # internal only (drives trade sizing/activity below) - not an exported
    # column, so hub clients get a random draw same as everyone else rather
    # than a hardcoded value.
    def random_aum(segment: str) -> float:
        centre = aum_cfg["centre"][segment]
        aum = math.exp(rng.gauss(centre, aum_cfg["sigma"]))
        return round(min(aum, aum_cfg["cap_usd"]), -4)

    clients = []
    for cid, name, country, segment, onboard in HUB_CLIENTS:
        clients.append({"client_id": cid, "client_name": name, "country": country,
                        "segment": segment, "onboard_date": onboard,
                        "aum_usd": random_aum(segment)})

    used_names = {c["client_name"] for c in clients}
    for i in range(len(HUB_CLIENTS) + 1, cfg.n_clients + 1):
        segment = rng.choices(segments, weights=segment_w)[0]
        for _ in range(50):
            name = f"{rng.choice(CLIENT_PREFIX)} {rng.choice(CLIENT_SUFFIX[segment])}"
            if name not in used_names:
                break
        used_names.add(name)

        aum = random_aum(segment)

        onboard_from = cfg.clients["onboard_from"]
        span = (cfg.clients["onboard_to"] - onboard_from).days
        onboard = onboard_from + timedelta(days=rng.randint(0, span))

        clients.append({
            "client_id": f"C{i:03d}", "client_name": name,
            "country": rng.choices(countries, weights=country_w)[0],
            "segment": segment, "onboard_date": onboard, "aum_usd": aum,
        })

    # ---- securities ------------------------------------------------------
    securities = []
    sec_meta = {}
    for ticker, name, sector, exchange, start_px, tier in SECURITIES:
        ccy = EXCHANGE_CCY[exchange]
        securities.append({"ticker": ticker, "security_name": name, "sector": sector,
                           "exchange": exchange, "currency": ccy})
        sec_meta[ticker] = {
            "sector": sector, "currency": ccy, "start_px": start_px, "tier": tier,
            "beta": round(rng.uniform(mkt["beta_min"], mkt["beta_max"]), 3),
            "idio_vol": rng.uniform(mkt["idio_vol_min"], mkt["idio_vol_max"]),
            # Small idiosyncratic alpha only - most of a security's return
            # should come from the market and sector factors below.
            "drift": rng.gauss(mkt["alpha_mean"], mkt["alpha_sd"]),
        }

    sectors = sorted({s["sector"] for s in securities})

    # ---- fx_rates --------------------------------------------------------
    fx_rows = []
    fx_lookup: dict[tuple[date, str], float] = {}
    fx_level = dict(fx_base)
    for d in days:
        for ccy, base in fx_base.items():
            if ccy == "USD":
                rate = 1.0
            else:
                # Mean-reverting random walk so rates drift but stay plausible.
                shock = rng.gauss(0, fx_vol[ccy])
                pull = cfg.fx["mean_reversion"] * (math.log(base) - math.log(fx_level[ccy]))
                fx_level[ccy] *= math.exp(shock + pull)
                rate = fx_level[ccy]
            rate = round(rate, 6)
            fx_lookup[(d, ccy)] = rate
            fx_rows.append({"rate_date": d, "currency": ccy, "rate_to_usd": rate})

    # ---- prices ----------------------------------------------------------
    # Factor model: market factor with volatility clustering and two drawdowns,
    # a daily factor per sector, then per-security idiosyncratic noise.
    # Market factor: ~9% annualised drift and ~14% annualised volatility, with
    # volatility clustering and three drawdowns so charts have something to show.
    market_vol = mkt["base_vol"]           # steady state lands near 0.0089 daily
    persistence = mkt["vol_persistence"]
    market_ret = []
    vol = market_vol
    shock_windows = [(day_index.get(w["start"], 0), w["trading_days"])
                     for w in mkt["shock"]["windows"]]
    for i, _ in enumerate(days):
        vol = persistence * vol + (1 - persistence) * market_vol * (1 + abs(rng.gauss(0, 0.60)))
        vol = min(vol, mkt["vol_cap"])
        # The drawdown multiplier applies to this day's draw only. Folding it
        # back into `vol` would compound through the recursion and blow up.
        drift, day_vol = mkt["drift"], vol
        for start_i, length in shock_windows:
            if start_i <= i < start_i + length:
                drift = mkt["shock"]["drift"]
                day_vol = vol * mkt["shock"]["vol_multiplier"]
        market_ret.append(rng.gauss(drift, day_vol))

    sector_ret = {s: [rng.gauss(0, mkt["sector_vol"]) for _ in days] for s in sectors}

    tier_volume = {1: mkt["volume"]["tier_1"], 2: mkt["volume"]["tier_2"],
                   3: mkt["volume"]["tier_3"]}

    prices = []
    price_lookup: dict[tuple[str, date], dict] = {}
    for ticker, meta in sec_meta.items():
        px = meta["start_px"]
        prev_close = px
        for i, d in enumerate(days):
            r = (meta["drift"]
                 + meta["beta"] * market_ret[i]
                 + mkt["sector_loading"] * sector_ret[meta["sector"]][i]
                 + rng.gauss(0, meta["idio_vol"]))
            cap = mkt["daily_return_cap"]
            r = max(min(r, cap), -cap)            # cap absurd single-day moves
            close = prev_close * math.exp(r)

            gap = rng.gauss(0, meta["idio_vol"] * mkt["open_gap_factor"])
            open_px = prev_close * math.exp(gap)
            wick = mkt["high_low_noise"]
            hi = max(open_px, close) * (1 + abs(rng.gauss(0, wick)))
            lo = min(open_px, close) * (1 - abs(rng.gauss(0, wick)))

            # Volume rises with absolute return; scaled by size tier.
            volume = int(tier_volume[meta["tier"]]
                         * math.exp(rng.gauss(0, mkt["volume"]["noise_sd"]))
                         * (1 + mkt["volume"]["return_sensitivity"] * abs(r)))

            dp = 2
            o, h, l, c = (round(open_px, dp), round(hi, dp), round(lo, dp), round(close, dp))
            # Rounding can break the bar; repair it so the CHECK constraints hold.
            h = max(h, o, c)
            l = min(l, o, c)
            if l <= 0:
                l = round(min(o, c) * 0.98, dp)

            prices.append({"price_date": d, "ticker": ticker, "open_px": o, "high_px": h,
                           "low_px": l, "close_px": c, "volume": volume})
            price_lookup[(ticker, d)] = {"open": o, "high": h, "low": l, "close": c}
            prev_close = close

    # ---- trades ----------------------------------------------------------
    # Each client gets a style: a weighted preference over sectors, so that
    # holdings look deliberate rather than uniformly random.
    all_tickers = [s["ticker"] for s in securities]
    client_universe: dict[str, list[str]] = {}
    client_style: dict[str, list[float]] = {}
    for c in clients:
        favoured = rng.sample(sectors, k=rng.randint(2, 4))

        # Each client invests in a limited universe - a mandate, effectively -
        # so books stay concentrated instead of drifting towards holding
        # everything. Institutions run broader lists than private clients.
        breadth = cfg.clients["mandate"][c["segment"]]
        k = rng.randint(breadth[0], breadth[1])
        pool_w = []
        for t in all_tickers:
            w = 1.0
            if sec_meta[t]["sector"] in favoured:
                w *= 6.0
            if sec_meta[t]["currency"] == "USD" and c["country"] == "US":
                w *= 1.6
            if sec_meta[t]["currency"] == "EUR" and c["country"] in ("FR", "DE", "IT", "ES", "BE", "NL", "LU"):
                w *= 1.5
            pool_w.append(w)

        universe: list[str] = []
        pool = list(all_tickers)
        weights_left = list(pool_w)
        for _ in range(min(k, len(pool))):
            pick = rng.choices(range(len(pool)), weights=weights_left)[0]
            universe.append(pool.pop(pick))
            weights_left.pop(pick)

        client_universe[c["client_id"]] = universe
        client_style[c["client_id"]] = [
            (6.0 if sec_meta[t]["sector"] in favoured else 1.0) * rng.uniform(0.6, 1.8)
            for t in universe
        ]

    # Activity weight: bigger books trade more often. A slice of clients is
    # dormant and never trades at all, which is realistic and gives LEFT JOIN
    # examples something to find.
    client_by_id = {c["client_id"]: c for c in clients}
    active_clients, activity_w = [], []
    for c in clients:
        if rng.random() < cfg.clients["dormant_rate"]:
            continue                                    # dormant
        active_clients.append(c["client_id"])
        activity_w.append(math.log10(max(c["aum_usd"], 1e6)) ** 3)

    # Running book: (client_id, ticker) -> {qty, avg_cost} in local currency.
    book: dict[tuple[str, str], dict] = {}
    trades = []
    trade_seq = 10001

    for d in days:
        # Seasonality: August and late December are quiet.
        factor = 1.0
        if d.month == 8:
            factor = season["august"]
        elif d.month == 12 and d.day > 18:
            factor = season["late_december"]
        elif d.month in (3, 6, 9, 12) and d.day > 25:
            factor = season["quarter_end"]          # quarter-end rebalancing
        n_trades = max(0, int(rng.gauss(cfg.trades_per_day * factor,
                                        cfg.trades_per_day * tr["daily_noise"])))

        for _ in range(n_trades):
            cid = rng.choices(active_clients, weights=activity_w)[0]
            client = client_by_id[cid]
            if d < client["onboard_date"]:
                continue

            ticker = rng.choices(client_universe[cid], weights=client_style[cid])[0]
            bar = price_lookup.get((ticker, d))
            if bar is None:
                continue

            held = book.get((cid, ticker), {"qty": 0, "avg_cost": 0.0})
            # Sell only what is actually held; otherwise buy.
            side = "SELL" if (held["qty"] > 0 and rng.random() < tr["sell_probability"]) else "BUY"

            ccy = sec_meta[ticker]["currency"]
            fx = fx_lookup[(d, ccy)]
            px_usd = bar["close"] * fx

            if side == "BUY":
                # Ticket size scales with the client's book, in USD, then
                # converts to a share count in the instrument's own currency.
                target_usd = client["aum_usd"] * rng.uniform(tr["ticket_frac_min"],
                                                             tr["ticket_frac_max"])
                target_usd = max(target_usd, min_ticket_usd)
                qty = round_lot(target_usd / max(px_usd, 0.01))
            else:
                # Nobody sends a 300-dollar order to the market. If the whole
                # holding is below the minimum ticket, leave it as dust; if a
                # partial sale would be below it, close the position instead.
                held_usd = held["qty"] * px_usd
                if held_usd < min_ticket_usd:
                    continue
                frac = rng.choice(tr["sell_fractions"])
                qty = min(round_lot(held["qty"] * frac), held["qty"])
                if qty * px_usd < min_ticket_usd:
                    qty = held["qty"]
                if qty <= 0:
                    continue

            # Execution price: close plus slippage, clamped inside the day's range.
            px = bar["close"] * (1 + rng.gauss(0, tr["slippage_sd"]))
            px = round(min(max(px, bar["low"]), bar["high"]), 2)

            trades.append({
                "trade_id": f"T{trade_seq}", "trade_date": d, "client_id": cid,
                "ticker": ticker, "side": side, "quantity": qty,
                "price": px,
            })
            trade_seq += 1

            # Update the running book: weighted average cost on buys, unchanged
            # on sells. Tracked purely so a client can never sell more than
            # they hold - this is the same running-net logic a trainee's SQL
            # has to reproduce to compute holdings from `trades`.
            if side == "BUY":
                new_qty = held["qty"] + qty
                held["avg_cost"] = (held["qty"] * held["avg_cost"] + qty * px) / new_qty
                held["qty"] = new_qty
            else:
                held["qty"] -= qty
                if held["qty"] == 0:
                    held["avg_cost"] = 0.0
            book[(cid, ticker)] = held

    commission_schedule = [
        {"segment": s, "bps": cfg.fees[s]["bps"], "min_usd": cfg.fees[s]["min_usd"]}
        for s in segments
    ]

    return {"clients": clients, "securities": securities, "fx_rates": fx_rows,
            "prices": prices, "trades": trades,
            "commission_schedule": commission_schedule}


# --------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------

COLUMNS = {
    "clients":    ["client_id", "client_name", "country", "segment", "onboard_date"],
    "securities": ["ticker", "security_name", "sector", "exchange", "currency"],
    "fx_rates":   ["rate_date", "currency", "rate_to_usd"],
    "prices":     ["price_date", "ticker", "open_px", "high_px", "low_px", "close_px", "volume"],
    "trades":     ["trade_id", "trade_date", "client_id", "ticker", "side", "quantity",
                   "price"],
    "commission_schedule": ["segment", "bps", "min_usd"],
}


def write_csv(name: str, rows: list[dict], out_dir: Path) -> Path:
    path = out_dir / f"{name}.csv"
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS[name], extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: ("" if row[k] is None else row[k]) for k in COLUMNS[name]})
    return path


def write_manifest(cfg: Config, data: dict[str, list], out_dir: Path) -> Path:
    """Record what produced these CSVs, so documentation cannot drift from data."""
    path = out_dir / "_manifest.json"
    path.write_text(json.dumps({
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "config_file": cfg.source.name,
        "seed": cfg.seed,
        "start_date": cfg.start_date.isoformat(),
        "end_date": cfg.end_date.isoformat(),
        "trading_days": len(business_days(cfg.start_date, cfg.end_date)),
        "clients": cfg.n_clients,
        "trades_per_day": cfg.trades_per_day,
        "rows": {name: len(data[name]) for name in COLUMNS},
    }, indent=2) + "\n", encoding="utf-8")
    return path


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Generate the Seki Capital dataset.",
        epilog="Parameters live in config.toml; these flags override it.")
    ap.add_argument("--config", type=Path, default=CONFIG_PATH,
                    help="config file to read (default: config.toml)")
    ap.add_argument("--clients", type=int, help="override [run] clients")
    ap.add_argument("--trades-per-day", type=int, help="override [run] trades_per_day")
    ap.add_argument("--out", type=Path, help="override [run] out_dir")
    args = ap.parse_args()

    cfg = load_config(args.config, clients=args.clients,
                      trades_per_day=args.trades_per_day, out=args.out)
    cfg.out_dir.mkdir(parents=True, exist_ok=True)
    data = generate(cfg)

    print(f"Seki Capital  {cfg.start_date} to {cfg.end_date}  "
          f"(seed {cfg.seed}, {cfg.source.name})\n")
    for name in COLUMNS:
        path = write_csv(name, data[name], cfg.out_dir)
        size_kb = path.stat().st_size / 1024
        print(f"  {name:<11} {len(data[name]):>8,} rows   {size_kb:>9,.0f} KB   {path.name}")
    print(f"\n  manifest    {write_manifest(cfg, data, cfg.out_dir).name}")


if __name__ == "__main__":
    main()
