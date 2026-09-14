-- ===========================================================================
-- Seki Capital - load the CSVs
--
-- Uses \copy (client side), so run psql from the REPO ROOT:
--     psql -v ON_ERROR_STOP=1 -d seki -f sql/02_load.sql
--
-- Load order matters: securities and clients before prices and trades, and
-- prices before trades because of the (trade_date, ticker) foreign key.
-- ===========================================================================

SET search_path TO seki, public;

\echo 'Loading clients...'
\copy clients    (client_id, client_name, country, segment, onboard_date)                           FROM 'data/clients.csv'    WITH (FORMAT csv, HEADER true, NULL '')

\echo 'Loading securities...'
\copy securities (ticker, security_name, sector, exchange, currency)                               FROM 'data/securities.csv' WITH (FORMAT csv, HEADER true, NULL '')

\echo 'Loading fx_rates...'
\copy fx_rates   (rate_date, currency, rate_to_usd)                                                FROM 'data/fx_rates.csv'   WITH (FORMAT csv, HEADER true, NULL '')

\echo 'Loading prices...'
\copy prices     (price_date, ticker, open_px, high_px, low_px, close_px, volume)                  FROM 'data/prices.csv'     WITH (FORMAT csv, HEADER true, NULL '')

\echo 'Loading trades...'
\copy trades     (trade_id, trade_date, client_id, ticker, side, quantity, price)                  FROM 'data/trades.csv'     WITH (FORMAT csv, HEADER true, NULL '')

\echo 'Loading commission_schedule...'
\copy commission_schedule (segment, bps, min_usd)                                                  FROM 'data/commission_schedule.csv' WITH (FORMAT csv, HEADER true, NULL '')

ANALYZE clients;
ANALYZE securities;
ANALYZE fx_rates;
ANALYZE prices;
ANALYZE trades;
ANALYZE commission_schedule;

\echo ''
\echo 'Row counts:'
SELECT 'clients'    AS table_name, count(*) AS rows FROM clients
UNION ALL SELECT 'securities', count(*) FROM securities
UNION ALL SELECT 'fx_rates',   count(*) FROM fx_rates
UNION ALL SELECT 'prices',     count(*) FROM prices
UNION ALL SELECT 'trades',     count(*) FROM trades
UNION ALL SELECT 'commission_schedule', count(*) FROM commission_schedule
ORDER BY 1;
