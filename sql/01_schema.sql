-- ===========================================================================
-- Seki Capital - schema
-- PostgreSQL 14+
--
-- Four core tables matching the Data Skills Learning Hub model, plus two
-- small reference tables: fx_rates (so holdings in EUR, GBP, CHF and JPY can
-- be valued in USD) and commission_schedule (the firm's fee rate card).
--
-- There is no positions table, and trades.commission does not exist either.
-- `trades` is the only source of truth for what a client holds - current
-- quantity, average cost, market value and per-trade commission are all
-- calculated columns the trainee derives with SQL in Metabase.
--
-- Constraints are deliberately strict: they are part of the deliverable. If
-- the data loads without error, the generator's invariants held.
-- ===========================================================================

DROP SCHEMA IF EXISTS seki CASCADE;
CREATE SCHEMA seki;

SET search_path TO seki, public;


-- ---------------------------------------------------------------------------
-- clients: one row per client of the firm
-- ---------------------------------------------------------------------------
CREATE TABLE clients (
    client_id     text            PRIMARY KEY,
    client_name   text            NOT NULL,
    country       char(2)         NOT NULL,
    segment       text            NOT NULL,
    onboard_date  date            NOT NULL,

    CONSTRAINT clients_segment_chk
        CHECK (segment IN ('Institutional', 'Private', 'Wholesale'))
);

COMMENT ON TABLE  clients IS
    'One row per client of the firm. Static reference data. AUM is not '
    'stored - it is a calculated column: SUM(market value) of that client''s '
    'holdings, derived from trades, which you compute yourself.';
COMMENT ON COLUMN clients.onboard_date IS
    'Date the relationship opened.';


-- ---------------------------------------------------------------------------
-- securities: one row per tradable instrument
-- ---------------------------------------------------------------------------
CREATE TABLE securities (
    ticker         text  PRIMARY KEY,
    security_name  text  NOT NULL,
    sector         text  NOT NULL,
    exchange       text  NOT NULL,
    currency       char(3) NOT NULL,

    CONSTRAINT securities_ccy_chk
        CHECK (currency IN ('USD', 'EUR', 'GBP', 'CHF', 'JPY'))
);

COMMENT ON TABLE  securities IS
    'One row per tradable instrument. currency is the instrument''s quotation '
    'currency: prices and trades.price are expressed in it.';


-- ---------------------------------------------------------------------------
-- fx_rates: daily rate from each quotation currency into USD
-- ---------------------------------------------------------------------------
CREATE TABLE fx_rates (
    rate_date    date            NOT NULL,
    currency     char(3)         NOT NULL,
    rate_to_usd  numeric(14, 6)  NOT NULL,

    PRIMARY KEY (rate_date, currency),
    CONSTRAINT fx_positive_chk CHECK (rate_to_usd > 0)
);

COMMENT ON TABLE fx_rates IS
    'Daily FX rate into USD, one row per currency per business day. USD is '
    'present with a rate of 1.0 so joins never need a special case.';


-- ---------------------------------------------------------------------------
-- prices: one row per instrument per business day
-- ---------------------------------------------------------------------------
CREATE TABLE prices (
    price_date  date            NOT NULL,
    ticker      text            NOT NULL REFERENCES securities (ticker),
    open_px     numeric(14, 2)  NOT NULL,
    high_px     numeric(14, 2)  NOT NULL,
    low_px      numeric(14, 2)  NOT NULL,
    close_px    numeric(14, 2)  NOT NULL,
    volume      bigint          NOT NULL,

    PRIMARY KEY (price_date, ticker),

    -- A price bar has to make sense: the high is the highest of the four,
    -- the low the lowest, and nothing is negative.
    CONSTRAINT prices_bar_chk CHECK (
        low_px > 0
        AND high_px >= low_px
        AND high_px >= open_px  AND high_px >= close_px
        AND low_px  <= open_px  AND low_px  <= close_px
    ),
    CONSTRAINT prices_volume_chk CHECK (volume >= 0)
);

COMMENT ON TABLE prices IS
    'Daily OHLCV bar per instrument, in the instrument''s quotation currency.';


-- ---------------------------------------------------------------------------
-- trades: one row per executed order
-- ---------------------------------------------------------------------------
CREATE TABLE trades (
    trade_id    text            PRIMARY KEY,
    trade_date  date            NOT NULL,
    client_id   text            NOT NULL REFERENCES clients (client_id),
    ticker      text            NOT NULL REFERENCES securities (ticker),
    side        text            NOT NULL,
    quantity    bigint          NOT NULL,
    price       numeric(14, 2)  NOT NULL,

    CONSTRAINT trades_side_chk       CHECK (side IN ('BUY', 'SELL')),
    CONSTRAINT trades_quantity_chk   CHECK (quantity > 0),
    CONSTRAINT trades_price_chk      CHECK (price > 0),

    -- Every execution must correspond to a real price bar.
    CONSTRAINT trades_price_bar_fk
        FOREIGN KEY (trade_date, ticker) REFERENCES prices (price_date, ticker)
);

COMMENT ON TABLE  trades IS
    'One row per executed order. quantity is always positive; side carries the '
    'direction. There is no commission column - join to commission_schedule '
    'on clients.segment and compute it: GREATEST(min_usd, notional_usd * '
    'bps / 10000).';
COMMENT ON COLUMN trades.price IS
    'Execution price in the instrument''s quotation currency. Always inside '
    'that day''s low/high range - see sql/03_checks.sql.';


-- ---------------------------------------------------------------------------
-- commission_schedule: the firm's fee rate card, one row per client segment
-- ---------------------------------------------------------------------------
CREATE TABLE commission_schedule (
    segment  text            PRIMARY KEY,
    bps      numeric(6, 2)   NOT NULL,
    min_usd  numeric(10, 2)  NOT NULL,

    CONSTRAINT commission_schedule_segment_chk
        CHECK (segment IN ('Institutional', 'Private', 'Wholesale')),
    CONSTRAINT commission_schedule_bps_chk     CHECK (bps > 0),
    CONSTRAINT commission_schedule_min_usd_chk CHECK (min_usd >= 0)
);

COMMENT ON TABLE commission_schedule IS
    'The firm''s fee rate card: commission rate in basis points of notional, '
    'and the per-ticket minimum in USD, by client segment. Reference data, '
    'not derived from anything else - unlike positions or market_value, this '
    'genuinely earns its own table. Join it to trades via clients.segment.';


-- ---------------------------------------------------------------------------
-- Indexes: the access paths Metabase will actually use
-- ---------------------------------------------------------------------------
CREATE INDEX idx_prices_ticker_date  ON prices    (ticker, price_date);
CREATE INDEX idx_prices_date         ON prices    (price_date);

CREATE INDEX idx_trades_date         ON trades    (trade_date);
CREATE INDEX idx_trades_client       ON trades    (client_id);
CREATE INDEX idx_trades_ticker       ON trades    (ticker);
CREATE INDEX idx_trades_client_tkr   ON trades    (client_id, ticker);

CREATE INDEX idx_fx_currency_date    ON fx_rates  (currency, rate_date);


-- Make `seki` the default schema for every new session on this database,
-- so plain `SELECT * FROM trades` works without qualifying the schema.
-- (Uses current_database() so this file works whatever the database is called.)
DO $$
BEGIN
    EXECUTE format('ALTER DATABASE %I SET search_path TO seki, public',
                   current_database());
END
$$;
