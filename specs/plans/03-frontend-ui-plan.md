# Frontend UI — implementation plan

## Context

Backend (specs 01 + 02) is done and running at `http://localhost:8000`:
`GET /cities`, `GET /forecasts/{city}/latest`, `GET
/forecasts/{city}/history?target_time=...`. This plan covers the final
build step, spec 03 only: a minimal Next.js dashboard on top of that
read-only API. No backend/docker-compose changes.

View 1 (city picker + latest forecast table) is the must-have. View 2
(row-click → revision history) is a stretch, built only once View 1 is
verified working end-to-end against the real API.

## Files touched

```
frontend/                    # new, via create-next-app
├── package.json
├── tsconfig.json
├── tailwind.config.ts
├── components.json          # shadcn config
├── .env.local               # NEXT_PUBLIC_API_URL=http://localhost:8000 (gitignored)
├── app/
│   ├── layout.tsx            # create-next-app default
│   └── page.tsx              # View 1 (+ View 2 if time allows)
├── components/ui/
│   ├── table.tsx              # via shadcn add
│   └── select.tsx             # via shadcn add
└── lib/
    ├── api.ts                 # API client
    └── utils.ts                # shadcn default (cn() helper)
```

## 1. Project scaffold

```
npx create-next-app@latest frontend --typescript --tailwind --app \
  --no-src-dir --import-alias "@/*" --eslint
cd frontend
npx shadcn@latest init -d
npx shadcn@latest add table select
```

- `--app`: App Router per spec.
- `-d` on `shadcn init`: accept defaults (no custom theme/design pass —
  spec 03 explicitly deprioritizes polish).
- Only `table` and `select` installed — matches CLAUDE.md's "do not
  install shadcn/ui components beyond `table` and `select` without
  checking specs/03 first."
- `.env.local` created manually after scaffold: `NEXT_PUBLIC_API_URL=http://localhost:8000`.
  Next.js's default `.gitignore` (from `create-next-app`) already
  excludes `.env*.local`, so no manual gitignore edit needed.

## 2. `lib/api.ts` — API client (new)

```typescript
const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export interface ForecastEntry {
  target_time: string;
  temperature_c: number;
}

export interface HistoryEntry {
  ingested_at: string;
  temperature_c: number;
}

async function fetchJson<T>(path: string): Promise<T> {
  const res = await fetch(`${API_URL}${path}`);
  if (!res.ok) {
    throw new Error(`Request to ${path} failed: ${res.status}`);
  }
  return res.json();
}

export function getCities(): Promise<string[]> {
  return fetchJson<{ cities: string[] }>("/cities").then((data) => data.cities);
}

export function getLatestForecast(city: string): Promise<ForecastEntry[]> {
  return fetchJson(`/forecasts/${encodeURIComponent(city)}/latest`);
}

export function getForecastHistory(
  city: string,
  targetTime: string
): Promise<HistoryEntry[]> {
  const qs = new URLSearchParams({ target_time: targetTime });
  return fetchJson(`/forecasts/${encodeURIComponent(city)}/history?${qs}`);
}
```

- Base URL: `NEXT_PUBLIC_API_URL` env var, `http://localhost:8000` fallback
  — matches spec 03 exactly (`NEXT_PUBLIC_*` is required for browser-side
  access in Next.js; server-only env vars aren't visible to client
  components).
- All three exported functions are called from `page.tsx` — components
  never call `fetch` directly, per CLAUDE.md.
- `target_time` is passed through as the raw ISO string already returned
  by `/latest` (not re-encoded via `Date`) — avoids any timezone-shift
  risk in the round-trip back to `/history`, and `URLSearchParams` handles
  the encoding.
- Response shapes mirror `backend/schemas.py`'s `ForecastEntry`/`HistoryEntry`
  exactly (`target_time`/`ingested_at` as ISO strings — JSON has no native
  date type — `temperature_c` as `number`).
- Error handling is deliberately minimal (throw on non-OK status) — no
  retry/backoff, matching the ingestion-side precedent of cutting that
  scope, and spec 03's "basic error state only."

## 3. `app/page.tsx` — View 1 (+ View 2 stretch)

Single client component (`"use client"` at the top — needed for
`useState`/`useEffect` and click handlers).

**State:**
```typescript
const [cities, setCities] = useState<string[]>([]);
const [selectedCity, setSelectedCity] = useState<string | null>(null);
const [forecast, setForecast] = useState<ForecastEntry[]>([]);
const [loading, setLoading] = useState(false);
const [error, setError] = useState<string | null>(null);
```

**Effects:**
- On mount: `getCities()` → `setCities`, then default-select the first
  city (`setSelectedCity(cities[0])`) so the table isn't empty on load.
- On `selectedCity` change: `getLatestForecast(selectedCity)`, with
  `loading`/`error` set around the call. Guard against setting state
  after unmount isn't needed at this scope (no cleanup function) — matches
  spec 03's "no error boundaries beyond a basic message."

**Render:**
- shadcn `Select` bound to `cities`, `onValueChange` sets `selectedCity`.
- `if (loading)` → `<p>Loading...</p>`; `if (error)` → `<p>Something went
  wrong: {error}</p>`; otherwise the shadcn `Table` with one `TableRow`
  per forecast entry, columns `target_time` (formatted) and
  `temperature_c`.
- Timestamp formatting: `new Date(entry.target_time).toLocaleString("nl-BE")`
  inline in the JSX — no helper module, since it's a one-line call used
  in exactly one (View 1) or two (View 1 + View 2) places, per spec 03's
  "no external date library" and CLAUDE.md's matching convention.

**View 2 (stretch, built only after View 1 is verified working):**
- Add `selectedHour: ForecastEntry | null` and `history: HistoryEntry[]`
  state.
- Each `TableRow` gets an `onClick` setting `selectedHour` to that row's
  entry, then a `useEffect` on `selectedHour` calls
  `getForecastHistory(selectedCity, selectedHour.target_time)`.
- Panel: a plain conditional block (`{selectedHour && (...)}`)  rendered
  below the main table — a second small `Table` (`ingested_at` formatted
  + `temperature_c`) with a "Close" button that sets `selectedHour` back
  to `null`. No shadcn `Dialog` — not in the approved component list, and
  a plain inline panel satisfies "small panel/modal" without adding a
  third shadcn component beyond what CLAUDE.md pre-approved.

## Verification

1. Confirm backend is running (`cd backend && .venv/bin/uvicorn main:app --reload`),
   real ingested data present (already true from prior verification).
2. `cd frontend && npm run dev` (default port 3000).
3. Open `http://localhost:3000`: city select populated with Ghent/Antwerp/Temse,
   table shows the default-selected city's latest forecast (168 rows), timestamps
   in `nl-BE` locale format.
4. Switch city via the select → table updates to that city's data, sourced
   from a real network call (verify via browser devtools Network tab, not
   mocked).
5. Kill the backend, reload the page → error message shown, no crash.
6. Restart backend, reselect a city → recovers, no stale error state.
7. If View 2 is built: click a row → panel appears showing that hour's
   revision history (2 entries, from the 2 real ingestion runs), ordered
   by `ingested_at`; Close button dismisses it.
8. `npm run build` — confirm the production build succeeds with no
   TypeScript errors.
