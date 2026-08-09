"""Build the reviewed identity registry from Oracle team rows and existing seeds."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import defaultdict
from pathlib import Path

from src.identity import SCHEMA, normalized_name


def build(data_root: Path, inputs: list[Path], existing: Path | None = None) -> dict:
    prior_by_oracle: dict[str, str] = {}
    if existing and existing.is_file():
        prior = json.loads(existing.read_text(encoding="utf-8"))
        for row in prior.get("teams", []):
            for value in row.get("providers", {}).get("oracles_elixir", {}).get("ids", []):
                prior_by_oracle[value] = row["canonical_id"]
    seed = json.loads((data_root / "teams_lol.json").read_text(encoding="utf-8"))
    preferred = {normalized_name(row["name"]): row["name"] for row in seed["teams"]}
    aliases_doc = json.loads((data_root / "polymarket_aliases.json").read_text(encoding="utf-8"))
    aliases = aliases_doc.get("aliases", {})
    observed: dict[str, set[str]] = defaultdict(set)
    for path in inputs:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                team_id, name = (row.get("teamid") or "").strip(), (row.get("teamname") or "").strip()
                if team_id and name:
                    observed[team_id].add(name)
    teams = []
    for oracle_id, variants in sorted(observed.items()):
        normalized = sorted({normalized_name(value) for value in variants})
        display = next((preferred[key] for key in normalized if key in preferred), sorted(variants)[0])
        canonical_id = (
            prior_by_oracle.get(oracle_id) or f"lol-team-{hashlib.sha256(oracle_id.encode()).hexdigest()[:16]}"
        )
        extra_aliases = [source for source, target in aliases.items() if normalized_name(target) in normalized]
        teams.append(
            {
                "canonical_id": canonical_id,
                "display_name": display,
                "names": sorted(set(variants) | set(extra_aliases) | {display}),
                "providers": {
                    "oracles_elixir": {"ids": [oracle_id]},
                    "pandascore": {"ids": []},
                },
                "status": "ACTIVE",
            }
        )
    sources = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
    return {
        "schema_version": SCHEMA,
        "registry_version": "2026-08-09.1",
        "id_policy": "internal ID derived once from the first stable Oracle team ID; existing IDs are preserved",
        "matching_policy": "exact provider ID or exact NFC/casefolded registered name; fuzzy matching forbidden",
        "sources_sha256": sources,
        "teams": sorted(teams, key=lambda row: row["canonical_id"]),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument("--output", type=Path, default=Path("data/canonical_teams.json"))
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    inputs = sorted((args.data_root / "manual_upload").glob("*_OraclesElixir.csv"))
    value = build(args.data_root, inputs, args.output)
    rendered = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if args.check:
        return 0 if args.output.is_file() and args.output.read_text(encoding="utf-8") == rendered else 1
    args.output.write_text(rendered, encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
