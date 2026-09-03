# Backend API — implementation plan

## Context

Ingestion (spec 01) is done: `backend/config.py`, `backend/db.py`,
`backend/models.py` exist and a working `ingest.py` has been run against
local dev Postgres. This plan covers step 2 of the build order (spec
02-backend-api.md only): a read-only FastAPI service on top of the
existing `forecasts` table. Frontend is explicitly out of scope.

The API never writes — ingestion is the only writer. Routes stay thin
(parse input, call `crud.py`, shape response); query logic lives in
`crud.py`, not in route functions, per CLAUDE.md and spec 02.

## Files touched

```
backend/
├── requirements.txt   # + fastapi, uvicorn[standard]
├── db.py              # + get_db() session-per-request dependency
├── models.py           # + two indexes in __table_args__
├── schemas.py          # new — Pydantic response models
├── crud.py             # new — query/service layer
└── main.py             # new — FastAPI app, CORS, startup, 3 routes
```

`config.py` is read, not modified — `CITY_COORDINATES` is already the
single source of truth for the city list, exactly as spec 02's `GET
/cities` wants ("the ingestion config, not a database query").

## 1. `models.py` — indexes (modifies existing file)

Add to `Forecast.__table_args__`, alongside the existing unique constraint:

```python
Index("ix_forecasts_city_ingested_at", "city", "ingested_at"),
Index("ix_forecasts_city_target_time", "city", "target_time"),
```

These serve the `/latest` `MAX(ingested_at)` lookup and the `/history`
`(city, target_time)` lookup respectively, per spec 02's explicit index
requirement. `Index` added to the existing `sqlalchemy` import line.

## 2. `db.py` — add `get_db()` (modifies existing file)

```python
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
```

Standard FastAPI session-per-request dependency, added here rather than in
a new file because `db.py` already owns `SessionLocal`/`engine` — this is
the same responsibility, just exposed as a generator for `Depends()`.
`engine` and `SessionLocal` stay as they are.

## 3. `schemas.py` — Pydantic response models (new)

```python
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class CitiesResponse(BaseModel):
    cities: list[str]


class ForecastEntry(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    target_time: datetime
    temperature_c: float


class HistoryEntry(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    ingested_at: datetime
    temperature_c: float
```

- `from_attributes=True` (Pydantic v2's `orm_mode`) lets FastAPI build
  these directly from `Forecast` ORM rows returned by `crud.py` — routes
  just `return` the ORM objects, no manual dict-building.
- Kept separate from `models.py`'s `Forecast` (DTO vs. entity), per spec
  02's explicit reasoning.
- `temperature_c: float` — the DB column is `Numeric`/`Decimal`; Pydantic
  coerces it to `float` for JSON output, matching spec 02's "ISO 8601
  strings in UTC" / plain-JSON convention (no `Decimal` in responses).

## 4. `crud.py` — query/service layer (new)

```python
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from models import Forecast


def get_latest_forecast(db: Session, city: str) -> list[Forecast]:
    latest_ingested_at = db.scalar(
        select(func.max(Forecast.ingested_at)).where(Forecast.city == city)
    )
    if latest_ingested_at is None:
        return []

    return db.scalars(
        select(Forecast)
        .where(Forecast.city == city, Forecast.ingested_at == latest_ingested_at)
        .order_by(Forecast.target_time)
    ).all()


def get_forecast_history(
    db: Session, city: str, target_time: datetime
) -> list[Forecast]:
    return db.scalars(
        select(Forecast)
        .where(Forecast.city == city, Forecast.target_time == target_time)
        .order_by(Forecast.ingested_at)
    ).all()
```

- `get_latest_forecast`: exactly spec 02's query strategy — one
  `MAX(ingested_at)` scalar query, explicit `None` check returning `[]`
  (empty DB / not-yet-ingested city), then a second query selecting every
  row at that exact `ingested_at`. Ordered by `target_time` so the API
  returns hours in chronological order for the UI table.
- `get_forecast_history`: filters on `(city, target_time)`, ordered by
  `ingested_at` ascending per spec. No special empty-case handling needed
  — a query with no matches already returns `[]` naturally, satisfying
  "no data for this hour → 200 + `[]`, not 404" for free.
- Both return plain `Forecast` ORM rows (not raw SQL tuples) — this is the
  "plain data" spec 02 asks for, and pairs with `schemas.py`'s
  `from_attributes=True` so route handlers don't need conversion code.
- City existence is **not** checked here — that's a route-level concern
  (404 vs. valid-but-empty is an HTTP decision), handled in `main.py`.

## 5. `main.py` — FastAPI app + 3 routes (new)

```python
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

import crud
import schemas
from config import CITY_COORDINATES
from db import engine, get_db
from models import Base

CITIES = list(CITY_COORDINATES)


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(engine)
    yield


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


def validate_city(city: str) -> str:
    if city not in CITY_COORDINATES:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown city '{city}'. Valid cities: {CITIES}",
        )
    return city


@app.get("/cities", response_model=schemas.CitiesResponse)
def list_cities():
    return {"cities": CITIES}


@app.get("/forecasts/{city}/latest", response_model=list[schemas.ForecastEntry])
def latest_forecast(
    city: str = Depends(validate_city),
    db: Session = Depends(get_db),
):
    return crud.get_latest_forecast(db, city)


@app.get("/forecasts/{city}/history", response_model=list[schemas.HistoryEntry])
def forecast_history(
    target_time: datetime,
    city: str = Depends(validate_city),
    db: Session = Depends(get_db),
):
    return crud.get_forecast_history(db, city, target_time)
```

Notes on the specific requirements:

- **`Base.metadata.create_all(engine)` at startup** — via a `lifespan`
  context manager (current non-deprecated FastAPI pattern; `@app.on_event`
  is deprecated). Matches CLAUDE.md: "`create_all()` at startup is
  sufficient for this scope."
- **CORS** — `CORSMiddleware` scoped to `http://localhost:3000` only,
  `allow_methods=["GET"]` since this API is read-only (no write routes
  exist to allow).
- **`GET /cities`** — no DB session dependency at all; reads `CITY_COORDINATES`
  directly, per spec 02 ("a static, hardcoded list... not a database
  query").
- **404 for unknown city** — factored into one `validate_city` dependency
  used by both forecast routes (via `Depends`, resolved against the
  `{city}` path param automatically), instead of duplicating the same
  `if city not in CITY_COORDINATES: raise HTTPException(404, ...)` in two
  route bodies.
- **`target_time: datetime`** — plain required query param (no default),
  typed as `datetime` directly in the signature. FastAPI/Pydantic parses
  ISO 8601 and raises `422` automatically on missing/invalid values — no
  manual `fromisoformat`/try-except in the route, per spec 02's explicit
  instruction. (Placed first in the parameter list since it has no
  default, ahead of the `Depends(...)` parameters, to satisfy Python's
  argument-ordering rules — FastAPI resolves them independently of
  declaration order.)
- **Empty result → 200 + `[]`** — routes just `return` whatever `crud.py`
  gives back; both crud functions already produce `[]` rather than
  raising, so no additional handling needed in the route bodies.
- **No `/docs`-related code needed** — FastAPI serves interactive docs at
  `/docs` automatically once `app = FastAPI(...)` exists.

## 6. `requirements.txt` — add API deps

```
fastapi>=0.115
uvicorn[standard]>=0.30
```

Appended to the existing `sqlalchemy`/`psycopg2-binary`/`python-dotenv`/
`requests`/`pytest` lines from the ingestion step.

## Verification

1. `cd backend && .venv/bin/pip install -r requirements.txt`
2. `cd backend && .venv/bin/uvicorn main:app --reload`
3. Open `http://localhost:8000/docs` — confirm all 3 routes are listed.
4. `curl localhost:8000/cities` → `{"cities":["Ghent","Antwerp","Temse"]}`
5. `curl localhost:8000/forecasts/Ghent/latest` → 168 entries (from the
   ingestion runs already in the DB), each with `target_time` +
   `temperature_c`.
6. `curl localhost:8000/forecasts/Nowhere/latest` → `404`.
7. `curl 'localhost:8000/forecasts/Ghent/history?target_time=<one of the
   target_time values from step 5>'` → one entry per prior ingestion run,
   ordered by `ingested_at` ascending (there are 2 real runs from spec 01
   verification, so 2 entries expected).
8. `curl localhost:8000/forecasts/Ghent/history` (no `target_time`) →
   `422`. `curl '.../history?target_time=not-a-date'` → `422`.
9. `curl 'localhost:8000/forecasts/Ghent/history?target_time=2099-01-01T00:00:00Z'`
   (a real city, a target_time with no data) → `200` + `[]`.
10. `curl -H 'Origin: http://localhost:3000' -I localhost:8000/cities` →
    confirm `access-control-allow-origin: http://localhost:3000` header
    present.
