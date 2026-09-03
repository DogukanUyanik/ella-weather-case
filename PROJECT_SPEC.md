# PROJECT_SPEC.md

## Task, in my own words

We're building a small system that ingests weather forecasts (not
historical observations) from the Open-Meteo API for three Belgian
cities, and stores them in PostgreSQL. Because Open-Meteo revises its
forecasts over time, our data model must support both "give me the
latest forecast" and "show me the full history of how the forecast for
one specific hour evolved." A FastAPI service exposes this data, and a
Next.js dashboard displays it. Everything must start with a single
command (`docker compose up`) from a fresh clone.

## Core problem

The forecast-revision problem: the same source returns different
values at different points in time for the same future target hour.
Data is never overwritten — every ingestion run inserts new rows, so
both "latest forecast" and "revision history" can be answered with
simple queries.

## Architecture overview

Three logical components (deployable units):

1. **Ingestion** — a standalone, on-demand runnable script/process
   that queries Open-Meteo for Ghent, Antwerp, and Temse, and writes
   the results to Postgres. Does not run as part of the API server.
2. **API (FastAPI)** — reads from Postgres only, contains no
   ingestion logic.
3. **Frontend (Next.js + shadcn/ui)** — consumes the API, renders the
   dashboard.

The database connection (for both ingestion and API) is configured via
the `DATABASE_URL` environment variable, so the same code works
unchanged against a local dev Postgres container and against the
Postgres service in the final `docker-compose.yml`.

All timestamps are stored in UTC (`TIMESTAMPTZ` in Postgres). Each
ingestion run computes a single `run_timestamp` once at the start of
the run and uses that exact same value for every row written in that
batch — never a fresh `now()` per row — so that "latest forecast"
queries (`MAX(ingested_at)`) are reliable. Details in
specs/01-data-model-and-ingestion.md.

## Scope — definitely building

- Ingestion for Ghent, Antwerp, Temse; idempotent, atomic, resilient
- Data model: flat time-series table with (city, target_time,
  ingested_at) + weather variables, unique constraint on
  (city, target_time, ingested_at)
- API endpoint: latest forecast per city
- API endpoint: forecast history for a city + specific target_time
- One focused idempotency test (running twice = no extra rows)
- Dashboard: pick a city, see the latest forecast per hour/day
- `docker-compose.yml` that starts everything with one command
- README with quickstart, architectural decisions, scope cuts

## Scope — stretch / optional

- UI visualization of how the forecast for one specific hour changed
  across multiple ingestion runs (the API endpoint exists regardless;
  the UI for it only if time allows)
- Automated scheduling (cron container or GitHub Action)

## Deliberate cuts (and why)

- No Alembic/migrations — `create_all()` is sufficient for this scope
- No authentication/rate limiting on the API — not relevant for an
  internal case demo
- No retry-with-backoff on the Open-Meteo call — just try/except with
  logging and skipping; in production I'd add a retry policy
- Automated scheduling may be dropped if time runs out — ingestion
  stays manually triggerable, and the README explains how this would
  be handled in production (cron container vs. GitHub Action, with
  the trade-off reasoning)

## Build order

1. Ingestion + data model — see specs/01-data-model-and-ingestion.md
2. Backend API — see specs/02-backend-api.md
3. Frontend dashboard — see specs/03-frontend-ui.md
4. docker-compose glue + README