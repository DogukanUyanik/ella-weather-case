# Spec 03 — Frontend UI

## Goal

A minimal Next.js dashboard: pick a city, see its current forecast.
No custom visual design — this case rewards a correct, working core
over polish, so styling stays at shadcn/ui defaults.

## Views

### View 1: City picker + forecast (core, must-have)

- What it shows: a dropdown/list of the 3 cities (Ghent, Antwerp,
  Temse). Selecting one shows that city's latest forecast as a simple
  table/list — one row per upcoming hour, with `target_time` and
  `temperature_c`.
- API calls: `GET /cities` on page load (populate the picker),
  `GET /forecasts/{city}/latest` when a city is selected.
- Interactions: just the city selection. No filtering, sorting, or
  editing.

### View 2: Forecast history (stretch — only if time allows)

- What it shows: clicking one row (one target hour) in View 1 opens a
  small panel/modal showing how that hour's forecast changed across
  ingestion runs — a simple table or line chart of `ingested_at` vs
  `temperature_c`.
- API calls: `GET /forecasts/{city}/history?target_time=...`.
- Interactions: click a row to open, close to dismiss. Nothing more.
- Explicitly optional: if this isn't built, the app is still complete
  per PROJECT_SPEC.md — the API endpoint exists and is tested
  regardless of whether this view ships.

## Data fetching

A single API client module (e.g. `lib/api.ts`) wraps `fetch` calls to
the three endpoints (`getCities`, `getLatestForecast(city)`,
`getForecastHistory(city, targetTime)`) and returns typed data. Page/
component code calls these functions rather than calling `fetch`
directly — same "service file" separation used in the earlier college
projects, just applied here too.

The API base URL comes from an environment variable
(`NEXT_PUBLIC_API_URL`), defaulting to `http://localhost:8000`.
Because data-fetching happens client-side (`useState`/`useEffect` runs
in the user's browser, not inside the Docker network), the browser can
only reach the backend via the mapped host port — `localhost:8000` —
both in local development and when running via docker-compose, as
long as port 8000 is published to the host. A Docker-internal service
name like `http://backend:8000` would only work for server-side
fetches (e.g. Next.js Server Components), which this app doesn't use.

Format ISO timestamps using native JavaScript
(`new Date(iso).toLocaleString('nl-BE')`) — no external date library
(no `date-fns`, no `moment`) needed for this scope.

No client-side state management library — `useState`/`useEffect` (or
equivalent data-fetching hook) is enough at this scale.

## Styling

`shadcn/ui` initialized with defaults, no custom theme or design pass.
Only `table` and `select` components are installed
(`npx shadcn@latest add table select`) — no reason to pull in more
than what these two views actually need. Deliberate choice: time
budget goes to the data model and API correctness, not visual polish —
consistent with the case's own framing ("we care more about your
judgment and reasoning than about polish").

## Out of scope for this part

- Loading skeletons / spinners beyond a basic "Loading..." state
- Error boundaries beyond a basic "Something went wrong" message
- Responsive design / mobile layout
- Animations/transitions
- Client-side caching of API responses

## Acceptance criteria

- [ ] Selecting a city shows its latest forecast, sourced from the
      real API (not mocked data)
- [ ] Switching cities updates the shown forecast correctly
- [ ] The frontend works unchanged both against a local dev backend
      and against the `backend` service inside docker-compose (proves
      the `NEXT_PUBLIC_API_URL` approach works)
- [ ] (If built) clicking a target hour shows its revision history