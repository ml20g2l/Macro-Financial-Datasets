-- Run from the repository root with psql so these relative paths resolve.
-- Example: psql -d macro_project -f sql/00_schema.sql -f sql/01_load_raw.sql

\set ON_ERROR_STOP on

TRUNCATE raw.asset_prices, raw.fred_vix, raw.fred_dgs10, raw.boe_bank_rate;

\copy raw.asset_prices(date_text, ticker, close_price_text) FROM 'data/raw/yahoo/asset_prices.csv' WITH (FORMAT csv, HEADER true);
\copy raw.fred_vix(date_text, vix_text) FROM 'data/raw/fred/VIXCLS.csv' WITH (FORMAT csv, HEADER true);
\copy raw.fred_dgs10(date_text, dgs10_text) FROM 'data/raw/fred/DGS10.csv' WITH (FORMAT csv, HEADER true);
\copy raw.boe_bank_rate(effective_date_text, bank_rate_text) FROM 'data/raw/boe/bank_rate_history.csv' WITH (FORMAT csv, HEADER true);
