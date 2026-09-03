# CLAUDE.md

## Project

Ella Energy take-home case: ingest Belgian weather forecasts (Ghent,
Antwerp, Temse) from Open-Meteo into Postgres, expose them via a
FastAPI service, and display them in a Next.js dashboard. See
`PROJECT_SPEC.md` for the full context and `specs/` for the
per-component decisions — this file is conventions and commands only,
not architecture. Do not restate architectural decisions here; link
to the relevant spec instead.

## Tech stack

- Backend: Python, FastAPI, SQLAlchemy, Postgres 16
- Frontend: Next.js (App Router), TypeScript, shadcn/ui
- Infra: Docker Compose

## Repo structure

```
├── PROJECT_SPEC.md
├── CLAUDE.md
├── docker-compose.yml
├── specs/
│   ├── 01-data-model-and-ingestion.md
│   ├── 02-backend-api.md
│   └── 03-frontend-ui.md
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── db.py          # DB session/engine, reads DATABASE_URL
│   ├── models.py      # SQLAlchemy models
│   ├── schemas.py      # Pydantic response models
│   ├── crud.py         # query/service layer — routes call this, not the DB directly
│   ├── ingest.py        # standalone ingestion entrypoint, not imported by main.py
│   ├── main.py           # FastAPI app + routers
│   └── tests/
│       └── test_ingest.py
└── frontend/
    ├── Dockerfile
    ├── package.json
    ├── app/
    │   └── page.tsx
    └── lib/
        └── api.ts       # API client — components call this, not fetch directly
```

## Key architectural decisions

Fixed decisions, already made — do not revisit without updating the
relevant spec file first:

- Data model, unique constraint, per-city atomicity, `run_timestamp`
  parameter behavior → specs/01-data-model-and-ingestion.md
- Endpoint contracts, router/crud layering, `/latest` query strategy
  → specs/02-backend-api.md
- Views, data fetching, `NEXT_PUBLIC_API_URL` behavior → specs/03-frontend-ui.md

## Commands

- Start local dev Postgres: `docker run --name dev-postgres -e
  POSTGRES_PASSWORD=postgres -e POSTGRES_DB=weather -p 5432:5432 -d
  postgres:16`
- Run ingestion manually: `cd backend && python ingest.py`
- Run backend dev server: `cd backend && uvicorn main:app --reload`
- Run backend tests: `cd backend && pytest`
- Run frontend dev server: `cd frontend && npm run dev`
- Run everything: `docker compose up --build`

## Conventions

- All DB access goes through `DATABASE_URL` (env var) — never a
  hardcoded connection string, in either `backend/` or `ingest.py`.
- All timestamps are UTC `TIMESTAMPTZ` / timezone-aware — never naive
  datetimes.
- Route handlers in `main.py` stay thin: parse input, call `crud.py`,
  shape the response. No raw SQL/ORM queries inside route functions.
- Frontend components call `lib/api.ts`, never `fetch` directly.
- No external date library in the frontend — native
  `Date.toLocaleString()` is sufficient.

## What NOT to do

- Do not add Alembic/migrations — `create_all()` at startup is
  sufficient for this scope.
- Do not add retry-with-backoff to the ingestion fetch — this was
  deliberately cut, see specs/01.
- Do not use a Docker-internal service name (e.g. `http://backend:8000`)
  for client-side frontend fetches — the browser can't resolve it;
  use `NEXT_PUBLIC_API_URL=http://localhost:8000`.
- Do not install shadcn/ui components beyond `table` and `select`
  without checking specs/03 first.
- Do not change the unique constraint or the flat single-table model
  without updating specs/01 first — this is the core of the case.