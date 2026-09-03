# Ingestion component — implementation plan

## Context

The repo currently has only docs (`CLAUDE.md`, `PROJECT_SPEC.md`, `specs/`) —
no `backend/` code exists yet. This plan covers step 1 of the documented
build order (specs/01-data-model-and-ingestion.md only): the data model and
the standalone ingestion script. API and frontend are explicitly out of
scope for this plan.

Local dev Postgres is assumed already running (per CLAUDE.md's `docker run
... postgres:16` command), and `backend/.env` already contains
`DATABASE_URL=postgresql://postgres:postgres@localhost:5432/weather` (user
confirmed this file exists and is gitignored).

## Files to create

```
backend/
├── requirements.txt   # sqlalchemy, psycopg2-binary, python-dotenv, requests, pytest
├── db.py              # engine/session, reads DATABASE_URL via python-dotenv
├── config.py          # CITY_COORDINATES — shared by ingest.py now, main.py later
├── models.py          # Forecast model + unique constraint
├── ingest.py           # Open-Meteo fetch, run_ingestion()
└── tests/
    └── test_ingest.py  # idempotency test
```

`main.py`, `schemas.py`, `crud.py` are not created in this pass — they
belong to the API step (spec 02). `requirements.txt` gets FastAPI/uvicorn
added then, not now.

`config.py` is new relative to CLAUDE.md's listed structure — added so the
city list can be shared between `ingest.py` and the future `main.py`
without either importing the other. CLAUDE.md documents `ingest.py` as "not
imported by main.py"; spec 02 wants `GET /cities` to serve "the ingestion
config, not a database query." A shared, dependency-free `config.py` is how
both statements stay true at once.

## 1. `models.py` — SQLAlchemy model

```python
from sqlalchemy import Column, Integer, String, Numeric, DateTime, UniqueConstraint
from sqlalchemy.orm import declarative_base

Base = declarative_base()

class Forecast(Base):
    __tablename__ = "forecasts"

    id = Column(Integer, primary_key=True)
    city = Column(String, nullable=False)
    target_time = Column(DateTime(timezone=True), nullable=False)
    ingested_at = Column(DateTime(timezone=True), nullable=False)
    temperature_c = Column(Numeric, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "city", "target_time", "ingested_at",
            name="uq_forecasts_city_target_time_ingested_at",
        ),
    )
```

- `DateTime(timezone=True)` maps to Postgres `TIMESTAMPTZ`, per CLAUDE.md's
  "never naive datetimes" rule.
- The unique constraint is what `ON CONFLICT (city, target_time,
  ingested_at) DO NOTHING` in `ingest.py` targets — enforced at the DB
  level, not in application code.
- Indexes on `(city, ingested_at)` and `(city, target_time)` (spec 02) are
  **not** added here — deferred to the API step, since they exist to serve
  API query patterns and this pass is ingestion-only.

## 2. `db.py` — engine/session setup

```python
import os
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

load_dotenv()

DATABASE_URL = os.environ["DATABASE_URL"]

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
```

- `os.environ["DATABASE_URL"]` (not `.get()` with a default) — fails loudly
  if the env var is missing, rather than silently falling back to a
  hardcoded string, which CLAUDE.md forbids.
- `load_dotenv()` picks up `backend/.env` when run from `backend/`, matching
  the "Run ingestion manually: `cd backend && python ingest.py`" command in
  CLAUDE.md.
- No `get_db()` FastAPI dependency here — that's API-step scaffolding.
  `ingest.py` opens `SessionLocal()` directly per city (see below).

## 3. City config (`config.py`) + Open-Meteo fetch (`ingest.py`)

`config.py`:

```python
CITY_COORDINATES = {
    "Ghent": (51.05, 3.72),
    "Antwerp": (51.22, 4.40),
    "Temse": (51.13, 4.21),
}
```

`ingest.py`:

```python
from config import CITY_COORDINATES

def fetch_forecast(latitude: float, longitude: float) -> dict:
    response = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": latitude,
            "longitude": longitude,
            "hourly": "temperature_2m",
            "forecast_days": 7,
            "timezone": "UTC",
        },
        timeout=10,
    )
    response.raise_for_status()
    return response.json()
```

**Timezone detail (corrected):** per Open-Meteo's own docs, the API
defaults to UTC — "Per default, all time is interpreted as GMT (UTC+0)." It
is passing `timezone=auto` or a named zone that would switch the response
to local time, not the absence of a `timezone` param. So `timezone=UTC` is
not fixing a wrong default; it's making the already-correct default
explicit and self-documenting in the request, so the behavior doesn't
silently depend on Open-Meteo's default rather than a value this code
states on purpose. `datetime.fromisoformat(t).replace(tzinfo=timezone.utc)`
is correct either way, but only because `timezone=UTC` is passed.

City coordinates live in `config.py`, not `ingest.py`, specifically so
`main.py` can import the same city list in the API step (spec 02's `GET
/cities`) without importing `ingest.py` itself — keeping CLAUDE.md's "not
imported by main.py" note about `ingest.py` true while still sharing one
source of truth for the city list.

## 4. `run_ingestion()` signature

```python
def run_ingestion(run_timestamp: datetime | None = None) -> None:
    if run_timestamp is None:
        run_timestamp = datetime.now(timezone.utc)
    ...
```

- Computed/defaulted once at the top, then threaded through the per-city
  loop as the single shared `ingested_at` for every row in the run.
- Returns `None` (or a simple summary dict for logging purposes) — the test
  doesn't rely on a return value, it queries the DB directly (see §6),
  which is the more reliable way to prove idempotency than trusting a
  self-reported row count.

## 5. Per-city loop — atomicity + resilience

```python
from sqlalchemy.dialects.postgresql import insert as pg_insert

for city, (lat, lon) in CITY_COORDINATES.items():
    try:
        payload = fetch_forecast(lat, lon)
        rows = _parse_rows(city, payload, run_timestamp)  # validates shape
    except (requests.RequestException, KeyError, ValueError) as exc:
        logger.error("%s: fetch/parse failed: %s", city, exc)
        continue

    try:
        with SessionLocal() as session:
            stmt = pg_insert(Forecast).values(rows)
            stmt = stmt.on_conflict_do_nothing(
                index_elements=["city", "target_time", "ingested_at"]
            )
            result = session.execute(stmt)
            session.commit()
            logger.info("%s: inserted %d rows", city, result.rowcount)
    except SQLAlchemyError as exc:
        session.rollback()
        logger.error("%s: DB write failed: %s", city, exc)
        continue
```

- Two nested try/excepts per city, matching the spec's two distinct
  failure modes: **resilient** (fetch/parse) and **atomic** (DB write) —
  each logs a distinct reason, and either failure `continue`s to the next
  city without affecting the others.
- `SessionLocal()` opened fresh per city → one transaction per city, not
  per run and not per row, per spec.
- `_parse_rows` validates `payload["hourly"]["time"]` and
  `payload["hourly"]["temperature_2m"]` are present and equal length before
  zipping them into row dicts — this is the "validate the response" step
  from the spec's ingestion flow.
- `Base.metadata.create_all(engine)` is called once at the top of
  `run_ingestion()` (or at module import in `ingest.py`), so the script
  works against a genuinely fresh Postgres container even if the API
  (which will also call `create_all()` at startup per CLAUDE.md) hasn't run
  yet — ingestion must not depend on API startup order.
- One-line-per-city logging via the stdlib `logging` module, per spec.

## 6. `tests/test_ingest.py` — idempotency test

- Patches `ingest.fetch_forecast` with a stub returning a small fixed
  canned payload (e.g. 3 hours of `time`/`temperature_2m`), so the test is
  deterministic and doesn't depend on network access or Open-Meteo being
  up — same stub regardless of city/coordinates passed in.
- Uses a fixed `run_timestamp` (e.g. `datetime(2026, 1, 1, tzinfo=timezone.utc)`).
- Runs against the same local dev Postgres from `DATABASE_URL` (no separate
  test DB — none is specified anywhere in CLAUDE.md/specs, and the case
  scope is "one focused idempotency test").
- Test flow:
  1. `Base.metadata.create_all(engine)` to ensure the table exists.
  2. Delete any pre-existing rows with `ingested_at == fixed_time` (defensive
     cleanup in case a previous failed run left residue).
  3. Call `run_ingestion(run_timestamp=fixed_time)`.
  4. Query DB: assert row count with `ingested_at == fixed_time` equals the
     expected count (3 cities × 3 stub hours = 9).
  5. Call `run_ingestion(run_timestamp=fixed_time)` again.
  6. Assert the count is **unchanged** — this is the actual idempotency
     assertion from the acceptance criteria.
  7. `finally:` delete the rows with that `ingested_at`, so the test is
     self-cleaning and re-runnable, and doesn't pollute real ingestion data.
- This directly satisfies spec 01's acceptance criteria: "Calling
  `run_ingestion()` twice with the same explicit `run_timestamp` produces
  zero additional rows."

## 7. CLI entrypoint (`ingest.py`)

```python
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_ingestion()
```

Without this, `python ingest.py` (CLAUDE.md's documented manual-run command)
imports the module but executes nothing. `logging.basicConfig` is set here,
not at module import time, so importing `ingest` (e.g. from the test file)
doesn't force logging config on the importer.

## Verification

1. `cd backend && pip install -r requirements.txt`
2. Confirm local Postgres is reachable: `psql $DATABASE_URL -c '\dt'` (or
   just proceed — `create_all()` will create the table).
3. `python ingest.py` — inspect logs, then query Postgres directly to
   confirm ~168 rows per city (7 days × 24h) were written.
4. Run `python ingest.py` again — expect a **new** batch of rows (fresh
   `run_timestamp`, legitimate new revision), not zero rows — this is the
   real-usage case, distinct from the test's fixed-timestamp case.
5. `cd backend && pytest tests/test_ingest.py -v` — confirm the idempotency
   test passes.
