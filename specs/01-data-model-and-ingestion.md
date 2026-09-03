# Spec 01 — Data model & ingestion

## Goal

Ingest hourly temperature forecasts from Open-Meteo for three Belgian
cities into Postgres, in a way that is idempotent, atomic (per city),
and resilient to source failures — while preserving every forecast
revision, never overwriting history.

## Data source

- Open-Meteo forecast API: `https://api.open-meteo.com/v1/forecast`
- Query parameters: `latitude`, `longitude`, `hourly=temperature_2m`,
  `forecast_days=7`
- Open-Meteo takes coordinates, not city names — it has no concept of
  "Ghent" or "Temse". We maintain our own small config mapping city
  name to coordinates, and label each response ourselves before
  writing it to the database:

  | city    | latitude | longitude |
  |---------|----------|-----------|
  | Ghent   | 51.05    | 3.72      |
  | Antwerp | 51.22    | 4.40      |
  | Temse   | 51.13    | 4.21      |

- Horizon: 7 days ahead, hourly granularity
- Variable: temperature only for now. Adding more variables later
  (e.g. precipitation) is an additive schema change — a new column on
  the same table — not a redesign. The key structure (`city`,
  `target_time`, `ingested_at`) and the idempotency/atomicity
  mechanisms described below are unaffected by adding columns.

## Data model

Single flat time-series table, e.g. `forecasts`:

| column        | type          | notes                                   |
|---------------|---------------|------------------------------------------|
| id            | serial/PK     |                                          |
| city          | text          | one of the 3 configured cities          |
| target_time   | timestamptz   | the future hour this forecast is for    |
| ingested_at   | timestamptz   | when this run fetched the data (UTC)    |
| temperature_c | numeric       | forecasted temperature in °C            |

A flat table (not normalized into separate `cities`/`runs` tables) is
the deliberate choice here — at this scale it keeps ingestion and
querying simple, and the unique constraint below is what actually
enforces correctness, not a normalized schema.

### Unique constraint

`UNIQUE (city, target_time, ingested_at)`

This is what makes re-running ingestion idempotent: inserting the same
(city, target_time, ingested_at) tuple twice is rejected by the
database itself via `ON CONFLICT DO NOTHING`, rather than relying on
application logic to detect duplicates.

### Timestamp rules

- All timestamps are stored as `TIMESTAMPTZ`, in UTC. Open-Meteo
  returns ISO 8601 strings — parse them into timezone-aware UTC
  `datetime` objects before writing, never naive datetimes.
- `ingested_at` is **not** `datetime.now(timezone.utc)` called
  per-row. It is computed **once**, at the very start of the ingestion
  run, and that exact same value is used for every row written during
  that run — across all cities. This is required for `MAX(ingested_at)`
  queries (the "latest forecast" lookup) to behave correctly; per-row
  timestamps would make rows from the same run appear as different
  revisions.
- The ingestion function accepts an optional `run_timestamp` parameter
  (`run_ingestion(run_timestamp: datetime | None = None)`). When not
  provided — i.e. normal CLI/scheduled usage — it defaults to
  `datetime.now(timezone.utc)`, so two legitimate runs (even minutes
  apart) each get their own timestamp and are correctly stored as
  separate revisions; nothing is silently discarded. The parameter
  exists so automated tests can pass the *same* fixed timestamp twice
  to simulate a retry of one specific run and assert that the second
  call inserts zero additional rows — proving idempotency on
  `(city, target_time, ingested_at)` without relying on wall-clock
  timing or truncation, and without ever dropping a real revision.

## Ingestion flow

1. Compute `run_timestamp` once, at the start of the run.
2. For each city in the coordinate config (loop):
   a. Fetch the 7-day hourly forecast from Open-Meteo using that
      city's latitude/longitude.
   b. Validate the response (expected fields present, parseable).
   c. Open a transaction **for this city only**.
   d. Bulk-insert one row per target hour, labeling every row with
      this city's name, using `run_timestamp` as `ingested_at`, with
      `ON CONFLICT (city, target_time, ingested_at) DO NOTHING`.
   e. Commit this city's transaction.
3. Log a one-line summary per city: success (row count) or failure
   (reason).

Transactions are scoped **per city, not per run**: if Antwerp's API
call times out or returns garbage, that city is logged and skipped,
but Ghent and Temse — already committed — are unaffected. A single
whole-run transaction was considered and rejected, since it would roll
back successful cities whenever one city fails, which conflicts with
the resilience requirement. A per-row transaction was also considered
and rejected as unnecessary overhead — the unique constraint plus
`ON CONFLICT DO NOTHING` already makes individual row conflicts safe
within a single batch insert.

## Error handling

- **Idempotent:** unique constraint + `ON CONFLICT DO NOTHING` at the
  database level — safe to re-run the exact same fetch any number of
  times.
- **Atomic:** each city's insert batch (all ~168 hourly rows for that
  city) is wrapped in one transaction. Either the full batch for that
  city is written, or none of it is — on any failure during the
  batch, the transaction is rolled back rather than left partially
  committed.
- **Resilient:** each city's fetch + parse is wrapped in try/except.
  On failure: log the city name and the error, skip that city, and
  continue to the next one in the loop. The run never crashes because
  of one bad city or a malformed response.
- **Considered but deliberately not implemented:** retry-with-backoff
  on a failed fetch before giving up on that city. Logged as a
  scope cut — see PROJECT_SPEC.md / README "what I'd do differently
  with more time".

## How to test locally

1. Start a local dev Postgres: `docker run --name dev-postgres -e
   POSTGRES_PASSWORD=postgres -e POSTGRES_DB=weather -p 5432:5432 -d
   postgres:16`
2. Set `DATABASE_URL` to point at it.
3. Run `python ingest.py` once, inspect row count.
4. Running it again immediately is expected to add a **new** batch of
   rows — that's a legitimate new revision (a fresh `run_timestamp`),
   not a bug. Idempotency is not "any two manual runs are identical,"
   it's "retrying the exact same run doesn't duplicate."
5. Run `pytest` — the dedicated idempotency test calls
   `run_ingestion(run_timestamp=fixed_time)` twice with the same
   explicit fixed timestamp (simulating a retry of one specific run)
   and asserts the row count is identical after the second call.

## Out of scope for this part

- Retry-with-backoff on failed API calls (logged and skipped instead)
- A separate `ingestion_runs` audit table tracking per-run success/
  failure per city (useful in production, not needed to prove the
  core model works)
- Alembic/migrations — schema is created via `create_all()` at startup
- Automated scheduling (handled separately, may be cut — see
  PROJECT_SPEC.md)
- Additional weather variables beyond temperature (deliberately
  deferred, not a blocker for correctness)

## Acceptance criteria

- [ ] Calling `run_ingestion()` twice with the same explicit
      `run_timestamp` produces zero additional rows (retry safety)
- [ ] Calling `run_ingestion()` twice with no argument (default,
      real usage) produces two separate, correctly stored revisions
- [ ] Killing/failing one city's fetch does not prevent the other two
      cities from being written
- [ ] All stored timestamps are UTC `TIMESTAMPTZ`
- [ ] All rows from a single run share the exact same `ingested_at`
- [ ] Idempotency test in `tests/test_ingest.py` passes