# Canonical operating state

This document reconciles historical handoffs that remain in the repository.
When it conflicts with an older narrative document, the versioned data record
and this document take precedence.

## Scientific baseline

The normalized Phase 1 prequential run measured 3,053 maps: H1 Brier 0.4432
versus regional-band baseline 0.4612, accuracy 64.6%, and Diebold-Mariano
p=0.0006. The lived rating artifact contains 82 canonical identities.

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
