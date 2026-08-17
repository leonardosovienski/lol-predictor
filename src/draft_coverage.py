"""Read-only coverage audit for the pre/post-draft economic hypothesis."""

from __future__ import annotations

import json
import os
import tempfile
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from predictor_core.data.contracts import DataUnavailableError

from .data.pandascore_provider import PandaScoreProvider
from .data.polymarket_provider import PolymarketProvider
from .identity import IdentityRegistry

SCHEMA = "lol-draft-coverage-audit/1.0"


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, allow_nan=False, sort_keys=True, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def identity_coverage(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    teams = payload.get("teams")
    if not isinstance(teams, list):
        raise ValueError("canonical_teams.json inválido")
    providers = ("oracles_elixir", "pandascore", "polymarket", "grid")
    counts = {
        provider: sum(bool(((team.get("providers") or {}).get(provider) or {}).get("ids")) for team in teams)
        for provider in providers
    }
    return {"canonical_teams": len(teams), "teams_with_provider_id": counts}


def _registry_resolver(path: Path) -> Callable[[str, dict[str, str]], str]:
    registry = IdentityRegistry(path)

    def resolve(name: str, aliases: dict[str, str]) -> str:
        return registry.resolve(provider="registered_name", name=aliases.get(name, name)).display_name

    return resolve


def _key(row: dict[str, Any]) -> tuple[str, str]:
    return tuple(sorted((row["canonical_team_a"], row["canonical_team_b"])))  # type: ignore[return-value]


def audit_draft_coverage(
    *,
    horizon_hours: int = 168,
    observed_at: datetime | None = None,
    polymarket: Any | None = None,
    pandascore: Any | None = None,
    aliases_path: Path | None = None,
    registry_path: Path | None = None,
    resolver: Callable[[str, dict[str, str]], str] | None = None,
) -> dict[str, Any]:
    """Measure source overlap without turning absence/failure into zero coverage."""
    if not 1 <= horizon_hours <= 168:
        raise ValueError("horizon_hours deve estar entre 1 e 168")
    observed = (observed_at or datetime.now(UTC)).astimezone(UTC)
    if aliases_path is None or registry_path is None:
        raise ValueError("aliases_path e registry_path são obrigatórios")
    aliases_doc = json.loads(aliases_path.read_text(encoding="utf-8"))
    aliases = aliases_doc.get("aliases") or {}
    registry = identity_coverage(registry_path)
    resolve_name = resolver or _registry_resolver(registry_path)
    sources: dict[str, Any] = {}
    normalized: dict[str, list[dict[str, Any]]] = {"polymarket": [], "pandascore": []}

    try:
        market_rows = (polymarket or PolymarketProvider()).list_upcoming_matches(
            horizon_hours=horizon_hours, now=observed
        )
        rejected = Counter()
        for row in market_rows:
            try:
                normalized["polymarket"].append(
                    {
                        **row,
                        "canonical_team_a": resolve_name(row["team_a"], aliases),
                        "canonical_team_b": resolve_name(row["team_b"], aliases),
                    }
                )
            except ValueError:
                rejected["identity"] += 1
        sources["polymarket"] = {
            "status": "AVAILABLE",
            "events": len(market_rows),
            "canonical_events": len(normalized["polymarket"]),
            "rejected": dict(rejected),
            "capabilities": ["fixture", "series_moneyline", "point_in_time_book", "spread", "depth"],
        }
    except DataUnavailableError as exc:
        sources["polymarket"] = {"status": "UNAVAILABLE", "reason": str(exc), "events": None}

    panda = pandascore or PandaScoreProvider()
    if not getattr(panda, "token", None):
        sources["pandascore"] = {
            "status": "BLOCKED_CREDENTIAL",
            "reason": "PANDASCORE_TOKEN ausente",
            "events": None,
            "capabilities": ["fixture", "series_result"],
            "unproven_capabilities": ["confirmed_roster", "substitutes", "patch", "draft_timeline"],
        }
    else:
        try:
            panda_rows = panda.list_upcoming(observed_at=observed)
            rejected = Counter()
            contexts = Counter()
            for row in panda_rows:
                try:
                    normalized["pandascore"].append(
                        {
                            **row,
                            "canonical_team_a": resolve_name(row["team_a"], {}),
                            "canonical_team_b": resolve_name(row["team_b"], {}),
                        }
                    )
                except ValueError:
                    rejected["identity"] += 1
                if hasattr(panda, "fetch_match_context"):
                    try:
                        context = panda.fetch_match_context(row["source_event_id"], observed_at=observed)
                        contexts["audited"] += 1
                        contexts["full_roster"] += int(context["full_five_player_rosters"] == 2)
                        contexts["substitutes"] += int(bool(context["substitutes_published"]))
                        contexts["patch"] += int(bool(context["patch"]))
                        contexts["draft_fields"] += int(bool(context["draft_fields_available"]))
                        contexts["draft_timeline"] += int(bool(context["draft_timeline_available"]))
                    except DataUnavailableError:
                        contexts["unavailable"] += 1
            sources["pandascore"] = {
                "status": "AVAILABLE",
                "events": len(panda_rows),
                "canonical_events": len(normalized["pandascore"]),
                "rejected": dict(rejected),
                "context_coverage": dict(contexts),
                "capabilities": ["fixture", "series_result"],
                "unproven_capabilities": ["confirmed_roster", "substitutes", "patch", "draft_timeline"],
            }
        except DataUnavailableError as exc:
            sources["pandascore"] = {"status": "UNAVAILABLE", "reason": str(exc), "events": None}

    panda_keys = {_key(row) for row in normalized["pandascore"]}
    overlap = [row for row in normalized["polymarket"] if _key(row) in panda_keys]
    blockers = []
    if sources["polymarket"]["status"] != "AVAILABLE":
        blockers.append("POLYMARKET_SOURCE")
    if sources["pandascore"]["status"] != "AVAILABLE":
        blockers.append("PANDASCORE_SOURCE")
    if sources["polymarket"]["status"] == sources["pandascore"]["status"] == "AVAILABLE" and not overlap:
        blockers.append("NO_CANONICAL_OVERLAP")
    blockers.extend(["CONFIRMED_ROSTER_UNPROVEN", "DRAFT_TIMELINE_UNPROVEN", "MAP_MARKET_UNPROVEN"])
    return {
        "schema_version": SCHEMA,
        "mode": "SHADOW",
        "capital_authorized": False,
        "observed_at": observed.isoformat(),
        "horizon_hours": horizon_hours,
        "identity": registry,
        "sources": sources,
        "canonical_overlap_events": len(overlap),
        "blockers": blockers,
        "continuity_decision": "BLOCKED" if blockers else "CONTINUE_SHADOW",
    }


def publish_audit(path: Path, **kwargs: Any) -> dict[str, Any]:
    report = audit_draft_coverage(**kwargs)
    _atomic_json(path, report)
    return report
