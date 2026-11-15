# BioOrbit connected crew console

React + Vite + Three.js crew health console backed by Django's operational measurements. Dashboard reads do not require login; recording crew check-ins requires an authorized Django session. The simulator ingestion secret is never used by the browser.

For a local backend, start/rebuild services from the project root:

```bash
docker compose up --build
```

In another terminal, start the frontend against that local backend:

```bash
cd frontend
npm install
BIOORBIT_BACKEND_URL=http://127.0.0.1:8000 npm run dev
```

If Vite was already running before the integration, stop it with Ctrl+C and restart it so `vite.config.js` loads. Its `/api` proxy forwards requests to `https://requests-curriculum-organisation-ace.trycloudflare.com`, keeping browser requests same-origin for sessions and CSRF. This applies to both development and preview. Restart Vite after changing the target. To override the backend (for example, to use a local server):

```bash
BIOORBIT_BACKEND_URL=http://127.0.0.1:8080 npm run dev
```

`BIOORBIT_BACKEND_URL` is a Vite server setting, not a browser secret. Never put `SIM_INGEST_TOKEN` in frontend code or `VITE_*` variables.

## Connected views

- `GET /api/v1/dashboard` refreshes every five seconds. The roster, actual participant count, activity, locations, latest readings, source timestamps, preflight baselines, heart-rate mini charts, habitat values, mission day, and simulated clock come from the selected database run.
- `GET /api/v1/trends` supplies recorded 24-hour, seven-day, or thirty-day charts, refreshed every fifteen seconds. These query the PostgreSQL event journal, the sole application history store.
- Select an explicit run or use the newest available run automatically. Habitat selection and selected-crew habitat changes scope the shared cabin view.
- The twelve-region interactive 3D suit model, hover cards, floating cabin points, and crew comparison use the connected measurements. Changing astronauts resets orientation; rotating the person does not rotate cabin markers.
- White/gray light mode and navy dark mode remain available. Only the theme preference persists in local storage.

No fixed four-person mock roster remains. Default simulation settings create three astronauts, but the interface displays however many participants have been ingested. If astronaut names are not populated in Django, their actual astronaut codes are displayed instead of invented names/roles.

## Honest data states

No placeholder readings, fabricated historical points, fixed medical incidents, fake deck locations, or numerical forecasts are substituted when data is missing. Unknown values display `—`; empty history stays empty. On connection loss the last snapshot can remain visible alongside an explicit connection-error message. Requests time out and retry; changing run/person cancels obsolete requests.

Freshness is assessed relative to the run's latest simulated observation time, so accelerated/future-dated simulations are not compared incorrectly with wall-clock time. Overdue data is a collection status, not a clinical alert. Clinical alert rules are connected; forecasts remain unimplemented.

Authenticated crew check-ins persist in the backend and feed alert evaluation. Manual measurements enter the recorded journal; symptoms and notes retain author and mission time. Offline/PWA caching is not implemented.

## Validation

```bash
npm test
npm run build
```

The Node tests check real-value mapping, zero/boolean handling, missing data, partial blood pressure, query encoding, and error propagation. Production build/preview:

```bash
npm run build
npm run preview
```

Preview uses the same API proxy. A build verifies bundling; it does not verify that the configured backend is reachable or that deployed sessions, CSRF and database migrations are configured correctly.

The Alerts navigation item displays persisted workbook alerts, evidence, guidance, recheck times and acknowledgment. Crew cards, body regions and cabin pins reflect the highest applicable severity. Missing inputs and collection tasks are shown separately. This is a workbook-based prototype. Check-in notes are stored with the report, but free-text notes alone do not supply clinical rule inputs.

Crew check-ins now save to the backend and feed the rule engine. The form accepts
manual core indicators, consciousness, oxygen treatment, headache, red flags and
ECG findings. Blank fields remain unknown. Sign in with a Django account granted
`core.add_crewcheckin` (or a superuser); the form prompts for login when needed.
The Crew check-ins view reloads saved reports after refresh. Backend migration
`0006_crewcheckin` must be applied before using this feature. Findings are stored
in simulated mission time; reports remain in history after their alert-input
freshness expires.

## Recorded decisions and history

Alert details show recorded findings, the workbook condition for the displayed tier,
mission observation/recheck times and readable guidance. Raw evidence and provenance
remain available in an expandable panel. Reference conditions do not replace the
engine's recorded evaluation, including held alert tiers.

History charts include UTC axes, focusable/tappable aggregate values displayed to two decimal places, expandable
value tables, personal preflight reference bands where available, and separate systolic
and diastolic blood-pressure series. Missing hourly/daily buckets break the lines.
Habitat and cabin-zone selectors scope readings, history and displayed crew locations.

API connectivity is separate from telemetry receipt age. The dashboard supplies
`run.telemetry_received_at`, excluding manual crew check-ins. A feed with no receipt
for over 30 wall-clock seconds is labeled inactive; this is independent of mission-time
measurement freshness. The receipt clock continues updating during a connection loss.

The Three.js body view loads on demand and pauses its animation loop while the page
is hidden. Run `npm test` for mapping, presentation and recorded-history regressions.

Habitat metric cards use the same interactive history panels as crew indicators:
24-hour, seven-day and thirty-day windows, UTC axes, aggregate inspection to two decimal places,
recorded-value tables and gaps for missing buckets. Each panel queries the selected
run, habitat and cabin zone. Personal preflight reference labels apply only to crew
charts; habitat charts show recorded environmental measurements.

Sleep history uses daily observations with seven-day or thirty-day views. Axes,
point inspection and value tables label each UTC calendar day relative to the
mission's first observation (Day 1), alongside its date. Sleep duration stays in
hours on the value axis. Missing days remain gaps.

## Landing page and dashboard

The frontend opens to an astronaut-focused project introduction at `/`. Its “Visit dashboard”
links open the existing console at `/dashboard`; the console wordmark returns
home. The dashboard code and API polling load only when the console is opened.
Both pages share the saved light/dark theme preference and orbit favicon.

The landing page describes the long-duration mission challenge and how astronauts
can review health indicators, personal references, cabin observations, alerts and
check-ins. It uses factual project language and links to NASA’s Human Research
Program, spaceflight hazards and evidence reports. Its
interactive vector illustration is a conceptual diagram, not measured data.
The page identifies the simulator data and the project’s independent status.

Vite development and preview serve both routes. When deploying the production
build behind another web server, configure SPA fallback to `index.html` for
`/dashboard`, `/documentation`, `/resources` and `/about`, while forwarding
`/api/` requests to the intended Django backend. Vite proxy settings do not get
embedded in static build files; the production host must supply its own API proxy.

## Measurements beside the 3D astronaut

The scrollable Crew measurements panel below the 3D astronaut displays all cards
under Body, Mind, Sleep and Habitat section headings. The category tab bar has
been removed. Habitat measurements, including drinking water availability, appear
near the bottom of this panel and are scoped to the crew member’s habitat.
The 3D region buttons remain separate; visible regions depend on core readings
and active alerts, rather than every configured region always being selectable.

All 88 current wire metrics have an explicit category in
`src/measurementCatalogue.json`. Values retain their backend units, timestamps,
missing/overdue states and alert links. Categories support numeric, boolean,
categorical and structured readings; independent random fixtures are labelled.

## Biology documentation and reference library

- `/documentation` explains the biology behind circulation, breathing, sleep,
  metabolism, bone/muscle changes, urinary health, immunity, sensory systems,
  cabin exposures, radiation and EVA, with source links and interpretation limits.
- Its searchable measurement atlas covers 87 measurement types (the serum iron/ferritin documentation entry is omitted),
  preserving the prototype’s declared units and distinguishing measurement types
  from actual collected observations. A glossary explains key abbreviations.
- `/resources` contains 139 references, across seven categories, including the added serum iron clinical reference
  (`ref-140`). REF 003 remains removed; retained IDs are not renumbered. Search works across titles, authors, dates and study IDs;
  category filters combine with search. Full citations remain expandable.
- `/downloads/References.docx` serves the updated bibliography, with REF 003
  removed and the serum iron reference added. One retained entry has no supplied
  URL and is explicitly marked. Sources are background references, not datasets
  connected to the console.

Both pages share the landing page navigation, mobile layout and saved theme.
Cross-references open the relevant library entry using a stable reference anchor.

### Check-ins when opening the dashboard over the local network

When the browser uses a LAN address rather than localhost, append that exact
frontend origin (including `http://` or `https://` and its port) to
`DJANGO_CSRF_TRUSTED_ORIGINS` in the root `.env`. Preserve the existing entries.
Apply the change with `docker compose up -d --no-deps backend`; a frontend
refresh alone cannot update Django’s origin configuration. Session login and a
valid CSRF token are still required to save a check-in.


## About and display conventions

`/about` introduces Farouk El Ouassif (Data & Software Engineer) and
Dr. Abdenacer Benchrifa (Biomedical Researcher). It includes their supplied bios,
email links, LinkedIn profiles and Abdenacer’s research profiles. No GitHub profile
was supplied. About us is linked from the public header and footer.

Numeric measurements, chart values, personal references and structured alert
scores display exactly two decimal places. Stored readings and scoring retain
full precision. Counts, dates and identifiers retain their usual formats. The raw
evidence panel preserves the original evidence for inspection.

NEWS2 alert details explain that component scores are not measured vital signs:
0.00 means no points contributed by an available reading, not 0 bpm or 0% SpO2.
Missing inputs remain unknown. When a prior higher alert tier is retained, the UI
labels that retained tier separately from the latest calculated tier. Three
qualifying later normal observations lower one tier; an observation that still
triggers a lower alert is not normal and resets the recovery counter.
