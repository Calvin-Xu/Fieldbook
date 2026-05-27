# Fieldbook Dogfood Pain Points

Date: 2026-05-22

These are issues observed while using Fieldbook from the Marin checkout for active data-mixing experiments. They should inform upcoming Fieldbook phases, but are not themselves a full spec.

## Manual Freshness Discipline

Fieldbook is useful once updated, but agents still have to remember to update it after launches, retries, collections, and context switches. This is the main reliability gap. The context-switch workflow should make the expected sequence hard to skip: inspect current experiment, refresh external state, update jobs/runs/validations, add a checkpoint or handoff, then switch.

## Runs As Datapoints

The `runs` table needs to be populated as the experiment matrix, not as a byproduct of successful jobs. Jobs are execution attempts; runs are intended datapoints. Progress questions should be answered as datapoint coverage, for example `26/117 runs complete`, with job-level failures/retries as secondary provenance.

## Doctor Signal-To-Noise

`fieldbook doctor` is too noisy on a real sidecar ledger. Legacy archived experiments, old recovered debug notes, and global warnings can swamp the few issues that matter for the active experiment. We need experiment-scoped doctor output, severity filters, and defaults that suppress archived-history noise unless explicitly requested.

## Recovery Ergonomics

Retry and recovery lineage is still too manual. When a failed launcher or eval attempt is superseded by a retry, agents need an explicit low-friction command to mark the old job as recovered, superseded, ignored, or linked to a successful descendant with a reason.

## Validation Visibility

Structured validations are useful, but status and context should surface the latest warning/failure validations near the top. Coverage warnings such as incomplete eval columns should be visible without searching notes or artifacts.

## Ledger Health

A transient SQLite `disk I/O error` occurred during parallel validation writes while the local disk was nearly full. Fieldbook should report low-disk and WAL-related risks through doctor before writes start failing.

## Agent Shell Ergonomics

Several ad hoc command failures came from piping JSON into `python - <<'PY'`, where the here-doc consumes stdin. The Fieldbook skill and cookbook should prefer `jq`, temp files, or `python -c` examples for JSON processing.

## Ledger Locality

`fieldbook db where` has helped, but multiple ledgers and dogfood directories still create cognitive overhead. Locality warnings and session surfaces should continue to make it obvious which ledger and experiment an agent is updating.
