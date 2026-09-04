# Belgian Weather Explorer

A small system that ingests weather forecasts from Open-Meteo for
three Belgian cities (Ghent, Antwerp, Temse), stores them in
PostgreSQL in a way that preserves every forecast revision, exposes
them through a FastAPI service, and displays them in a Next.js
dashboard.

## Quickstart

**Prerequisites:** Docker Engine and Docker Compose v2 installed.
Check with:
```bash
docker --version
docker compose version
```
If either command fails, install Docker first (e.g.
https://docs.docker.com/get-docker/) before continuing. No other
software (Python, Node, Postgres) needs to be installed on the host —
everything runs inside containers.

**1. Clone the repository and move into it:**
```bash
git clone <this-repo-url>
cd <repo-folder-name>
```
All commands below assume you are in this directory — the same one
that contains `docker-compose.yml`.

**2. Start everything:**
```bash
docker compose up --build
```
No `.env` file needs to be created manually — all required
environment values (database credentials, service URLs) are already
set directly in `docker-compose.yml`. An internet connection is
required, since the ingestion step fetches live data from the
Open-Meteo API.

The first run takes a few minutes (pulling base images, installing
Python/Node dependencies, building the Next.js production bundle).
You'll see the services start up in this order in the terminal
output: `postgres` becomes healthy → `ingest` runs once and exits →
`backend` starts → `frontend` starts.

**3. Verify it worked**, once the logs settle and you see the
frontend has started:
- Open http://localhost:3000 in a browser — a city dropdown and a
  forecast table should appear, already populated with real data (no
  manual step needed).
- Or, from a terminal: `curl http://localhost:8000/cities` should
  return `{"cities":["Ghent","Antwerp","Temse"]}`.
- Interactive API docs: http://localhost:8000/docs

**To stop everything:**
```bash
docker compose down
```
(Add `-v` to also delete the stored forecast data: `docker compose down -v`.)

**To trigger an additional ingestion run** (e.g. to demonstrate the
forecast-revision behavior live), while the stack is running:

```bash
docker compose run ingest
```

This adds a new, timestamped batch of forecasts on top of the
existing data — nothing is overwritten. Refresh the dashboard and
click a forecast row to see the new revision appear in its history.

**Troubleshooting — "address already in use" on port 8000 or 3000:**
this means something else on your machine is already using that port
(commonly a leftover local `uvicorn` or `npm run dev` process from
development, or a previous container that didn't shut down cleanly).
Check what's running with `docker ps` (look for old containers from
this project and stop them with `docker stop <container-id>`), or
identify and stop whatever process is bound to the port on the host,
then retry `docker compose up --build`.

## Architecture

Three independently deployable components:

1. **Ingestion** (`backend/ingest.py`) — a standalone script, not part
   of the API process. Fetches a 7-day hourly forecast per city from
   Open-Meteo and writes it to Postgres.
2. **API** (`backend/main.py`) — a read-only FastAPI service. Never
   writes to the database.
3. **Frontend** (`frontend/`) — a Next.js dashboard that consumes the
   API over HTTP.

### The forecast-revision problem

Open-Meteo's forecast for a given future hour changes depending on
when you ask. Rather than overwriting old values, every ingestion run
inserts new rows, keyed on `(city, target_time, ingested_at)` with a
database-level unique constraint. This makes both "give me the latest
forecast" and "show me how this hour's forecast changed over time"
simple queries, and gives idempotency for free: re-inserting an
identical key is a no-op (`ON CONFLICT DO NOTHING`), rather than
something the application has to detect itself.

A flat, single-table model was chosen over a normalized schema
(separate `cities`/`runs` tables) — at this scale the unique
constraint does the real work of enforcing correctness, and a flatter
table keeps both ingestion and querying simpler.

### Idempotency vs. revisions — a distinction that matters

Idempotency here specifically means: *retrying the same run* (e.g.
after a crash) must not duplicate data. It does **not** mean that two
separate, legitimate runs produce identical data — a new run an hour
or a day later is supposed to add a new revision. `run_ingestion()`
accepts an optional `run_timestamp` parameter: in normal use it
defaults to `datetime.now(timezone.utc)`, so real runs each get their
own timestamp and are stored as separate revisions; the automated
test instead passes the same fixed timestamp twice, to prove that
retrying one specific run is safe without ever discarding a real
revision.

(This was a deliberate correction made during development — an
earlier draft rounded the timestamp to the hour to make manual
re-testing convenient, which would have silently dropped genuine
revisions that happened to fall in the same hour. Fixed to use an
explicit, injectable timestamp instead.)

### Atomicity and resilience

Each city is ingested in its own database transaction, not one
transaction for the whole run and not one per row:
- **Atomic**: a city's full batch of ~168 hourly rows is written, or
  none of it is.
- **Resilient**: if one city's fetch or parse fails (timeout, bad
  response), it's logged and skipped — the other cities are
  unaffected. A whole-run transaction was considered and rejected,
  since it would roll back already-successful cities whenever one
  city fails.

### Backend layering

Route handlers in `main.py` stay thin — they validate input and call
`crud.py`, which owns the actual queries (e.g. the `/latest` lookup:
find `MAX(ingested_at)` for the city, then select all rows at that
exact timestamp — correct specifically because of the per-city
atomicity guarantee above, since a successful run never leaves a city
with a mix of stale and fresh hours). Pydantic response models
(`schemas.py`) are kept separate from the SQLAlchemy models
(`models.py`).

### Two environment-variable boundaries

- `DATABASE_URL` is container-to-container inside docker-compose
  (`postgres` service name) — different from the `.env` used for
  local, non-Docker development (`localhost:5432`).
- `NEXT_PUBLIC_API_URL` is browser-to-host: the browser runs outside
  the Docker network entirely, so it must resolve `localhost:8000`
  (the published port), not a Docker service name. It's also a
  **build-time** value — Next.js inlines `NEXT_PUBLIC_*` variables
  into the client JS bundle during `next build` — so it's passed as a
  Docker build `ARG`, not a runtime `environment:` entry.

## API

| Method | Path | Purpose |
|---|---|---|
| GET | `/cities` | List configured cities (from config, not a DB query) |
| GET | `/forecasts/{city}/latest` | Most recent forecast, one entry per hour |
| GET | `/forecasts/{city}/history?target_time=...` | Every revision for one specific hour, ordered by `ingested_at` |

Unknown city → `404`. Missing/invalid `target_time` → `422`
(validated automatically via FastAPI's `datetime` type hint, no manual
parsing). Valid city with no data yet → `200` + `[]`, not an error.

## What I deliberately cut, and why

- **No Alembic/migrations** — `create_all()` at startup is enough for
  a single, stable schema at this scope.
- **No retry-with-backoff** on the Open-Meteo fetch — a failed city is
  logged and skipped instead. With more time, I'd add one retry
  before giving up, since many failures against external APIs are
  transient.
- **No authentication or rate limiting** on the API — not relevant for
  a local case demo.
- **Only temperature** is ingested, not the full set of Open-Meteo
  variables — the data model supports adding more as additional
  columns without changing the key structure or the
  idempotency/atomicity mechanisms.
- **No automated scheduling** (cron container / GitHub Action) —
  ingestion is manually triggerable (`docker compose run ingest`).
  With more time, I'd add a cron container to the compose file, since
  it keeps the entire stack — including scheduling — reproducible via
  a single `docker compose up`, which matters more here than a
  GitHub Action would (a scheduled Action can't reach a database that
  only exists inside someone else's local `docker compose up`).
- **No separate `ingestion_runs` audit table** tracking per-run
  success/failure per city — logged to stdout instead. Useful in
  production for querying "how often does ingestion partially fail",
  not needed to prove the core model works.

## What I'd polish with more time

- The forecast-history panel (clicking a row) renders as an inline
  table row rather than a proper modal/popover — functional and clear,
  but a dedicated component would look more polished.
- A shared `run_id`/timestamp passed in by an external trigger (rather
  than each run computing its own `now()`) would be a cleaner
  foundation if ingestion frequency ever increased beyond daily.

## Testing

```bash
cd backend
source .venv/bin/activate
pytest tests/test_ingest.py -v
```

The idempotency test mocks the Open-Meteo call and asserts that
calling `run_ingestion()` twice with the same explicit timestamp
produces zero additional rows, without ever touching the network.

## AI-assisted workflow

This project was built with Claude Code, using plan mode for every
component: a written spec (`specs/`) was authored before any code was
generated, Claude Code proposed an implementation plan against that
spec, the plan was reviewed and corrected before approval, and the
finalized plan was committed (`specs/plans/`) alongside the resulting
code. Notable corrections made along the way are documented inline in
`specs/01-data-model-and-ingestion.md` (the idempotency-vs-revision
timestamp issue) and in the plan files.