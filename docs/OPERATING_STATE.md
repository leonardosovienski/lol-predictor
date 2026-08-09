# Canonical operating state

This document reconciles historical handoffs that remain in the repository.
When it conflicts with an older narrative document, the versioned data record
and this document take precedence.

## Scientific baseline

The normalized Phase 1 prequential run measured 3,053 maps: H1 Brier 0.4432
versus regional-band baseline 0.4612, accuracy 64.6%, and Diebold-Mariano
p=0.0006. The lived rating artifact contains 82 historical rating keys. Team
identity is now governed separately by `data/canonical_teams.json`, whose first
registry contains all 495 Oracle provider team IDs observed in the versioned
2025/2026 sources. Resolution permits only an exact provider ID or an exact
registered NFC/casefolded name; substring matching is forbidden on this
transition path.

The runtime artifacts `data/ratings.json` and `data/calibration.json` are
intentionally ignored because they are regenerated locally. Every operational
run must record their SHA-256 values and cutoff timestamp. Serving consumes
the lived ratings when available. Kills serving never consumes team statistics:
when calibration is published it requires an explicit league and uses only that
league's total-kills mean and sigma; otherwise it reports the explicit legacy
global baseline from `config.yaml`.

## H4 V2

`data/h4_v2_closure.json` is the sole authority for H4 lifecycle. It preserves
the 2026-07-23 human closure and records the audited 2026-07-25 reopening for
prospective collection only. This is not an approval or refutation and real
money remains permanently NO_GO. All collectors and evaluators must consult
that record and fail closed whenever its current state is closed.

## CI contract

CI runs the complete test suite on Python 3.13 and may not mask failures.
Tests must use fixtures or explicit temporary runtime artifacts rather than
depending on an operator's ignored local data directory.

## Canonical operational pipeline

The installed `lol-predictor` CLI is the only supported entrypoint for new
scheduled operations. Its phases are `ingest`, `collect-holdout`,
`publish-snapshot`, `backtest`, `publish-freeze`, `settle`, `collect-shadow`,
and `health`. `jobs.json` is validated and executed
by `predictor-ops` 3.x; the external scheduler controls cadence only.

`ingest` uses the resilient downloader and its atomic immutable-snapshot
publication contract. `publish-snapshot` is an explicit validation/idempotency
barrier over that publication; it never duplicates equal content. `backtest`
builds an isolated database from the current immutable `payload.csv`, verifies
its SHA-256 against snapshot metadata, and records the processed input hash in
`data/.idem_state/backtest.json`. It no longer uses the mutable operational
`lol.db` when invoked through the canonical CLI.

The latest observed UTC calendar day is reserved as a real OOS partition and
is excluded from rating generation. `backtest_manifest.json` seals that split,
the input snapshot, configuration and processing code, plus every derived
artifact. `publish-freeze` validates it and publishes an immutable core 2.2
`DatasetFreeze` under `data/freezes/`, then atomically moves
`data/current_freeze.json`. Serving loads ratings exclusively through this
pointer and rejects missing, stale, modified, path-escaping or version/code-
incompatible manifests. Every canonical prediction carries `freeze_id`, the
freeze seal, snapshot hash and ratings hash.

## Transition collection and prospective holdout

During the shadow transition, `publish-snapshot` preserves the legacy Oracle
CSV contract and also adapts each resolvable map to the core 2.2
`ObservationEnvelope`. Envelopes use Oracle `gameid` plus both immutable
canonical team IDs and are appended to `data/collection_archive/events.jsonl`.
Unknown or ambiguous identities are excluded from that archive, written to an
append-only quarantine record and surface as an alert in health. This is the
new principal collection contract; legacy CSV remains a compatibility input
until the dual-write acceptance window closes.

The independent `lol-collect-holdout` job runs as `COLLECTION_ONLY`, archives
content-addressed captures below `data/holdout/raw/`, and never calls snapshot,
backtest or freeze publication. Its versioned charter prohibits any training,
feature selection or tuning use. Data-only evaluation freezes will be created
only after the declared prospective window closes.

The CLI emits one JSON result on stdout and structured JSON events on stderr.
Exit 0 means success (including an idempotent skip), exit 1 is an operational
failure, and exit 2 is an input or contract failure. Real-money operation and
scientific promotion beyond the registered lifecycle remains out of scope.
The pipeline transports `COLLECTION_ONLY → HYPOTHESIS_REGISTERED →
DATASET_FROZEN`; market collection and settlement remain `SHADOW` and real
money remains `NO_GO`.
