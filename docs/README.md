# Documentation map

Read `OPERATING_STATE.md` first. It is the current, reconciled statement of
scientific metrics, runtime-artifact provenance, and H4 lifecycle.

The older report and handoff documents preserve their contemporaneous
decisions. They are historical evidence and must not override the versioned
closure record or the operating-state document when their operational status
differs.

Runtime artifacts are deliberately local. A successful weekly refresh writes
`data/runtime_artifacts.json` with SHA-256 values for ratings, calibration,
database, and team registry; that manifest is the required evidence for a
specific local serving run.
