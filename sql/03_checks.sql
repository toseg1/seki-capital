-- ===========================================================================
-- Seki Capital - data quality checks
--
--     psql -v ON_ERROR_STOP=1 -d seki -f sql/03_checks.sql
--
-- Every row must come back PASS. These are the assertions the generator is
-- built to satisfy; they are worth running after any regeneration, and they
-- are worth showing an interviewer, because "I wrote tests for my test data"
-- is a better answer than "I trusted the script".
-- ===========================================================================

SET search_path TO seki, public;

WITH checks AS (

    -- 1. Every execution price sits inside that day's traded range.
    SELECT 1 AS n, 'Trade prices within the day''s low/high range' AS check_name,
           count(*) AS violations
    FROM trades t
    JOIN prices p ON p.ticker = t.ticker AND p.price_date = t.trade_date
    WHERE t.price < p.low_px OR t.price > p.high_px

    UNION ALL
    -- 2. Nobody sold stock they did not hold: no negative running quantity.
    -- This is the same running-net logic you need to reproduce in SQL to
    -- compute current holdings from trades.
    SELECT 2, 'No client ever holds a negative quantity',
           count(*)
    FROM (
        SELECT SUM(CASE WHEN side = 'BUY' THEN quantity ELSE -quantity END)
                   OVER (PARTITION BY client_id, ticker ORDER BY trade_date, trade_id)
                   AS running_qty
        FROM trades
    ) r
    WHERE r.running_qty < 0

    UNION ALL
    -- 3. No trade predates the client's onboarding.
    SELECT 3, 'No trade occurs before the client onboarded',
           count(*)
    FROM trades t
    JOIN clients c ON c.client_id = t.client_id
    WHERE t.trade_date < c.onboard_date

    UNION ALL
    -- 4. Price history is complete: every security on every trading day.
    SELECT 4, 'Every security has a price on every trading day',
           (SELECT count(*) FROM securities) * (SELECT count(DISTINCT price_date) FROM prices)
           - (SELECT count(*) FROM prices)

    UNION ALL
    -- 5. FX covers every currency on every trading day, and USD is exactly 1.
    SELECT 5, 'FX rates complete, and USD is exactly 1.0',
           (SELECT count(*) FROM fx_rates WHERE currency = 'USD' AND rate_to_usd <> 1.0)
         + (SELECT count(DISTINCT price_date) FROM prices) * 5
         - (SELECT count(*) FROM fx_rates)

    UNION ALL
    -- 6. Every client segment that trades has a commission_schedule entry.
    -- Commission is not stored per trade - it is computed by joining trades
    -- to clients (for segment) to commission_schedule (for bps/min_usd). If
    -- a segment is missing from the schedule, that join silently drops rows
    -- instead of erroring, so this is worth checking explicitly.
    SELECT 6, 'Every client segment has a commission_schedule entry',
           count(*)
    FROM (SELECT DISTINCT segment FROM clients) c
    LEFT JOIN commission_schedule cs ON cs.segment = c.segment
    WHERE cs.segment IS NULL
)

SELECT
    n                                                        AS "#",
    check_name                                               AS "check",
    violations                                               AS "violations",
    CASE WHEN violations = 0 THEN 'PASS' ELSE 'FAIL' END     AS "result"
FROM checks
ORDER BY n;
