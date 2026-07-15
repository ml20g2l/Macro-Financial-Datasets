-- PostgreSQL 15+ schema and raw landing tables.
-- Raw values remain text so source formatting and missing markers are preserved.

CREATE SCHEMA IF NOT EXISTS raw;
CREATE SCHEMA IF NOT EXISTS stg;
CREATE SCHEMA IF NOT EXISTS mart;

DROP TABLE IF EXISTS raw.asset_prices CASCADE;
CREATE TABLE raw.asset_prices (
    date_text        text,
    ticker           text,
    close_price_text text
);

DROP TABLE IF EXISTS raw.fred_vix CASCADE;
CREATE TABLE raw.fred_vix (
    date_text text,
    vix_text  text
);

DROP TABLE IF EXISTS raw.fred_dgs10 CASCADE;
CREATE TABLE raw.fred_dgs10 (
    date_text  text,
    dgs10_text text
);

DROP TABLE IF EXISTS raw.boe_bank_rate CASCADE;
CREATE TABLE raw.boe_bank_rate (
    effective_date_text text,
    bank_rate_text      text
);
