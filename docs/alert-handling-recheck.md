# Alert handling recheck — 15 November 2026

> Historical review snapshot. Later fixes and the expanded simulator supersede parts of this report. For current behavior, see the [project README](../README.md), [backend README](../backend/README.md) and [expanded simulation notes](expanded-workbook-simulation.md). Test counts below describe the review when it was run.

Assessment: improved, but one confirmed alert-loss case prevents a clean pass. No application changes made during this review.

## Confirmed issue: Emergency can disappear inside an ingestion batch

Location: `backend/bitorbit/core/ingestion/service.py`, latest-value projection and final `evaluate_run(run)` call (lines 130–173).

PostgreSQL reproduction on an isolated Django test database:

1. Submit one batch containing cabin O2 partial pressure 120 mmHg at 12:00:00 UTC, followed by 150 mmHg at 12:00:05 UTC for the same run/cabin.
2. Both events are stored, but latest-value projection retains only 150 mmHg before alert evaluation.
3. No `cabin_o2` alert is created. The test expecting an active Emergency fails with an empty alert list.

The PDF says latest O2 <122 mmHg triggers Emergency immediately, and recovery needs three later normal observations per tier. Processing these same observations separately raises the Emergency; batch delivery therefore changes alert behavior. This also matters for backlog/retry batches and short-lived symptom/scenario facts. Historical records remain stored, but the alert is missed.

Recommendation: evaluate chronological observation groups while processing a batch, retaining simultaneous facts together, or implement an explicit chronological alert replay path. Verify that single-event and batched delivery produce equivalent trigger/recovery transitions. Do not clear an intermediate Emergency merely because a later sample in the batch is normal.

## Previous issues now fixed

- Work-tagged noise history cannot establish a sleep exposure window; dedicated regression passes.
- Normal awake-time alone cannot establish normal sleep history; dedicated regression passes.
- Supplemental facts have independent latest-input storage, survive omission, and reject older replay as the latest fact.
- Pattern rules have explicit normal/unknown decisions and tested recovery.

## Verification

- Offline backend: 56 tests passed.
- Simulator: 34 tests run, passed with one skipped.
- PostgreSQL alert/PDF suite: 20 tests passed, including ingestion, acknowledgment, duplicate protection, all-tier recovery, supplemental-fact replay, post-EVA and storm recovery, and simulator NEWS2 evaluation.
- Additional batch Emergency regression: 1 test failed as described above.
- Read-only live dashboard response: 20 active alerts; NEWS2 correctly reports insufficient data where required components or coherent observations are unavailable. This snapshot alone does not establish validity of every existing alert.

The checked-in Docker test command for `core.test_pdf_scenarios` currently fails on `Path(__file__).resolve().parents[3]` under `/app/core/`, and the backend image does not include the simulator source. To verify the suite, backend and simulator source were staged in a temporary directory inside the backend container; production mission data were not modified. Test databases were removed by Django after execution.

## Remaining scope limits

- Additional symptom-based solar-storm Warning remains absent from the reference PDF's measurement table.
- The PDF's simulator coverage limitations remain outdated.
- Recheck deadlines are tracked, but there is no independent watchdog evaluating new clinical alerts during ingestion outages. The UI reports loss of contact and keeps the latest state.
- This verifies software behavior against the prototype specification, not clinical validity or complete collection of all 83 workbook parameters.

## Fix follow-up

Batch ingestion now publishes new observations in mission-time order and evaluates
all readings/facts sharing each timestamp together. Later samples in the same
batch cannot overwrite an intermediate Emergency before evaluation. The same
transaction/run lock covers the complete batch. Already-stored newer state is
not rewound by late historical delivery. Five database regressions cover the O2
Emergency, duplicate/reversed delivery, single/batch recovery equivalence,
supplemental pressure-loss flags, simultaneous readings and late history.

This corrects new ingestion; it does not replay previously missed historical
transitions. Large batches covering many timestamps perform more evaluations.

Fix verification: the full backend suite passed on PostgreSQL (104 tests),
including all five new batch regressions. The offline backend suite also passed
(56 tests), and `git diff --check` passed. No new migration is required for this
batch-processing change. The running backend image was not rebuilt as part of
the source fix; rebuild/recreate it to activate the updated ingestion code.
