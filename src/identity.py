"""Explicit, versioned team identity registry. No fuzzy matching is allowed."""

from __future__ import annotations

import json
import unicodedata
from dataclasses import dataclass
from pathlib import Path

SCHEMA = "lol-canonical-teams/1.0"


class IdentityError(ValueError):
    """An identity is unknown, ambiguous, or the registry is invalid."""


def normalized_name(value: str) -> str:
    return " ".join(unicodedata.normalize("NFC", value).strip().casefold().split())


@dataclass(frozen=True)
class CanonicalTeam:
    canonical_id: str
    display_name: str
    oracle_ids: tuple[str, ...]
    pandascore_ids: tuple[str, ...]
    names: tuple[str, ...]


class IdentityRegistry:
    def __init__(self, path: Path):
        self.path = path
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise IdentityError(f"canonical team registry unavailable: {path}") from exc
        if raw.get("schema_version") != SCHEMA or not isinstance(raw.get("teams"), list):
            raise IdentityError("canonical team registry has an unsupported schema")
        self.version = str(raw.get("registry_version", ""))
        self._by_canonical: dict[str, CanonicalTeam] = {}
        self._by_provider_id: dict[tuple[str, str], CanonicalTeam] = {}
        names: dict[str, list[CanonicalTeam]] = {}
        for row in raw["teams"]:
            providers = row.get("providers") or {}
            oracle = providers.get("oracles_elixir") or {}
            panda = providers.get("pandascore") or {}
            team = CanonicalTeam(
                canonical_id=str(row["canonical_id"]),
                display_name=str(row["display_name"]),
                oracle_ids=tuple(str(value) for value in oracle.get("ids", [])),
                pandascore_ids=tuple(str(value) for value in panda.get("ids", [])),
                names=tuple(str(value) for value in row.get("names", [])),
            )
            if team.canonical_id in self._by_canonical:
                raise IdentityError(f"duplicate canonical ID: {team.canonical_id}")
            self._by_canonical[team.canonical_id] = team
            for provider, values in (("oracles_elixir", team.oracle_ids), ("pandascore", team.pandascore_ids)):
                for value in values:
                    key = (provider, value)
                    if key in self._by_provider_id:
                        raise IdentityError(f"duplicate provider identity: {provider}:{value}")
                    self._by_provider_id[key] = team
            for value in {team.display_name, *team.names}:
                names.setdefault(normalized_name(value), []).append(team)
        self._by_name = names

    def resolve(self, *, provider: str, provider_id: str | None = None, name: str | None = None) -> CanonicalTeam:
        if provider_id:
            found = self._by_provider_id.get((provider, str(provider_id)))
            if found is not None:
                return found
        if name:
            candidates = {row.canonical_id: row for row in self._by_name.get(normalized_name(name), [])}
            if len(candidates) == 1:
                return next(iter(candidates.values()))
            if len(candidates) > 1:
                raise IdentityError(f"ambiguous team identity: {name!r}")
        raise IdentityError(f"unknown team identity: provider={provider!r}, id={provider_id!r}, name={name!r}")

    def get(self, canonical_id: str) -> CanonicalTeam:
        try:
            return self._by_canonical[canonical_id]
        except KeyError as exc:
            raise IdentityError(f"unknown canonical ID: {canonical_id}") from exc
