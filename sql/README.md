# PostgreSQL reproduction

Run these files in order from the repository root:

```bash
psql -d macro_project -f sql/00_schema.sql
psql -d macro_project -f sql/01_load_raw.sql
psql -d macro_project -f sql/02_transform_regimes.sql
psql -d macro_project -f sql/04_validation.sql
psql -d macro_project -f sql/03_analysis_queries.sql
```

`01_load_raw.sql` uses `psql`'s client-side `\copy`, so the command must be launched from the repository root. The SQL transformation mirrors the Python implementation: seven-day backward as-of joins for release-calendar gaps, a 63-trading-day yield change, and one-trading-day-lagged regime signals.
