#!/usr/bin/env bash
# Reuse helper for this sandbox session only — see note below.
set -euo pipefail
cd "$(dirname "$0")/../.."
export ORACLES_ELIXIR_2026_URL="file://$(pwd)/data/manual_upload/2026_LoL_esports_match_data_from_OraclesElixir.csv"
export ORACLES_ELIXIR_2025_URL="file://$(pwd)/data/manual_upload/2025_LoL_esports_match_data_from_OraclesElixir.csv"
export PYTHONPATH="$(pwd)"
exec uv run python3 scripts/atualiza_semanal_payload.py
