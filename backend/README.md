# Local backend + PostgreSQL

From the repository root, run:

```bash
docker compose up --build
```

Compose reads the root `.env` for configuration. A generated `.env` is provided locally and ignored by Git and Docker builds. `.env.example` documents the required variables without real credentials. For a fresh checkout, copy the example to `.env` and replace its secret placeholders before starting.

Services:

- `db`: PostgreSQL 17, persistent `postgres_data` volume, internal port 5432. No host database port is published.
- `backend`: built from the root Dockerfile, runs migrations after PostgreSQL is healthy, then starts Django's foreground development server at http://localhost:8000. The Django admin route is http://localhost:8000/admin/; the machine-to-machine ingestion route is `/api/v1/ingest/events`.

The backend is a development service, not a production deployment. Source code is copied into the image: rebuild after backend changes. `POSTGRES_HOST=db` is the Compose service name. Django receives variables from Compose; it does not load `.env` automatically outside Docker.

Validation commands to run yourself:

```bash
docker compose config --quiet
docker compose exec backend python manage.py check
docker compose exec backend python manage.py showmigrations
```

`docker compose down` stops the services and preserves the database volume. Changing PostgreSQL credentials in `.env` does not update an already-initialized database; coordinate credential changes with the existing database rather than deleting its volume.

The same Compose command also starts `simulator`, which has a separate persistent `simulator_data` volume. It initializes preflight data once, backfills to day 30, and resumes live generation. HTTP delivery is configured through `SIM_INGEST_URL` and a shared `SIM_INGEST_TOKEN` in `.env`; synthetic records also remain in the simulator journal. See [the simulator Compose guide](../simulator/README.md#run-with-docker-compose) for configuration and control commands.

## Operational Django models

`core` is registered in `INSTALLED_APPS`; `core/migrations/0001_initial.py` creates the supplied operational schema. Build/start the backend to apply it through the existing startup migration step:

```bash
docker compose up --build backend
```

Model/table mapping:

| Django model | Database table |
|---|---|
| `Mission` | `missions` |
| `Habitat` | `habitats` |
| `Astronaut` | `astronauts` |
| `MissionCrew` | `mission_crew` |
| `SimulationRun` | `simulation_runs` |
| `MetricCatalog` | `metric_catalog` |
| `MeasurementEvent` | `measurement_events` |
| `PreflightProfile` | `preflight_profiles` |
| `PreflightBaseline` | `preflight_baselines` |
| `LatestMeasurement` | `latest_measurements` |

The models preserve the supplied column lengths, nullable columns, database defaults, UUID/string identifiers, enum CHECK constraints, value/subject checks, and named partial indexes. Generated numeric IDs use Django's PostgreSQL bigint identity implementation of `BigAutoField`. JSON fields use PostgreSQL JSONB. All FK deletions use ORM `PROTECT`; the database also enforces referential integrity. Django may create its normal additional foreign-key indexes.

`MissionCrew.pk` is `(mission_id, astronaut_id)` and `PreflightBaseline.pk` is `(profile_id, metric_id)`, backed by genuine composite primary keys. No surrogate ID was added. Django's composite-primary-key admin/relational limitations still apply; neither composite-key model is registered in admin or used as a foreign-key target. See [Django's composite-key documentation](https://docs.djangoproject.com/en/6.1/topics/composite-primary-key/).

Foreign keys have conventional Django names: `run`, `metric`, and `source_event`; their database columns remain `run_id`, `metric_code`, and `source_event_id`. For example, `MeasurementEvent(run_id='demo-001', metric_id='heart_rate', ...)` supplies their referenced identifiers, while `event.metric` resolves the catalogue model.

Defaults exist both in Python and at database level. The nullable defaulted fields from the supplied SQL remain nullable. `LatestMeasurement.updated_at` defaults on insert; it is **not** an automatic update trigger. The future ingestion/upsert path must explicitly advance it. Preflight background rate (mSv/year) and pre-mission career dose (mSv) remain separate fields.

The ingestion service provisions consistent mission/habitat/crew references and metric definitions, validates run ownership and metric domain/type, journals events, and projects profiles/latest readings atomically. Direct ORM or SQL writes can still violate cross-row semantic relationships not expressed by the supplied foreign keys. PostgreSQL retains the complete raw journal and serves both current readings and historical trends; workbook alert evaluation runs during ingestion.

Offline checks from the repository root (no database access):

```bash
.venv/bin/python backend/check_models.py
```

Database checks/tests to run yourself after rebuilding the backend:

```bash
docker compose exec backend python manage.py check
docker compose exec backend python manage.py showmigrations core
docker compose exec backend python manage.py test core
```

The last command creates an isolated Django test database on PostgreSQL. It checks numeric/boolean exclusivity (including boolean `false`), valid subjects/profile shapes, event idempotency keys, composite-key uniqueness, per-mission habitat uniqueness, baseline sample counts, partial latest-value uniqueness, catalogue enums, and protected deletion. PostgreSQL execution has not been performed by the assistant.


## Simulator ingestion API

`POST /api/v1/ingest/events` (also accepts a trailing slash) receives either one schema-1.0 simulator event or `{"schema_version":"1.0","events":[...]}`. The wire format and units match [the simulator contract](../simulator/README.md#measurement-contract-and-catalogue). Maximum: 1,000 events and 4 MiB per request. Identifiers are at most 100 characters, source at most 200. Only synthetic v1.0 data is supported.

Headers:

```text
Content-Type: application/json
Authorization: Bearer <SIM_INGEST_TOKEN from .env>
```

The root `.env` now contains a shared generated token and `SIM_INGEST_URL=http://backend:8000/api/v1/ingest/events`. Compose passes the same token to Django and the simulator. Fresh checkouts should replace the token placeholder in `.env.example` when creating `.env`. This token is for service-to-service ingestion, independent of any crew login. Missing server configuration fails closed with 503. Keep the token out of logs and source control.

Run these yourself to deploy the code, apply any pending schema migration through backend startup, and recreate the simulator with its endpoint/token settings:

```bash
docker compose up --build
docker compose exec backend python manage.py test core
docker compose logs -f simulator
```

A successful request returns HTTP 200 **after committing**:

```json
{"accepted_event_ids":["event-uuid-1","event-uuid-2"],"created_count":2,"duplicate_count":0}
```

Behavior:

- The whole batch is validated before database writes. Every new event is stored in `measurement_events` with the original v1 payload in `raw_payload` (UUID spelling canonicalized), context and timestamps intact. PostgreSQL is the sole application event store.
- Source `mission_id`, `habitat_id`, and `astronaut_id` are external **codes**, resolved to internal rows. Missing missions, habitats, astronauts, runs, crew assignments, and catalogue entries are created as needed. Names remain unspecified because the simulator contract supplies codes, not personal names. The first observed habitat becomes the crew assignment; event habitat/zone tracks later locations.
- The same `run_id` cannot belong to another mission. Existing catalogue definitions cannot silently change unit, domain, value type, or aggregation meaning. Run metadata reflects the newest observed environment; late backfill does not overwrite it.
- Duplicate event IDs with identical payloads, or payloads differing only in documented equivalent metric identifiers/units, are acknowledged without a second write or projection. Conflicting payloads return 409 and roll back the **entire batch**, including newly provisioned metadata. `emitted_at` is part of the payload: resend from the original journal, rather than regenerating the same run ID with different emission timestamps.
- Preflight profiles create `preflight_profiles` and the twelve required `preflight_baselines`, plus an optional stress baseline. Profiles are immutable per run/astronaut; resend the original event ID to retry. Ordinary preflight observations stay in the journal and never overwrite live measurements.
- In-flight measurements update `latest_measurements` by run/astronaut/metric or run/habitat/zone/metric. Late records are still journaled but cannot regress latest state. Equal timestamps use the greater UUID integer as a deterministic tie break. Updated rows explicitly refresh `updated_at`. Boolean `false` is preserved separately from numeric values.
- Run-row locks serialize concurrent projections for the same run; journal, profiles, latest rows, and references commit in one transaction. Successful acknowledgments include existing duplicates. The request-level `Idempotency-Key` header is optional; **event IDs** are the durable deduplication keys.

Errors: 400 malformed JSON (including NaN/Infinity and duplicate object keys), 401 missing/wrong bearer token, 405 wrong method, 409 identity/profile/catalogue conflict, 413 excessive body size, 415 wrong content type, 422 contract validation failure, 503 unavailable database/configuration. Validation errors include the zero-based `event_index` when applicable. 503 responses from database failures include `Retry-After: 2`. Failed batches are not acknowledged.

On startup the container backfills locally first, then sends its existing pending journal in bounded batches alongside live generation. A large historical backlog takes time to catch up; do not delete simulator state to force another send. Both HTTP delivery receipts and PostgreSQL event IDs make restarts safe to retry.

Verification performed here: offline model/migration checks and validation/request tests. PostgreSQL transaction/constraint tests are included in `core.test_ingestion.IngestionDatabaseTests` but must be executed with the Docker command above; Docker and live database migrations were not run by the assistant.


## Workbook metric identifier compatibility

The ingestion endpoint accepts `Data.xlsx` identifiers for measurements already supported by the project. It normalizes them to the existing database catalogue codes **before validation and projection**, while preserving the source identifier/unit in `measurement_events.raw_payload`. Existing simulator event codes and persisted records do not need migration. The simulator JSON Schema continues to describe its canonical emitted format; the following aliases are an additional backend input compatibility layer.

| Workbook identifier | Canonical database identifier |
|---|---|
| `bp_systolic` | `systolic_blood_pressure` |
| `bp_diastolic` | `diastolic_blood_pressure` |
| `resp_rate` | `respiratory_rate` |
| `core_temp` | `body_temperature` |
| `glucose` | `blood_glucose` |
| `sleep_hours` | `sleep_duration` |
| `stress` | `stress_level` |
| `cabin_co2` | `co2_partial_pressure` |
| `cabin_o2` | `o2_partial_pressure` |
| `cabin_pressure` | `total_cabin_pressure` |
| `cabin_temp` | `cabin_temperature` |
| `cabin_humidity` | `relative_humidity` |
| `noise` | `noise_level` |
| `dust` | `dust_concentration` |
| `rad_cumulative` | `total_career_radiation_dose` |
| `rad_rate` with `domain=astronaut` | `personal_radiation_dose_rate` |
| `rad_rate` with `domain=cabin` | `radiation_level` |

`rad_cumulative` maps to **total career dose**, since the workbook compares it against a career exposure budget. A source that means dose accumulated only during the current mission must send `mission_cumulative_radiation_dose` explicitly. Identity mappings such as `heart_rate`, `spo2`, `mood`, `fluid_intake`, and `body_mass` remain accepted as before.

Equivalent unit labels are normalized without numeric scaling: heart rate `beats/min` → `bpm`, sleep `h/night` → `hours`, and mood/stress `0–10 slider` → `0–10`. Other units must match the canonical catalogue. This does **not** convert `L/day` to a six-hour `L` total, or oxygen percent to partial pressure. The workbook's `solar_storm` (S-level/projected dose) is not an alias for `is_solar_storm` (boolean); those have different meanings.

The same aliases also work in a profile's `baseline_statistics` keys. Supplying two keys for the same canonical metric in one profile is rejected instead of silently discarding one. Duplicate-event comparisons normalize aliases/units on both sides, so a previously accepted event can be resent in either equivalent spelling with the same UUID. Changing a value or other payload content still returns 409.

Example: keep the normal event envelope and send `"metric":"bp_systolic","value":112,"unit":"mmHg"`. The journal retains `bp_systolic` in its raw payload; its `metric_code`, latest measurement, and any corresponding baseline use `systolic_blood_pressure`.


## Connected frontend read APIs

The shared local crew console now uses two **GET-only** endpoints. They do not require the ingestion bearer token and do not modify state. The backend is still published only on localhost by Compose; Vite forwards browser `/api` requests to it through its development/preview proxy. Read views remain shared; authenticated crew check-ins use the session flow documented below. Apply network access controls before exposing crew health data outside the intended local environment.

### `GET /api/v1/dashboard`

Optional query parameters: `run_id`, `habitat_id`, `zone_id`. Without a run ID, the newest active run is selected, falling back to the newest available run. Invalid explicit run/habitat/zone selections return 404. An empty database returns 200 with `run: null`, `crew: []`, and no fabricated measurements.

The response includes:

- Available recent runs, selected mission/run/environment, earliest in-flight observation, latest simulated observation time, and mission day derived from that range.
- Actual run participants and their names/codes. It does not combine participants from unrelated historical runs.
- Latest astronaut readings and habitat/zone-scoped cabin readings, including canonical metric, numeric/boolean value, unit, source event ID, measured/emitted/received timestamps, source, simulation flag, and context/activity.
- Personal preflight baseline means, standard deviations, minima, maxima, and sample counts.
- Up to 24 recent real heart-rate observations per astronaut for roster mini charts.
- A freshness indicator (`current`/`overdue`) based on elapsed **simulated time** relative to the newest observation. Collection thresholds use workbook cadences, with a 15-minute continuous-stream gap tolerance. They are not clinical alert classifications and do not yet adapt to arbitrary custom historical sampling intervals.
- `alerts_available: true`, with persisted workbook alerts, rule coverage and separate collection tasks.

### `GET /api/v1/trends`

Required: `metric` plus `astronaut_id` for astronaut measurements or `habitat_id` for cabin measurements. Also accepts `run_id`, `domain` (`astronaut` by default, or `cabin`), `zone_id`, and `window` (`24h`, `7d`, `30d`). Workbook metric aliases are accepted. Unknown subjects return 404; invalid metric/domain/window combinations return 422.

Charts use **in-flight PostgreSQL measurement history** anchored to the selected run's latest observation time. They do not invent missing days or include preflight observations as flight trends. The 24-hour view groups by UTC hour; longer windows group by UTC day. Point metrics use the mean, cumulative metrics use the maximum, and interval-total metrics use the sum of recorded window totals. Each bucket contains timestamp, value, and source sample count. Boolean metrics remain available in the dashboard but have no numeric trend endpoint.

Historical trends are served directly from the PostgreSQL event journal. Both endpoints set `Cache-Control: no-store`; database failures return 503 rather than synthetic fallback data. The frontend polls dashboard data every five seconds and charts every fifteen seconds.

Run these yourself after rebuilding:

```bash
docker compose up --build
docker compose exec backend python manage.py test core
```

The read integration adds no models or migrations. `core.test_reads.ReadDatabaseTests` covers ingested values reaching dashboard/trend responses, per-run isolation, preflight references, boolean false, real aggregation, empty states, and invalid selections. Offline request/serialization tests are included in `backend/check_models.py`; PostgreSQL tests still require your running Docker setup.

## Workbook alert mechanism

Ingestion now evaluates alert rules inside the same database transaction, after updating the journal and latest values. No additional worker is needed. Migration `0003_workbook_alerts` adds `monitoring_alerts` (persistent lifecycle/evidence/acknowledgment) and `alert_assessments` (coverage and missing inputs). Run locks serialize ingestion and one-pass evaluation. Duplicate-only ingestion does not advance recovery counters. Late records cannot move the alert observation timestamp backward.

`core/alerts/workbook.json` preserves the 83 parameter rows, patterns, tiers, row references and source-file SHA256 from `Data.xlsx`. This is a specification, not 83 collected measurements. `engine.py` implements explicit numerical rules and windowed combinations for available telemetry. Specialist rules with ambiguous prose require explicit reviewed source flags. Absent clinical inputs do not become normal observations or zero NEWS2 components.

Supported telemetry rules include activity-aware vital components (HR 5-minute persistence; SpO2 2-minute persistence), all-meal low glucose and fasting reference checks, personal baseline deviations, multi-day sleep/mood/stress/fluid summaries, cumulative career radiation, 24-hour mean dose rate, cabin O2/CO2/pressure/temperature/humidity, and qualified noise/dust observations. High resting heart rate is not inferred from exercise readings. Full NEWS2 requires all five numerical components, consciousness and supplemental oxygen with a coherent spot-check; a partial lower bound can escalate at 5/7 while missing components remain unknown. Simulator `is_solar_storm=true` alone does not establish a NOAA severity or projected event dose.

Windowed means require complete coverage with gaps no greater than 15 minutes; HR/SpO2 persistence tolerates gaps up to 60 seconds. Sparse backfill can therefore leave persistence rules pending. Fluid totals require complete days with known intervals; simulator six-hour summaries are recognized by source and window tag. Noise requires an explicit work/sleep period; surface dust requires `context.surface_body` (`moon` or `mars`). Low humidity uses an explicitly documented one-hour mean because the workbook does not specify its averaging duration. In-flight reference bands require at least 20 valid resting observations spanning a day, using the prior seven days excluding the latest day, with median-deviation trimming. NEWS2 integer bands round readings; raw observations remain unchanged.

Four tiers are Advisory (blue), Caution (amber), Warning (orange), Emergency (red). Escalation is immediate once persistence/window requirements are met. Three distinct later normal observations lower severity by one tier; another three are required for another step. Missing, stale, or pending data never clear an alert. Advisory rechecks use four simulated hours, habit rules 24 hours, Caution/Warning one hour, symptomatic glucose 15 minutes, Emergency continuous monitoring. Workbook actions and recipients are reference metadata: no notifications or treatments are dispatched. Acknowledgment records review and does not resolve an alert. The current no-login console stores acknowledgment time, not an authenticated reviewer identity.

API:

- `GET /api/v1/alerts?run_id=...`: active alerts with tier, evidence, guidance, provenance, observation/recheck times and acknowledgment.
- `GET /api/v1/alert-rules`: workbook specification and explicit prototype assumptions.
- `GET /api/v1/dashboard`: includes alerts, per-subject assessments and separate collection tasks.
- `POST /api/v1/alerts/{id}/acknowledge`, JSON `{"tier":"caution"}`: requires the current tier; returns 409 if severity changed or the alert resolved. Uses Django CSRF cookie/header protection. Dashboard GET initializes the CSRF cookie. Configure `DJANGO_CSRF_TRUSTED_ORIGINS` for custom frontend origins; localhost Vite/preview ports are included by default.

Optional clinical facts can accompany an otherwise valid measurement, without changing its metric or raw observation:

```json
{"context":{"activity":"resting","rule_inputs":{
  "consciousness":{"value":"alert"},
  "supplemental_oxygen":{"value":false},
  "noaa_s_level":{"value":1,"unit":"S-level"},
  "projected_event_dose_msv":{"value":220,"unit":"mSv"},
  "reaction_slower_two_tests":{"value":true}
}}}
```

Supplemental numeric facts require exact workbook units, enumerations and booleans are type checked, and optional UTC `observed_at` cannot exceed the containing measurement's time. Canonical measurements cannot be overridden through supplemental facts. Invalid supplemental facts are ignored and remain unevaluated. Session notes in React do not supply these inputs.

To apply the migration using the existing backend startup:

```bash
docker compose up --build
```

To evaluate already-stored latest data once, without waiting for another ingestion:

```bash
docker compose exec backend python manage.py evaluate_alerts
# Optionally append: --run-id YOUR_RUN_ID
```

Evaluation concerns the current stored state and supporting history; it is not a chronological replay of every historical alert transition. Observation and recheck clocks use simulated mission time, acknowledgment uses real UTC time. If ingestion stops, the UI reports loss of contact and retains the latest state; there is no independent watchdog generating alerts while Django receives no data.

Focused checks:

```bash
.venv/bin/python backend/check_models.py
# Database-backed ingestion/acknowledgment/recovery test:
docker compose exec backend python manage.py test core.test_alerts
```

## PDF coverage completion and upgrade (15 November)

Apply migrations through `0004_latest_rule_inputs`. Independent supplementary
observations now project into `latest_rule_inputs`; later measurements omitting
an observation do not erase it. Original observation time, source event, validity,
and deterministic timestamp/UUID ordering are preserved. Stale, invalid and
unknown observations cannot clear an alert. The projection commits with ingestion.

Rebuild/restart the backend and simulator images to use the new source. After
migration, rebuild historical supplementary projections without editing the journal:

```bash
docker compose exec backend python manage.py evaluate_alerts --rebuild-inputs
```

Add `--run-id <id>` for one run. This reconstructs current supplementary facts;
it does not replay all historical alert transitions. New profiles may optionally
include `stress_level`; existing twelve-field profiles remain valid. Old immutable
profiles are not enriched with invented stress references.

Patterns now emit explicit normal results using three-valued logic. Known false,
known true and unavailable inputs are distinct. Recovery uses later participating
observations, not repeated evaluations or unrelated measurements. Cabin patterns
aggregate occupants so a normal person cannot overwrite another person's trigger.
Acute symptom groups require explicit negative review for recovery. Three normal
observations lower one tier; another three are needed for the next step.

Noise windows require matching historical work/sleep tags. Sleep recovery requires
negative evidence for the three-night, seven-day and awake-time conditions; normal
awake time alone is insufficient. Symptomatic solar storms retain the workbook's
Warning path (`is_solar_storm` with nausea/vomiting), in addition to the PDF's
numerical NOAA/projected-dose paths. The original PDF omits that extra workbook path.

`core.test_pdf_scenarios` checks threshold boundaries, missing data, exposure tags,
all four recovery tiers, duplicate/late delivery, symptom retention and real
simulator-to-Django scenarios. Run `python manage.py test core` on PostgreSQL;
`backend/check_models.py` runs only the offline subset.

### Chronological alert evaluation within ingestion batches

New in-flight events are projected and evaluated in ascending observation time,
with all measurements and supplemental facts at the same timestamp published
before evaluation. A cabin O2 reading of 120 mmHg followed by 150 mmHg in one
batch therefore raises and retains the Emergency; the later reading cannot hide
it. Recovery counts each qualifying later observation, just as with separate
requests. The existing transaction and run locks cover every intermediate step,
so retries remain atomic and duplicate-only delivery does not advance recovery.

Already-stored newer observations are never rewound by late historical delivery.
Late-only batches reassess the current state using the added history; they do not
replay historical transitions. This change prevents missed transitions in new
batches; it does not reconstruct alerts already missed by earlier versions.
Large batches spanning many observation times now require more evaluations.

Regression coverage is in `core.test_alerts.BatchAlertIntegrationTests`, including
reversed wire order, Emergency retention, single/batch recovery equivalence,
supplemental flags, simultaneous inputs and late history.


## PostgreSQL-only storage upgrade

Compose runs three services: `db`, `backend`, and `simulator`. PostgreSQL stores
all accepted measurements and original raw payloads, as well as baselines, latest
readings and alerts. Historical charts query the same event journal.

Migration `0005_remove_bronze_export` removes obsolete export receipts and fields;
it does not delete measurement events or their original JSON. Earlier migrations
remain intact so existing databases can upgrade safely. The simulator's persistent
SQLite journal remains its generation/checkpoint/retry mechanism.

Rebuild/restart the backend to apply pending migrations automatically. Database
and simulator volumes remain intact. No filesystem export worker is required.

## Crew check-ins and remaining alert inputs

Migration `0006_crewcheckin` adds durable crew reports. Rebuild the backend using
`docker compose up -d --build backend` to apply pending migrations through its
existing startup command. The console requires a Django account with the
`core.add_crewcheckin` permission (superusers have it). Use existing admin accounts,
or create an account with `docker compose exec backend python manage.py createsuperuser`;
no password is embedded in the frontend or simulator.

- `GET /api/v1/session` establishes CSRF and reports login capability;
  `POST` signs in with username/password, and `DELETE` signs out.
- `GET /api/v1/check-ins?run_id=...` returns the last 100 reports to authorized users.
- `POST /api/v1/check-ins` requires the session, CSRF, a client UUID `id`, active
  `run_id`, participating `astronaut_id`, and an explicit `activity`. Optional
  `measurements` accepts heart rate, breathing rate, SpO2, systolic/diastolic BP,
  glucose, core temperature, sleep, and mood. Glucose requires `meal_context`.
  Optional `rule_inputs` accepts consciousness, supplemental oxygen, headache
  severity, red-flag symptoms and ECG alarm findings; values are scalar observations.
  Omitted findings remain unknown. `notes` alone do not trigger rules.

The backend uses the current mission clock, records the author, persists the report
and evaluates alerts in one transaction. Repeating the same UUID/body returns the
original result without new observations; reusing it with different contents is a
conflict. Actual manual measurements enter the existing journal and trend path.
Symptom-only reports never manufacture heart-rate or other sensor samples.
Crew findings override simulator fixtures for one mission hour; consciousness and
oxygen treatment still obey the scorer's five-minute freshness check. Repeated
polling does not count the same report as a new normal recovery observation.
Explicitly reviewed negative reports can replace earlier positives.

Diastolic drift now compares non-exertion measurements against an observed
in-flight reference (same prior-seven-day window, excluding the last day, ≥20
samples spanning ≥24h), with ±5 mmHg prototype tolerance. Missing reference data
remain unevaluated. Explicit reviewed drift flags remain supported.
An unplanned fall **>6.9 kPa within 10 mission minutes** now raises a pressure
Emergency; `context.planned_pressure_change: true` suppresses this inference,
while explicit pressure-loss flags still take precedence.

ECG inputs are supplied by normal simulator observations (negative fixtures),
scenarios, the `symptom ... ecg_alarm` control, and crew reports. An alarm raises
Caution; associated symptoms raise Warning; chest pain/collapse raises Emergency.
These adaptations are team prototype rules, not clinical validation or an external
sensor connection. This work does not establish complete collection of all 83
workbook indicators or tracking against a 250 mSv event limit.

## Expanded workbook measurement storage

Migration `0007_typed_workbook_measurements` adds typed JSON storage for categorical/structured readings and allows longer workbook unit descriptions. All 83 workbook indicators are represented, retaining existing internal fields. Original numeric/boolean storage, IDs and raw payloads remain intact. New independent random fixtures are stored and exposed via dashboard measurements, but do not override validated alert context or calculated scores. See [expanded generator definitions](../docs/expanded-workbook-simulation.md).


## NEWS2 evidence and retained severity

`evidence.components` contains numerical component scores, not measurement values.
A zero score is valid when an available reading contributes no points. Missing or
invalid components remain unknown; they are not filled with zero. Full assessments
and partial lower bounds are distinguished in the evidence.

For example, a latest total of 2 yields an Advisory candidate. If the alert already
holds Emergency, `candidate_tier` can be Advisory while `tier` remains Emergency
and `held_until_three_normal_readings` is true. Recovery requires three distinct
later qualifying normal observations per tier. A later observation still triggering
an alert resets the normal counter, even when its candidate tier is lower. The
frontend labels these scores and the retained/calculated tier distinction.
