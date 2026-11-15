# BioOrbit connected crew console

React + Vite + Three.js frontend for Django's operational measurement data. No login flow or ingestion secret is used by the browser.

From the project root, start/rebuild backend services yourself:

```bash
docker compose up --build
```

In another terminal, start the frontend yourself:

```bash
cd frontend
npm install
npm run dev
```

If Vite was already running before the integration, stop it with Ctrl+C and restart it so `vite.config.js` loads. Its `/api` proxy forwards requests to `http://127.0.0.1:8000`, keeping browser requests same-origin. For a different backend host port:

```bash
BIOORBIT_BACKEND_URL=http://127.0.0.1:8080 npm run dev
```

`BIOORBIT_BACKEND_URL` is a Vite server setting, not a browser secret. Never put `SIM_INGEST_TOKEN` in frontend code or `VITE_*` variables.

## Connected views

- `GET /api/v1/dashboard` refreshes every five seconds. The roster, actual participant count, activity, locations, latest readings, source timestamps, preflight baselines, heart-rate mini charts, habitat values, mission day, and simulated clock come from the selected database run.
- `GET /api/v1/trends` supplies recorded 24-hour, seven-day, or thirty-day charts, refreshed every fifteen seconds. These currently query PostgreSQL journal history; Gold/DuckDB analytics are not yet integrated.
- Select an explicit run or use the newest available run automatically. Habitat selection and selected-crew habitat changes scope the shared cabin view.
- The twelve-region interactive 3D suit model, hover cards, floating cabin points, and crew comparison use the connected measurements. Changing astronauts resets orientation; rotating the person does not rotate cabin markers.
- White/gray light mode and navy dark mode remain available. Only the theme preference persists in local storage.

No fixed four-person mock roster remains. Default simulation settings create three astronauts, but the interface displays however many participants have been ingested. If astronaut names are not populated in Django, their actual astronaut codes are displayed instead of invented names/roles.

## Honest data states

No placeholder readings, fabricated historical points, fixed medical incidents, fake deck locations, or numerical forecasts are substituted when data is missing. Unknown values display `—`; empty history stays empty. On connection loss the last snapshot can remain visible alongside an explicit connection-error message. Requests time out and retry; changing run/person cancels obsolete requests.

Freshness is assessed relative to the run's latest simulated observation time, so accelerated/future-dated simulations are not compared incorrectly with wall-clock time. Overdue data is a collection status, not a clinical alert. Clinical alert rules and forecasts are not connected yet.

Session check-in notes are still local to the current browser tab, explicitly labeled, and clear on refresh. They do not overwrite backend telemetry. A persistent check-in API is future work. Offline/PWA caching is not implemented.

## Validation

```bash
node src/data.test.js
npm run build
```

The Node tests check real-value mapping, zero/boolean handling, missing data, partial blood pressure, query encoding, and error propagation. Production build/preview:

```bash
npm run build
npm run preview
```

Preview uses the same API proxy. Browser interaction and real PostgreSQL round-trip verification must be performed against the services you run; no Docker containers or dev server were started by the assistant.

The Alerts navigation item displays persisted workbook alerts, evidence, guidance, recheck times and acknowledgment. Crew cards, body regions and cabin pins reflect the highest applicable severity. Missing inputs and collection tasks are shown separately. This is a workbook-based prototype; session notes remain local and do not supply clinical rule inputs.
