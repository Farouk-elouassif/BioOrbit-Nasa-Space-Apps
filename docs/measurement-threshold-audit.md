# Measurement and alert audit

Reviewed 15 November 2026 against `BioOrbit_Measurements_and_Alert_Thresholds.pdf` (14 November reference), using the current working tree, including existing uncommitted edits. Files changed during the review, so this is a working-tree assessment, not a release certification. No application code was changed for this audit.

## Conclusion

The numerical boundaries generally match the PDF. The implementation is not fully aligned: exposure-period handling and sleep recovery have gaps, an additional solar-storm condition is undocumented, and the PDF's simulator limitations are outdated.

## Project flow

The Python simulator generates preflight profiles and in-flight astronaut/cabin events, journals them locally, and delivers batches to Django. Django validates units, domains, types and identities, stores immutable events, updates latest values, then evaluates alerts inside the ingestion transaction. Historical observations supply averaging windows, persistence and personal references. Persistent alerts and assessments feed the React dashboard and acknowledgment API. Frontend colors and severity come from backend alerts. Workbook JSON preserves source metadata; executable thresholds live in `engine.py`. Notification recipients and actions are informational; the application does not dispatch them.

## Findings

### 1. Noise averages mix work and sleep exposure

`backend/bitorbit/core/alerts/engine.py`, noise branch and `Frame.mean` / `average`.

Only the latest reading's `sleep_period` selects the eight-hour sleep or sixteen-hour work threshold. Historical samples are not checked for a matching period. Reproduced with eight hours of work-tagged 55 dBA observations followed by the first sleep-tagged observation: the engine immediately returns sleep Advisory. The history does not establish eight hours of sleep exposure.

Recommendation: define exposure periods explicitly, validate historical period tags, and evaluate a completed qualifying exposure or clearly document a rolling mixed-period assumption. Keep energy averaging.

### 2. Normal awake time can permit sleep-alert recovery with missing sleep history

`backend/bitorbit/core/alerts/engine.py`, sleep branch (`enough=... or awake is not None`); `service.py`, normal-observation recovery.

Reproduced with one five-hour sleep observation, `hours_awake=2`, and no three-night or seven-day history. The sleep decision is `normal`, with empty missing inputs and `daily_values=None`. An explicit normal awake-time observation only rules out the awake-time trigger; it does not establish that the sleep-history triggers are normal. Three later distinct sleep observations under this condition can count toward recovery even when nightly history remains unavailable.

Recommendation: evaluate each sleep subcondition separately. A positive subcondition may trigger immediately; classify the combined rule normal only with sufficient negative evidence for all applicable subconditions. Otherwise retain insufficient data and the active alert.

### 3. Additional solar-storm Warning is absent from PDF

`backend/bitorbit/core/alerts/engine.py`, solar-storm branch.

Reproduced `is_solar_storm=true`, nausea=true, NOAA level=0 and projected dose=0: Warning. The PDF's measurement 26 table lists Warning at projected dose >=200 mSv, but omits this symptomatic storm path. This is a documentation/specification discrepancy; it should not be removed without deciding whether the underlying workbook intends it. The symptomatic path is also gated by the presence of a NOAA or projection input.

Recommendation: reconcile the workbook, PDF and executable rule, including whether symptoms alone qualify and what inputs are required.

### 4. PDF no longer describes current simulator coverage

`simulator/space_sim/model.py`, `simulator/space_sim/scenarios.py`, and ingestion profile validation.

The working tree now generates in-flight body mass, preflight stress samples, consciousness, supplemental oxygen status, synthetic negative symptom findings, NOAA level/projection fields, work/sleep tags, surface-body context, explicit pressure-loss negatives, and frequent systolic/temperature spot checks. It also supports scenario overrides. Consequently:

- Body mass is no longer preflight-only; the catalogue still has 26 unique types, but the PDF's 14 in-flight / 3 preflight-only split is outdated (now 15 / 2, plus 9 cabin types).
- Stress can have a personal baseline for newly generated runs.
- Combined NEWS2 is no longer inherently blocked by missing consciousness/oxygen inputs; valid baseline, activity, coherent timing and persistence requirements still apply.
- Noise, surface dust and conditional rules can receive context the PDF says is unavailable.
- Existing saved runs need separate consideration: immutable old journal records are not retroactively enriched.

Recommendation: regenerate the PDF and README after the simulator work stabilizes. Label synthetic negative findings clearly and verify saved-run behavior separately.

## Measurement-by-measurement review

“Match” means executable conditions match the document on inspection; it does not claim exhaustive integration coverage.

| # | Measurement | Assessment |
|---|---|---|
| 1 | Heart rate | Match: integer bands, preflight exception, 3-SD drift, resting context and 5-minute persistence. |
| 2 | Respiratory rate | Match: component bands and reported breathlessness Emergency. Acute symptoms have a separate rule as well. |
| 3 | SpO2 | Match: integer bands, 2-minute persistence, quality gate and symptomatic Emergency bypass. |
| 4 | Systolic pressure | Match: integer bands, in-flight band exception and symptomatic hypotension Warning. |
| 5 | Diastolic pressure | Match: reviewed drift flag; no standalone numeric cutoff. |
| 6 | Temperature | Match: <=35 C Caution, low-temperature Advisory, baseline-relative Advisory and symptomatic >=39.1 C Warning. |
| 7 | Glucose | Match: fasting <65 / >110, symptomatic Caution; after-meal not numerically classified. |
| 8 | Sleep | Trigger thresholds match; incomplete-history recovery gap above. |
| 9 | Mood | Match: personal median drop >=2 over three consecutive days, symptoms increase severity. |
| 10 | Stress | Thresholds match; simulator baseline limitation outdated. |
| 11 | Fluid | Match: interval aggregation into complete days; three consecutive days <2 L. |
| 12 | Body mass | Match: <=95% preflight mean; simulator limitation outdated. |
| 13 | Personal dose rate | Match: complete 24-hour mean >1.3 or >0.9 by environment. |
| 14 | Mission cumulative dose | Match: no standalone threshold; total career dose used. |
| 15 | Career dose | Match: >=300 Advisory, >=450 Caution, no Emergency at 600. |
| 16 | Preflight background radiation | Match: baseline only, yearly units distinct from daily rate. |
| 17 | Previous career dose | Match: feeds total; no separate direct threshold. |
| 18 | Cabin CO2 | Match: seven-day >=2.5, one-hour >3 / >4.5; co-located symptom pattern present. |
| 19 | Cabin O2 | Match: latest <145 / >155, hourly <127, latest <122 Emergency; highest tier wins. |
| 20 | Cabin pressure | Match: <34.5 / >103 Caution and explicit rapid-loss Emergency. |
| 21 | Cabin temperature | Match: <18 / >27 Advisory. |
| 22 | Humidity | Match: latest >60 or one-hour mean <25 Advisory. |
| 23 | Noise | Numeric thresholds and logarithmic averaging match; history period qualification gap above. |
| 24 | Dust | Match: Moon >0.3 / Mars >0.1, surface environment and explicit body context required. |
| 25 | Cabin radiation | Match: complete 24-hour environment-specific rate thresholds. |
| 26 | Solar storm | Numeric NOAA/projected-dose thresholds match; extra symptomatic Warning undocumented. |

## Lifecycle and shared behavior

Code inspection confirms simulated-time windows/rechecks, explicit quality exclusions, full-coverage time-weighted averages with 15-minute maximum gaps, HR/SpO2 persistence with 60-second maximum gaps, integer component rounding, baseline trimming, tier colors, immediate escalation, three later normal observations per recovery step, acknowledgment without resolution, and documented recheck intervals. Missing/pending decisions generally preserve alerts; finding 2 is an exception where incomplete evidence is classified normal.

The PDF describes a prototype and is itself an implementation reference, not independent validation of medical suitability. This audit evaluates agreement with that reference only.

## Verification

- Existing offline backend suite: 49 tests passed (`.venv/bin/python backend/check_models.py`).
- Additional isolated engine checks: 99 assertions passed covering vital component edges, persistence-supported HR/SpO2, fasting glucose, career dose, cabin pressure/temperature/O2/CO2, Moon/Mars dust, work/sleep noise boundaries and personal/cabin radiation boundaries.
- Noise, sleep-history and undocumented solar paths reproduced directly with engine frames.
- PostgreSQL ingestion, acknowledgment and recovery integration were not exercised in this audit. Passing isolated thresholds does not establish full lifecycle or deployment correctness.
- Review observed concurrent changes to alert engine/service; final verification should be repeated on a fixed commit after ongoing edits finish.
- Simulator suite: 26 tests run, 1 failure and 1 skip (`PYTHONPATH=simulator .venv/bin/python -m unittest discover -s simulator/tests -q`). `test_preflight_profiles_statistics_and_units` expects 12 baseline metrics but current generation produces 13 after adding stress. Update this coverage expectation after confirming the intended new catalogue split; this is further evidence of simulator/reference drift.
