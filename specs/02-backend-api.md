# Spec 02 — Backend API

## Goal

Expose the data written by ingestion (see specs/01) through a
read-only FastAPI service. The API never writes to the database —
that is ingestion's job only.

## Code structure within this component

Route handlers (routers) do not query the database directly. Each
route delegates to a separate query/service function
(e.g. in `crud.py` or `queries.py`) that takes the DB session and
parameters, and returns plain data — the route function's only job is
request handling (path/query params, calling the query function,
shaping the HTTP response, raising the right status code).

This mirrors the classic controller → service → repository split: the
router is the controller, the query functions are the
service/repository layer. Reasons this matters for this scope:
- The `/latest` query logic (the `MAX(ingested_at)` lookup, including
  the empty-database `None` case) is non-trivial enough to deserve a
  unit test of its own, independent of the HTTP layer — that's only
  possible if it isn't buried inside a route function.
- Pydantic response models (`schemas.py`) stay separate from
  SQLAlchemy models (`models.py`), same DTO-vs-entity separation as
  spec 01's data model.

## Endpoints

### GET /cities

- Purpose: list the configured cities, for the frontend's city
  picker.
- Parameters: none.
- Response shape: `{ "cities": ["Ghent", "Antwerp", "Temse"] }`
- Error cases: none expected — this is a static, hardcoded list from
  the ingestion config, not a database query.

### GET /forecasts/{city}/latest

- Purpose: the most recent forecast for every target hour available
  for this city — the normal "weather report" view.
- Path parameter: `city` (must match one of the configured cities).
- Response shape: a list of entries, one per target hour, each with
  `target_time` and `temperature_c`, all drawn from the row with the
  highest `ingested_at` per `target_time`.
- Query strategy: find `MAX(ingested_at)` for this city as a single
  value, then select all rows matching that exact `ingested_at`
  (rather than a `DISTINCT ON (target_time)` per-hour lookup). This is
  correct — not just simpler — specifically because of the per-city
  atomicity guarantee in specs/01: a successful run writes the
  complete set of target hours for a city in one transaction, so there
  is never a mix of stale and fresh hours within the latest batch. If
  that atomicity guarantee ever changed, this query would need
  revisiting.
- Error cases:
  - Unknown city → `404`, body explains which cities are valid.
  - No data yet for this city (ingestion hasn't run yet — the `MAX
    (ingested_at)` subquery returns `NULL`) → `200` with an empty
    list, not a crash and not a `404`. The city itself is valid; there
    is just no forecast yet. The route must explicitly check for this
    `None` case before using it in the row-matching query, rather than
    letting a `None` comparison silently return zero rows or raise.

### GET /forecasts/{city}/history

- Purpose: how the forecast for one specific target hour evolved
  across ingestion runs.
- Path parameter: `city`.
- Query parameter: `target_time` (ISO 8601 datetime string, required).
- Response shape: a list of entries, one per ingestion run that
  produced a forecast for that hour, each with `ingested_at` and
  `temperature_c`, ordered by `ingested_at` ascending.
- Error cases:
  - Unknown city → `404`.
  - Missing or unparseable `target_time` → `422`.
  - Valid city + valid `target_time`, but no data exists for it yet
    → `200` with an empty list (not a `404` — the city is real, there
    just isn't a forecast for that exact hour yet).

## Conventions

- All datetimes in requests and responses are ISO 8601 strings in UTC.
- `target_time` on the history endpoint is declared with a `datetime`
  type hint in the route signature. FastAPI/Pydantic validates and
  parses ISO 8601 automatically and raises `422` itself on an invalid
  value — no manual `datetime.fromisoformat()` / try-except parsing
  needed in the route handler.
- Error responses use FastAPI's default `{ "detail": "..." }` shape —
  no custom error envelope needed for this scope.
- CORS: `CORSMiddleware` is enabled for `http://localhost:3000` (the
  Next.js dev server origin), so browser requests from the frontend
  aren't blocked. This is a development-only setting — in production
  you'd restrict it to the actual deployed frontend origin instead of
  leaving it wide open.
- Interactive API docs (`/docs`) are available for free via FastAPI —
  used as the primary way to manually test endpoints during
  development, no separate Postman collection needed.
- Database indexes on `(city, ingested_at)` and `(city, target_time)`
  are added on the `forecasts` table, so both the `/latest` subquery
  and the `/history` lookup are index scans rather than full table
  scans once the table grows.

## Out of scope for this part

- Authentication / API keys
- Rate limiting
- Pagination (response sizes here are small — a week of hourly data
  per city — so it isn't needed at this scale)
- Write endpoints of any kind — ingestion is the only writer

## Acceptance criteria

- [ ] `GET /cities` returns the 3 configured cities
- [ ] `GET /forecasts/Ghent/latest` returns one entry per target hour,
      using the most recent `ingested_at` for each
- [ ] `GET /forecasts/Ghent/history?target_time=...` returns every
      revision for that hour, ordered by `ingested_at`
- [ ] Unknown city returns `404` on both forecast endpoints
- [ ] Missing/invalid `target_time` returns `422` on the history
      endpoint
- [ ] `GET /forecasts/{city}/latest` on a city with no ingested data
      yet returns `200` with an empty list, not a crash
- [ ] A request from `http://localhost:3000` is not blocked by CORS