# Astronaut & cabin simulation service

Standalone Python 3.11+ service. **No runtime dependencies**; no Django, PostgreSQL, alert rules, or AI components are implemented here. All measurements are synthetic observations, not a validated physiological or radiation-transport model.

## Quick start

Run from this directory; no installation is needed:

```bash
cd /home/farouk/Desktop/bioorbit/simulator
python -m space_sim init --environment space_station
python -m space_sim history
python -m space_sim export --output data/events.jsonl
python -m space_sim live
```

`init` creates three distinct astronauts, 14 days of daily preflight observations, baseline statistics, one habitat, and an initial in-flight sample. `history` appends **30 simulated days** at five-minute frequent sampling; spot checks and daily summaries follow their own schedules. `live` resumes that exact state and emits every five real seconds. Ctrl+C or SIGTERM stops after the current atomic transaction. Run `live` again to resume. Defaults: transit spacecraft, seed 42, mission `MARS_001`, habitat `HAB_001`, UTC start `2026-11-14T00:00:00Z`, duration 180 mission days, speed 1.

For a finite accelerated demo:

```bash
python -m space_sim storm --duration 7200 --peak 12
python -m space_sim live --ticks 120 --interval 1 --speed 60
python -m space_sim status
python -m space_sim export --output data/events.jsonl
```

The storm peaks halfway through its two-hour simulated duration and then recovers. `--peak` is the cabin radiation **target in mSv/day**, not a dose and not a medical limit. At speed 60, each one-second tick advances one mission minute. Keep interval × speed at most 60 simulated seconds so HR/SpO₂ persistence can be evaluated; coarse history does not establish that persistence. Tiny storms are unsuitable for coarse demo sampling; use minute/hour-scale events so the rise and fall are visible.

## Configuration and controls

Global arguments go **before** the subcommand:

```bash
python -m space_sim --state data/station.sqlite3 init --astronauts 4 --seed 91 --environment space_station --mission-id ISS_DEMO --habitat-id HAB_002 --start 2026-11-14T00:00:00Z --duration-days 90 --speed 60 --run-id station-001
python -m space_sim --state data/station.sqlite3 history --days 2 --interval 600
python -m space_sim --state data/station.sqlite3 live --interval 1 --ticks 10
```

| Control | Command |
|---|---|
| Initialize stable preflight profiles | `python -m space_sim init` |
| Inspect clock, mission/career dose and settings | `python -m space_sim status` |
| Append history | `python -m space_sim history --days 30 --interval 300` |
| Stream until stopped | `python -m space_sim live --interval 5` |
| Change saved speed | `python -m space_sim speed 60` |
| Schedule storm now | `python -m space_sim storm --duration 21600 --peak 12` |
| Schedule storm later | `python -m space_sim storm --after 3600 --duration 21600 --peak 20` |
| Cancel storms, gradually return radiation to ambient | `python -m space_sim normal` |
| Change environment | `python -m space_sim environment surface_base` |
| Export all records | `python -m space_sim export --output data/events.jsonl` |
| Explicitly erase this local run and start a new identity | `python -m space_sim reset --confirm` |

Environment choices: `transit_spacecraft`, `space_station`, `rover`, `surface_base`. Config/state persist in the local journal. Initialization refuses to overwrite existing state. Reset creates a new run ID by default; `--run-id` may supply another unique ID. It erases local events and delivery receipts, **not data already sent downstream**. To reproduce the identical original run, use a new state file with the same configuration and run ID instead of resetting.

Run only **one generation driver** (`history` or `live`) per state file. Controls may run in another terminal while live is running: each tick reads the committed configuration. Brief controls wait for any current tick transaction. Paused wall time, HTTP delays, and shutdown downtime do not advance simulated time. `interval × saved speed` determines a live tick; the interval is a nominal pacing interval, and HTTP work may make real emission slower. History intervals are already simulated seconds and ignore speed. The mission stops at its configured total duration; choose a duration greater than the backfill when you want live continuation.

## How the model works

- Correlated preflight profiles use a latent fitness factor. Resting heart rate, respiratory rate, and blood pressure relate to it. Daily preflight observations provide per-metric mean, sample standard deviation, minimum, maximum, count, and unit. These stay unchanged after initialization.
- An eight-hour sleep opportunity, staggered exercise, daytime work, evening rest, and scheduled EVA windows set activity for each astronaut. Realized sleep duration integrates sleeping time × individual sleep quality; first summary at 06:00 is explicitly a partial window from mission start. Following summaries cover the intervening day. Activity is recorded on every observation; cabin noise/CO₂ use combined crew activity.
- A shared clock advances in internal steps no longer than 60 simulated seconds, even during sparse backfill; active storms use finer steps when needed. Exponential relaxation plus elapsed-time-scaled stochastic fluctuations creates continuous time series. Spot-check schedules are visited exactly, even when an output interval skips past them.
- Heart and breathing rates share activity drivers; blood pressure responds to exertion; glucose responds to meals and workload; temperature has daily/mission drift; mood and stress share workload context. Numerical bounds only enforce physical/scale validity, not clinical healthy ranges.
- Cabin oxygen is **partial pressure in mmHg**, never a percent. Pressure is kPa. Default pressure and oxygen are internally compatible. Cabin observations have `astronaut_id: null`. EVA personal samples use zone `EVA`; the cabin still has one shared zone.
- Radiation references come from the supplied project brief: station 0.35 mSv/day (within its 0.2–0.5 example), transit 1.8, surface base 0.67. Rover 0.8 is a **team synthetic assumption**, representing less shielding than the base. Earth background preflight rate varies around 2 mSv/year. These are approximate scenario inputs, not universal limits.
- Persistent solar events use a smooth sine-squared pulse plus gradual environmental response. The configured peak is a forcing target; the actual measured peak may lag or be lower. Normal radiation contains small correlated fluctuations. Shielding differs per person; EVA increases exposure. Rates can exceed nominal ranges during a storm.
- Mission dose uses trapezoidal integration of personal rate over every internal elapsed step: `dose += (previous_rate + new_rate) / 2 × elapsed_seconds / 86400`. Numerical accuracy depends on internal step size; it is not a radiation-transport calculation. Total career dose = fixed preflight career dose + current mission dose. Preflight background **rate** in mSv/year is a distinct quantity and is never added directly to accumulated dose.

## Durable state, reproducibility, and replay

`data/simulation.sqlite3` is the simulator's **local checkpoint and event journal**, not the application's operational database. It requires only Python's built-in `sqlite3`. RNG state, clock, schedules, profiles, cumulative dose, and the new events commit in one SQLite transaction (WAL, synchronous FULL). Interruption before commit rolls everything back; interruption after commit resumes after that tick. Do not copy a live `.sqlite3` file without its WAL; stop generation first or use SQLite's backup API.

Seed + initial configuration + ordered controls + sampling/tick schedule reproduce measured values and event IDs. Changing sampling changes RNG consumption; different sampling schedules are not promised bitwise identical. Real `emitted_at` timestamps intentionally differ. Event IDs are deterministic UUIDs based on run/mission identity, seed, start time, and persisted sequence. Give independent runs distinct `run_id` values. Keep all samples from one run ordered by observation time; equal timestamps across metrics/crew are expected. Preflight history is emitted before mission observations.

Local JSONL is an atomic **full snapshot** exported from the journal; re-export replaces the previous file rather than appending duplicates. The journal is the source of truth. Export/HTTP replay never recalculates dose. Profile records and measurements coexist in the journal and export; use `kind` and `phase` to separate them.

## HTTP delivery to Django

The matching Django receiver is now implemented at `POST /api/v1/ingest/events`. For host-run simulator commands, configure its URL and the shared token from the root `.env` explicitly:

```bash
export SIM_INGEST_URL=http://localhost:8000/api/v1/ingest/events
# If required by your ingestion API:
export SIM_INGEST_TOKEN=your-ingestion-token
python -m space_sim send --batch-size 500
python -m space_sim live --endpoint http://localhost:8000/api/v1/ingest/events --batch-size 100
```

`history --endpoint ...` sends bounded batches during generation, then drains the pending queue. `live --endpoint ...` sends small per-tick batches and any pending historical backlog. Use `send` after backfill to drain history before starting a live demo. `--single` sends a bare event object one request at a time; otherwise the body is:

```json
{"schema_version":"1.0","events":[{"...":"measurement or preflight_profile event"}]}
```

The endpoint must:

1. Validate version, kind, entity/domain, timestamps, metric type/unit, and context against [the contract](schemas/event.schema.json).
2. Persist every accepted event durably; make `event_id` unique and deduplicate replay. Duplicate IDs with identical contents count as already accepted. Reject conflicting payloads with the same ID. `Idempotency-Key` identifies the batch but is not a substitute for event-level deduplication.
3. Return HTTP 200/201 with **all** IDs from the request: `{"accepted_event_ids":["uuid-1","uuid-2"]}`. Repeated events must be acknowledged too. Bare single events use the same acknowledgment format. Empty/malformed/partial acknowledgments are treated as failure and left pending. An HTTP 204 without an acknowledgment is not success for this contract.
4. Use 400/401/403/422 for permanent request failures and 429/5xx for transient failures. HTTP 409 is a permanent failure here, so use a 2xx acknowledgment for already-stored events.

Delivery is **at least once**. Timeouts, network failures, 429 and 5xx retry with bounded exponential backoff (default three retries after the initial attempt, 10-second request timeout, maximum 30-second delay). Numeric `Retry-After` seconds are honored up to 30 seconds. Redirects are rejected to avoid forwarding credentials. Other 4xx and invalid acknowledgments are not automatically retried in the same send attempt. Events remain pending. Success is tracked separately for each exact endpoint URL, so another URL receives a full replay. Auth tokens come from the environment and are not written into state or logged.

Generation continues locally through HTTP failures. After retries, failed delivery is logged; the final drain exits nonzero if still unsuccessful. Restart `send` or `live` to retry. A crash after remote acceptance but before local acknowledgment replays the **same IDs**, which is why receiver deduplication is required.

No endpoint supplied means fully local operation, with no network requirement. `SIM_INGEST_URL`/`SIM_INGEST_TOKEN` are shell environment variables; this service does not load the repository's Django `.env` or change its settings.

## Measurement contract and catalogue

Every record includes `schema_version`, `kind`, stable `event_id`, `run_id`, `mission_id`, `habitat_id`, `zone_id`, nullable `astronaut_id`, `domain`, `phase`, `environment`, `measured_at`, `emitted_at`, `source`, `simulated: true`, and `context`.

`measured_at` is simulated UTC observation time; `emitted_at` is real UTC time when the event was generated and committed for emission. On retries/replay the original timestamps and IDs are preserved; it is not a per-HTTP-attempt timestamp. A future simulated timestamp is possible under acceleration. `context.activity` is `resting`, `sleeping`, `working`, `exercising`, or `eva`. The simulator does not emit alert classifications or diagnoses.

| Metric | Unit | Domain | In-flight cadence |
|---|---|---|---|
| `heart_rate` | bpm | astronaut | Frequent |
| `respiratory_rate` | breaths/min | astronaut | Frequent |
| `spo2` | % | astronaut | Frequent |
| `personal_radiation_dose_rate` | mSv/day | astronaut | Frequent |
| `mission_cumulative_radiation_dose` | mSv | astronaut | Frequent |
| `total_career_radiation_dose` | mSv | astronaut | Frequent |
| `systolic_blood_pressure` | mmHg | astronaut | Every 5 minutes; coherent vital spot check |
| `diastolic_blood_pressure` | mmHg | astronaut | Hourly |
| `blood_glucose` | mg/dL | astronaut | Every 4 hours; fasting/after_meal context |
| `body_temperature` | °C | astronaut | Every 5 minutes; coherent vital spot check |
| `sleep_duration` | hours | astronaut | Daily at 06:00; accumulated window |
| `mood` | 0–10 | astronaut | Daily at 06:00 |
| `stress_level` | 0–10 | astronaut | Every 6 hours |
| `fluid_intake` | L | astronaut | Every 6 hours; accumulated window |
| `body_mass` | kg | astronaut | Daily, plus preflight |
| `preflight_radiation_level` | mSv/year | astronaut | Preflight only |
| `preflight_career_radiation_dose` | mSv | astronaut | Preflight only |
| `co2_partial_pressure` | mmHg | cabin | Frequent |
| `o2_partial_pressure` | mmHg | cabin | Frequent |
| `total_cabin_pressure` | kPa | cabin | Frequent |
| `cabin_temperature` | °C | cabin | Frequent |
| `relative_humidity` | % | cabin | Frequent |
| `noise_level` | dBA | cabin | Frequent |
| `dust_concentration` | mg/m³ | cabin | Frequent |
| `radiation_level` | mSv/day | cabin | Frequent |
| `is_solar_storm` | boolean | cabin | Frequent; actual JSON boolean |

Historical frequent cadence defaults to 300 simulated seconds. Live frequent cadence defaults to 5 real seconds × speed. Periodic frequencies are fixed in `model.PERIODIC` and are in simulated time; an initial spot-check sample occurs at mission start (including a zero-length fluid window), followed by scheduled samples. Coarse history emits periodic records at their exact due times, not delayed to the next frequent sample.

Example measurement (see [generated examples](examples/sample-events.json)):

```json
{
  "schema_version": "1.0",
  "kind": "measurement",
  "event_id": "6bc950ca-1915-53af-b191-866c957851ee",
  "run_id": "demo-001",
  "mission_id": "MARS_001",
  "habitat_id": "HAB_001",
  "zone_id": "CABIN_MAIN",
  "astronaut_id": "AST_001",
  "domain": "astronaut",
  "phase": "inflight",
  "environment": "transit_spacecraft",
  "metric": "heart_rate",
  "value": 68.4,
  "unit": "bpm",
  "measured_at": "2026-12-14T00:00:05Z",
  "emitted_at": "2026-11-14T12:00:00Z",
  "source": "bioorbit-simulator",
  "simulated": true,
  "context": {"activity": "sleeping", "scenario": "normal"}
}
```

A `preflight_profile` record shares the envelope but replaces `metric/value/unit` with `profile`: `baseline_statistics` keyed by metric; each contains `mean`, `stddev`, `min`, `max`, `count`, `unit`. It also contains window dates, `preflight_radiation_level` + `preflight_radiation_unit`, and `career_radiation_dose` + `career_radiation_unit`. Daily preflight measurement records remain available to independently recompute the statistics.

## Tests

```bash
cd /home/farouk/Desktop/bioorbit/simulator
python -m unittest discover -s tests -v
```

Tests cover preflight statistics/distinctness, reproducibility, activity effects, schedule frequencies, sleep integration, cabin continuity, four environment radiation references, persistent solar storms, dose integration, acceleration, history/live continuation, exact restart, atomic rollback, JSONL export, event validation, bounded CLI execution, HTTP payloads/retries/permanent errors/acknowledgment loss, and replay IDs. A real localhost HTTP round-trip test runs where sockets are permitted; it is explicitly skipped in sandboxes that deny socket creation. Request/response adapter tests still execute there; the skip does **not** claim a real Django connection was verified.

## Layout

- `space_sim/model.py`: profiles, mission clock, schedules, dynamics, dose integration.
- `space_sim/contracts.py`: stable metric catalogue and runtime validation.
- `space_sim/storage.py`: atomic state + event journal, export, delivery receipts.
- `space_sim/transport.py`: HTTP requests, retries, acknowledgment validation.
- `space_sim/cli.py`: foreground commands and controls.
- `schemas/event.schema.json`: machine-readable JSON Schema.
- `tests/`: standard-library automated tests.

Optional package installation: `python -m pip install -e .` exposes `space-sim`; it is unnecessary for the commands above. No Docker, database infrastructure, or receiver setup is needed to generate and export data.

## Run with Docker Compose

From the **repository root**, start PostgreSQL, Django, and the simulator together:

```bash
docker compose up --build
```

The `simulator` image uses `simulator/Dockerfile` and requires no pip downloads. It runs as a non-root user. A named volume, `simulator_data`, stores `/data/simulation.sqlite3` and its journal files. Initial startup creates profiles and backfills **to mission day 30**, then starts foreground live generation. Subsequent starts resume the saved mission; a partially completed backfill resumes only its remaining portion. Stop signals are handled during backfill and live generation. On completion of the configured mission duration the container exits normally. Only failures trigger up to three restart attempts.

Simulator options are in the repository's `.env` and documented in `.env.example`:

- Initial mission settings: `SIM_MISSION_ID`, `SIM_HABITAT_ID`, `SIM_RUN_ID`, `SIM_ASTRONAUTS`, `SIM_ENVIRONMENT`, `SIM_SEED`, `SIM_START`, `SIM_DURATION_DAYS`, `SIM_PREFLIGHT_DAYS`, `SIM_SPEED`. These apply **only when state is first initialized**. Existing state retains saved profiles, environment, and speed; use live controls below for those supported changes.
- Startup history target: `SIM_HISTORY_DAYS` (default 30, set 0 for no initial history), `SIM_HISTORY_INTERVAL` (default 300 simulated seconds). Raising the target backfills further only if the current mission clock is still below it. Lowering it never rewinds the clock.
- Live delivery/pacing: `SIM_EMIT_INTERVAL` (default 5 real seconds), `SIM_BATCH_SIZE` (500), `SIM_HTTP_TIMEOUT` (10), `SIM_HTTP_RETRIES` (3).
- `SIM_INGEST_URL` and `SIM_INGEST_TOKEN`: the root `.env` configures `http://backend:8000/api/v1/ingest/events` and a shared bearer token for the implemented Django receiver. Use `backend`, not `localhost`, inside Compose. Startup backfill is local; once live starts, HTTP delivery sends the pending history and new records. Clear `SIM_INGEST_URL` for local-only operation. Recreate the service after changing environment configuration. See [backend ingestion documentation](../backend/README.md#simulator-ingestion-api).

Commands to run yourself from the repository root:

```bash
# Follow generation/startup logs
docker compose logs -f simulator

# Inspect saved mission status
docker compose exec simulator python -m space_sim status

# Change speed without resetting the mission
docker compose exec simulator python -m space_sim speed 60

# Trigger and cancel a solar storm
docker compose exec simulator python -m space_sim storm --duration 7200 --peak 12
docker compose exec simulator python -m space_sim normal

# Export a snapshot into the persistent volume, then copy it to your machine
docker compose exec simulator python -m space_sim export --output /data/events.jsonl
docker compose cp simulator:/data/events.jsonl ./events.jsonl

# Apply changed image/environment configuration
docker compose up --build simulator
```

`docker compose down` preserves state volumes. Do not delete volumes to apply ordinary configuration changes. CLI commands inside this image automatically use `SIM_STATE_PATH=/data/simulation.sqlite3`; host commands still default to `data/simulation.sqlite3`. Do not launch a second live generator against the same volume. The entry command can also be tested outside Docker with `SIM_STATE_PATH` pointing at a local file and `SIM_LIVE_TICKS` set to a finite count; this is used by the automated lifecycle tests.


The backend also accepts the equivalent workbook metric identifiers listed in [its mapping table](../backend/README.md#workbook-metric-identifier-compatibility). The simulator continues to emit its existing canonical identifiers; both forms resolve to the same database metrics. No simulator state reset or migration is required for this compatibility change.

## PDF alert coverage and scheduled scenarios (15 November update)

The 26-metric catalogue now has 15 in-flight astronaut types, 9 cabin types, and
2 preflight-only types. New runs include a thirteenth baseline (`stress_level`).
Old twelve-baseline profiles remain accepted and immutable. Resuming old state
adds the body-mass schedule but does not invent a historical stress baseline;
use a fresh state path and run ID when demonstrating the new preflight reference.

Events now carry explicit **synthetic** consciousness, oxygen-treatment status,
negative symptom/review findings, awake time, urinary findings, fitness context,
noise work/sleep tags, pressure-loss negatives, and Moon/Mars surface context.
`init --surface-body moon` or `SIM_SURFACE_BODY=moon` selects the surface; Mars is
the default. NOAA level is zero outside storms. New scheduled storms default to an explicit synthetic S1 (override with `storm --noaa-s-level 0..5`); this is not inferred from dose. Scheduled storms supply projected
excess dose from the synthetic sin² event envelope; NOAA severity is never inferred
from dose. It can be injected explicitly. These inputs are simulated facts, not
an external space-weather feed or a clinical classification.

Run from `simulator/` (with Django's migration applied before delivering events):

```bash
python -m space_sim --state data/pdf-demo.sqlite3 init --run-id pdf-demo-001
python -m space_sim --state data/pdf-demo.sqlite3 scenario --file examples/scenarios/post-eva.json
python -m space_sim --state data/pdf-demo.sqlite3 live --interval 1 --speed 30 --ticks 24
```

Add `--endpoint` to `live` to deliver to Django, with `SIM_INGEST_TOKEN` set.
The post-EVA scenario lasts five simulated minutes. It then stops overriding
normal observations; twelve later normal observations can recover an Emergency
through all four tiers. An acknowledged alert still requires recovery observations.
`normal` cancels scheduled scenarios and storms; it does not clear Django alerts.

Scenario JSON supports `name`, `after` (seconds from scheduling), `duration`
(seconds), `astronaut_id` (omit for cabin), `measurements` (catalogue values), and
`context` (including typed `rule_inputs`). Scenarios persist across restarts.
Later overlapping scenarios override earlier ones. Overrides apply only to samples
actually emitted during `[start,end)`, at each metric's normal schedule; sample
more frequently than the scenario duration. Values are controlled test fixtures,
not changes to the physical dynamics or accumulated-dose integrator. Use `storm`
when demonstrating integrated physical radiation exposure.

Other examples cover hypoxia, explicit NOAA/projected-dose severity, and pressure
loss. The same mechanism can inject every catalogue measurement and conditional
PDF input, including reviewed diastolic drift, fasting glucose symptoms, mood
symptoms, noise exposure, hydration findings, and surface dust. Supplementary
numeric entries require the exact workbook unit; boolean negatives must be explicit.

NEWS2 needs prior resting in-flight baseline history, a coherent current spot check,
and any required HR/SpO2 persistence. History at 300-second intervals does not
establish 60-second-gap persistence; follow it with at least five minutes of
30-second or finer live samples. Noise requires consistently tagged full 8-hour
sleep or 16-hour work exposure, not a mixture. Daily habit rules need their complete
history. Missing history never counts as a normal recovery observation.

## Percentage of abnormal data

Set `SIM_ERROR_LEVEL=20` in the root `.env` to deliberately inject abnormal values
into approximately 20% of newly generated in-flight measurement records. Compose
passes this value to the simulator. Accepted range: 0–100, including fractional
percentages; default `0` disables injection. Standalone initialization also accepts
`init --error-level 20`.

After changing the value, rebuild/recreate only the simulator:

```bash
docker compose up -d --build simulator
```

The setting updates an existing saved run on startup without clearing its journal
or rewriting old data. Preflight data and profiles are excluded. Stable event-ID
sampling makes selection reproducible across restarts and delivery retries without
changing the dynamics RNG. Positive levels add `context.error_injection` with
`selected` and `percentage` for inspection. Explicit scheduled scenarios take
precedence over automatic injected values.

The percentage describes **injected measurements**, not the percentage of active
alerts or a requested severity. Some injected readings trigger immediately; others
require sustained readings, complete history or applicable environment context.
Normal dynamics can also trigger alerts. `0` disables deliberate injection rather
than guaranteeing zero alerts. Automatic fixtures do not alter the physical state
or dose integrator, and deliberately high dose fixtures may therefore decrease
when the next uninjected observation arrives. Use scheduled scenarios/storms for
coherent sustained incidents and physical accumulated-dose demonstrations.

## Alert-fix demo controls

Use a fresh station state for a nominal demo; transit remains 1.8 mSv/day and can
legitimately produce a persistent design-reference Advisory. Existing saved states
retain their environment. Historical storms without severity metadata remain S0.

```bash
python -m space_sim storm --duration 7200 --peak 12 --noaa-s-level 1
python -m space_sim live --interval 1 --speed 60
# In another terminal, using the same --state if specified:
python -m space_sim symptom --astronaut AST_002 chest_pain
python -m space_sim normal
```

Symptoms persist on subsequent emitted observations until `normal` clears all
scheduled scenarios and storms. Controls do not send an observation immediately;
the next generation tick carries the change. `normal` does not directly clear
backend alerts: their existing recovery rules still apply.

The alert engine now scores working vitals, applies only low-value checks during
exercise/EVA and the following 20 mission minutes, suppresses pulse 41–50 and
breathing 9–11 sleep Advisories, and uses a ±5 mmHg systolic reference tolerance.
Heart-rate baseline drift applies only at rest. These are team prototype rules.
Low glucose is checked regardless of meal context (<70 Advisory; <54 or shaking/
sweating Caution; low glucose with confusion Emergency). The last fasting reading
within 24 hours remains available for fasting-specific checks.

Coherent available vital components within five minutes can establish a partial
space-adjusted NEWS2 lower bound: ≥5 Warning, ≥7 Emergency. Missing components
remain listed; a low partial score cannot establish normality. This is a prototype
adaptation, not a complete or validated NEWS2 assessment. Storm Cautions use
explicit synthetic severity and workbook shelter guidance. No 250 mSv projection
limit or validated coverage count is claimed by these changes.

ECG reports use the same durable scenario control:

```bash
python -m space_sim symptom --astronaut AST_002 ecg_alarm
python -m space_sim symptom --astronaut AST_002 lightheadedness
```

Normal events supply explicit negative ECG findings; the controls supply an alarm
until `normal` clears scenarios. The engine combines an alarm with associated
symptoms for escalation. Diastolic drift and rapid cabin-pressure loss can now be
detected from measured history without injected flags; diastolic needs its
in-flight baseline window. A scenario may tag a planned pressure change with
`context.planned_pressure_change: true` to suppress the inferred loss rule.
