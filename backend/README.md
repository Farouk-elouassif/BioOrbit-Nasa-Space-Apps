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
| `BronzeExportBatch` | `bronze_export_batches` |

The models preserve the supplied column lengths, nullable columns, database defaults, UUID/string identifiers, enum CHECK constraints, value/subject checks, and named partial indexes. Generated numeric IDs use Django's PostgreSQL bigint identity implementation of `BigAutoField`. JSON fields use PostgreSQL JSONB. All FK deletions use ORM `PROTECT`; the database also enforces referential integrity. Django may create its normal additional foreign-key indexes.

`MissionCrew.pk` is `(mission_id, astronaut_id)` and `PreflightBaseline.pk` is `(profile_id, metric_id)`, backed by genuine composite primary keys. No surrogate ID was added. Django's composite-primary-key admin/relational limitations still apply; neither composite-key model is registered in admin or used as a foreign-key target. See [Django's composite-key documentation](https://docs.djangoproject.com/en/6.1/topics/composite-primary-key/).

Foreign keys have conventional Django names: `run`, `metric`, and `source_event`; their database columns remain `run_id`, `metric_code`, and `source_event_id`. For example, `MeasurementEvent(run_id='demo-001', metric_id='heart_rate', ...)` supplies their referenced identifiers, while `event.metric` resolves the catalogue model.

Defaults exist both in Python and at database level. The nullable defaulted fields from the supplied SQL remain nullable. `LatestMeasurement.updated_at` defaults on insert; it is **not** an automatic update trigger. The future ingestion/upsert path must explicitly advance it. Preflight background rate (mSv/year) and pre-mission career dose (mSv) remain separate fields.

The ingestion service provisions consistent mission/habitat/crew references and metric definitions, validates run ownership and metric domain/type, journals events, and projects profiles/latest readings atomically. Direct ORM or SQL writes can still violate cross-row semantic relationships not expressed by the supplied foreign keys. A separate Django Bronze worker now exports committed raw events; an alert service is not implemented.

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

- The whole batch is validated before database writes. Every new event is stored in `measurement_events` with the original v1 payload in `raw_payload` (UUID spelling canonicalized), context and timestamps intact, and `bronze_status='pending'`. The Bronze worker exports it asynchronously after commit.
- Source `mission_id`, `habitat_id`, and `astronaut_id` are external **codes**, resolved to internal rows. Missing missions, habitats, astronauts, runs, crew assignments, and catalogue entries are created as needed. Names remain unspecified because the simulator contract supplies codes, not personal names. The first observed habitat becomes the crew assignment; event habitat/zone tracks later locations.
- The same `run_id` cannot belong to another mission. Existing catalogue definitions cannot silently change unit, domain, value type, or aggregation meaning. Run metadata reflects the newest observed environment; late backfill does not overwrite it.
- Duplicate event IDs with identical payloads, or payloads differing only in documented equivalent metric identifiers/units, are acknowledged without a second write or projection. Conflicting payloads return 409 and roll back the **entire batch**, including newly provisioned metadata. `emitted_at` is part of the payload: resend from the original journal, rather than regenerating the same run ID with different emission timestamps.
- Preflight profiles create `preflight_profiles` and all twelve `preflight_baselines`. Profiles are immutable per run/astronaut; resend the original event ID to retry. Ordinary preflight observations stay in the journal and never overwrite live measurements.
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


## Bronze raw JSON export

The ingestion transaction commits to PostgreSQL first. The separate `bronze-worker` service runs the Django management command `export_bronze --watch` against the committed journal. It polls every two seconds by default; ingestion acknowledgments do not wait for disk I/O or Bronze export.

```text
Simulator → ingestion → PostgreSQL measurement_events (pending)
                                ↓
                      durable export-batch manifest
                                ↓
                      immutable Bronze JSON file
                                ↓
                      exported status + timestamp
```

Migration `0002_bronze_export_batches` adds `bronze_export_batches` and the nullable `measurement_events.bronze_batch_id` link. This records the exact event membership and file path **before** writing files. Existing pending events are automatically eligible; no simulator reset or historical replay is needed.

Run yourself from the repository root:

```bash
docker compose up --build
```

Compose now runs PostgreSQL, the Django backend, the simulator, and the Django Bronze worker. Backend startup applies pending migrations. Both the worker and simulator wait for backend readiness; the worker uses the same backend Dockerfile and has no exposed HTTP port.

Files are stored directly in **`lakehouse/bronze/` in the repository root**, bind-mounted at `/data/bronze` in both Django containers. Compose uses `BIOORBIT_UID`/`BIOORBIT_GID` from `.env` so generated files belong to the host user. The shared `:z` mount label supports SELinux hosts. Fresh checkouts should set these IDs to the output of `id -u` and `id -g` when they differ from 1000. Example layout:

```text
/data/bronze/
  run=demo-001/
    domain=astronaut/
      phase=inflight/
        date=2026-11-14/
          batch=<export-batch-uuid>.json
    domain=cabin/
      phase=inflight/
        date=2026-11-14/
          batch=<export-batch-uuid>.json
```

Every `.json` file is a JSON **array of complete `raw_payload` objects** from the database. It includes normal and unusual measurements, boolean cabin measurements, preflight observations, and profile records. Source metric aliases and units remain intact; no cleaning, normalization, aggregation, or medical scoring occurs in Bronze. UUID spelling is already canonicalized by ingestion. `received_at` and export timestamps remain in PostgreSQL; `measured_at` and `emitted_at` remain inside each raw event.

Files are partitioned by run, domain, phase, and **UTC observation date**, including historical or accelerated dates. Run codes are escaped for paths; exceptionally long encoded codes use a SHA-256 `run_hash=` directory to stay within filesystem limits. The original code remains inside every raw event. Rows inside each file are ordered by observation timestamp and event ID. Filenames are immutable batch identities, not chronological sequence numbers; a later analytical reader should order by the event timestamps. The default claim takes at most 1,000 events and splits them into separate files for each partition represented.

Reliability behavior:

- Export workers read committed PostgreSQL records only. The durable claim transaction fixes batch membership before file I/O; these helpers must not be called inside an outer application transaction.
- Files are written to a temporary file, flushed and synced, then published atomically without overwriting an existing final file. Parent directory entries are synced too. Local POSIX filesystem operations are used; the project Bronze directory must be on a filesystem supporting hard links and directory syncing.
- The database is marked `exported` only after publication succeeds. A failed write leaves the batch/event rows pending. Watch mode logs the failure and retries; HTTP ingestion can continue independently.
- If the process stops after file publication but before database confirmation, retry uses the same manifest, same event IDs, and same path. An identical existing file is accepted without duplication or replacement.
- If an existing final file has different content, export stops that pass and retries with an error log; it never overwrites or marks corrupted data as successfully exported. Investigate/restore that file before expecting the queue to continue past it.
- PostgreSQL row locks with `skip_locked` prevent simultaneous workers from processing the same claimed batch. Replayed ingestion events do not reset their export state.
- A forced interruption can leave hidden `.tmp` files. Final `.json` files are complete arrays; readers should ignore temporary files. Back up PostgreSQL and the Bronze directory together. Deleting Bronze files does not automatically reset already-exported database receipts.

Configuration in `.env`:

```dotenv
BRONZE_BATCH_SIZE=1000
BRONZE_POLL_INTERVAL=2
```

`BRONZE_ROOT` defaults to `backend/bitorbit/data/bronze` outside Docker; Compose sets `/data/bronze` explicitly. Generation controls and simulator delivery are unchanged.

Inspection and one-shot commands to run yourself:

```bash
# Worker progress and failures
docker compose logs -f bronze-worker

# Export pending data manually; safe alongside the worker
docker compose exec backend python manage.py export_bronze --max-batches 5

# Files already appear directly on the host
ls lakehouse/bronze

# Run PostgreSQL ingestion, model, and exporter transaction tests
docker compose exec backend python manage.py test core
```

Ordinary `docker compose down` preserves the PostgreSQL/simulator named volumes and the host `lakehouse/bronze/` directory. Silver, Gold, Parquet transformations, and DuckDB queries remain future work.

The offline checker runs real temporary-filesystem tests for publication, raw-payload preservation, idempotent retry, conflicting-file protection, traversal protection, and failed-write cleanup. PostgreSQL tests additionally cover manifest claiming, crash-after-publication recovery, pending-state retention, limits, and replay. Database tests are supplied for the Docker command above; they have not been executed by the assistant.


If an older deployment already wrote Bronze files to the former named volume, copy them from the old container **before recreating it**. The old named volume is not deleted by this configuration change. Preserving its files matters because PostgreSQL may already mark those batches as exported.

```bash
docker compose stop bronze-worker
docker compose cp bronze-worker:/data/bronze/. ./lakehouse/bronze/
docker compose up --build
```

For a first deployment with no previous Bronze files, only `docker compose up --build` is needed.

## Connected frontend read APIs

The shared local crew console now uses two **GET-only** endpoints. They do not require the ingestion bearer token and do not modify state. The backend is still published only on localhost by Compose; Vite forwards browser `/api` requests to it through its development/preview proxy. There is no user-login flow. Apply network access controls before exposing crew health data outside the intended local environment.

### `GET /api/v1/dashboard`

Optional query parameters: `run_id`, `habitat_id`, `zone_id`. Without a run ID, the newest active run is selected, falling back to the newest available run. Invalid explicit run/habitat/zone selections return 404. An empty database returns 200 with `run: null`, `crew: []`, and no fabricated measurements.

The response includes:

- Available recent runs, selected mission/run/environment, earliest in-flight observation, latest simulated observation time, and mission day derived from that range.
- Actual run participants and their names/codes. It does not combine participants from unrelated historical runs.
- Latest astronaut readings and habitat/zone-scoped cabin readings, including canonical metric, numeric/boolean value, unit, source event ID, measured/emitted/received timestamps, source, simulation flag, and context/activity.
- Personal preflight baseline means, standard deviations, minima, maxima, and sample counts.
- Up to 24 recent real heart-rate observations per astronaut for roster mini charts.
- A freshness indicator (`current`/`overdue`) based on elapsed **simulated time** relative to the newest observation. Collection thresholds follow the simulator's default cadences with tolerance. They are not clinical alert classifications and do not yet adapt to arbitrary custom historical sampling intervals.
- `alerts_available: false`, because the clinical alert engine is not implemented.

### `GET /api/v1/trends`

Required: `metric` plus `astronaut_id` for astronaut measurements or `habitat_id` for cabin measurements. Also accepts `run_id`, `domain` (`astronaut` by default, or `cabin`), `zone_id`, and `window` (`24h`, `7d`, `30d`). Workbook metric aliases are accepted. Unknown subjects return 404; invalid metric/domain/window combinations return 422.

Charts use **in-flight PostgreSQL measurement history** anchored to the selected run's latest observation time. They do not invent missing days or include preflight observations as flight trends. The 24-hour view groups by UTC hour; longer windows group by UTC day. Point metrics use the mean, cumulative metrics use the maximum, and interval-total metrics use the sum of recorded window totals. Each bucket contains timestamp, value, and source sample count. Boolean metrics remain available in the dashboard but have no numeric trend endpoint.

This operational history endpoint is an interim serving path while Gold/DuckDB is pending. Both endpoints set `Cache-Control: no-store`; database failures return 503 rather than synthetic fallback data. The frontend polls dashboard data every five seconds and charts every fifteen seconds.

Run these yourself after rebuilding:

```bash
docker compose up --build
docker compose exec backend python manage.py test core
```

The read integration adds no models or migrations. `core.test_reads.ReadDatabaseTests` covers ingested values reaching dashboard/trend responses, per-run isolation, preflight references, boolean false, real aggregation, empty states, and invalid selections. Offline request/serialization tests are included in `backend/check_models.py`; PostgreSQL tests still require your running Docker setup.
