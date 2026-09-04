# Docker Compose integration — implementation plan

## Context

All three components (ingestion, backend API, frontend) are implemented
and individually verified against a local dev Postgres. This is the
final integration step (PROJECT_SPEC.md step 4 / CLAUDE.md's "Run
everything: `docker compose up --build`"): wire them into a single
`docker compose up` that works from a clean clone, matching
PROJECT_SPEC.md's "Everything must start with a single command."

Two env-var boundaries matter here, and get confused easily:
- `DATABASE_URL` is **container-to-container** (ingest/backend →
  `postgres` service name) — different from the root `.env`'s
  `localhost:5432`, which stays as-is for local (non-Docker) dev per
  CLAUDE.md's existing commands.
- `NEXT_PUBLIC_API_URL` is **browser-to-host** — the browser runs
  outside the Docker network entirely, so it must resolve
  `localhost:8000` (the published port), not a service name. This one
  is also a **build-time** value (Next.js inlines `NEXT_PUBLIC_*` into
  the client JS bundle during `next build`), so it has to be passed as
  a Docker build ARG, not a runtime container env var — setting it only
  in `docker-compose.yml`'s `environment:` would compile a bundle with
  the var missing, and nothing would surface that mistake until the
  browser's fetches silently 404/CORS-fail.

## Files touched

```
backend/
├── Dockerfile        # new
└── .dockerignore      # new — keeps .venv/, __pycache__/, tests/ out of the build context
frontend/
├── Dockerfile         # new
└── .dockerignore       # new — keeps node_modules/, .next/ out of the build context
docker-compose.yml     # new, repo root
```

## 1. `backend/Dockerfile` (new)

```dockerfile
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- `python:3.12-slim`: no version-specific syntax in the codebase, so a
  standard current slim tag is fine — smaller than the full image,
  widely available.
- Requirements copied and installed before the rest of the source so
  the pip-install layer is cached across source-only changes.
- `--host 0.0.0.0` is required — the default `127.0.0.1` would refuse
  connections from outside the container (i.e. from `docker-compose`'s
  published port or from the `frontend`/other containers).
- No `CMD` override needed for the default (`backend`) service — the
  `ingest` service in `docker-compose.yml` overrides `command` to run
  `python ingest.py` instead, reusing this same image.
- `backend/.dockerignore`: `.venv/`, `__pycache__/`, `*.pyc`,
  `.pytest_cache/`, `.env` — mirrors CLAUDE.md's own `.gitignore`
  entries for this directory; keeps the build context small and avoids
  leaking a host-built `.venv` into the image. `.env` is included
  defensively — the repo's only `.env` currently lives at the repo
  root (outside `backend/`'s build context), but `COPY . .` should
  never have a path to bundle a local dev env file into the image even
  if one were later added inside `backend/`.

## 2. `frontend/Dockerfile` (new)

```dockerfile
FROM node:22-slim

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm install

COPY . .

ARG NEXT_PUBLIC_API_URL
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL

RUN npm run build

EXPOSE 3000
CMD ["npm", "start"]
```

- `node:22-slim` to match the Node version already used in local dev
  (`v22.22.1`) — this app already depends on very recent
  Next.js/React majors, so staying close to the tested local version
  avoids surprises.
- `package.json`/`package-lock.json` copied and installed before the
  rest of the source, same caching rationale as the backend.
- **The critical piece**: `ARG NEXT_PUBLIC_API_URL` declared, then
  re-exposed as `ENV` *before* `RUN npm run build` — Next.js's build
  step reads it from `process.env` at that point and inlines it into
  the client bundle. Declaring it only as `ARG` (without the `ENV`
  line) would leave it unset during the actual `next build` process
  substitution in some Next.js versions' env-loading path, so both
  lines are kept.
- `npm start` (→ `next start`) serves the already-built `.next` output;
  it does not rebuild, so the inlined value from build time is what
  ships — matches the plan's "serve via npm start."
- `frontend/.dockerignore`: `node_modules/`, `.next/`, `.env.local` —
  the container installs its own `node_modules` and builds its own
  `.next`; a stale host copy of either must not be copied in.

## 3. `docker-compose.yml` (new, repo root)

```yaml
services:
  postgres:
    image: postgres:16
    environment:
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres
      POSTGRES_DB: weather
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 5s
      timeout: 5s
      retries: 5

  ingest:
    build: ./backend
    command: python ingest.py
    environment:
      DATABASE_URL: postgresql://postgres:postgres@postgres:5432/weather
    depends_on:
      postgres:
        condition: service_healthy
    restart: "no"

  backend:
    build: ./backend
    environment:
      DATABASE_URL: postgresql://postgres:postgres@postgres:5432/weather
    ports:
      - "8000:8000"
    depends_on:
      postgres:
        condition: service_healthy
      ingest:
        condition: service_completed_successfully

  frontend:
    build:
      context: ./frontend
      args:
        NEXT_PUBLIC_API_URL: http://localhost:8000
    ports:
      - "3000:3000"
    depends_on:
      - backend

volumes:
  pgdata:
```

- `postgres`: named volume `pgdata` for persistence across
  `docker compose down` (without `-v`); `pg_isready` healthcheck is
  what `ingest`/`backend` gate on, so neither starts against a
  not-yet-accepting-connections Postgres.
- `ingest`: reuses the `backend` image (own `build: ./backend`, so
  Compose builds/tags it separately from `backend`'s image — simplest
  option here without extracting a shared base image, and matches the
  plan's "builds from backend/"), overrides `command` to
  `python ingest.py` (CLAUDE.md's own documented ingestion entrypoint),
  runs to completion once, `restart: "no"` so it doesn't loop.
- `backend`: gates on **both** `postgres` healthy and `ingest` having
  exited 0 (`service_completed_successfully`) — guarantees the API
  never serves before at least one ingestion run has populated data,
  satisfying the plan's "dashboard shows real data without any manual
  step."
- `frontend`: `build.args.NEXT_PUBLIC_API_URL: http://localhost:8000` —
  the host-published port, reachable from the browser; `depends_on:
  backend` only waits for container start (no healthcheck defined on
  `backend`), which is fine here since the frontend fetches
  client-side on page load, by which time `uvicorn` (a fast-starting
  process) is virtually always already accepting connections.
- Root `.env` is untouched — it's for the non-Docker local-dev path
  (`uvicorn`/`ingest.py` run directly against `localhost:5432`) and is
  unrelated to the `DATABASE_URL` values set directly in this compose
  file.

## Verification

1. `docker compose down -v` (clean slate — drops the named volume too).
2. `docker compose up --build`.
3. Watch the log interleaving: `postgres` becomes healthy → `ingest`
   runs and exits 0 → `backend` starts → `frontend` builds and starts.
4. `curl http://localhost:8000/cities` → real city list.
5. `curl http://localhost:8000/forecasts/Ghent/latest` → non-empty,
   real forecast rows (proves `ingest` ran before `backend` served
   traffic).
6. Open `http://localhost:3000` in a browser — city select populated,
   table shows real data, with **no manual step** (no `.env` edits, no
   manually running ingestion) — confirms the `NEXT_PUBLIC_API_URL`
   build-arg actually made it into the client bundle (if it hadn't,
   fetches would silently fail against `undefined`/relative URLs).
7. `docker compose down` (without `-v`), `docker compose up` again
   (no `--build`) — confirms Postgres data persisted via the `pgdata`
   volume and `ingest` still runs (re-ingesting is idempotent per the
   existing unique constraint, so no duplicate rows).
