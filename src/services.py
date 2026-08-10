import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from predictor_core.kernel.timeindex import parse_iso

from .data.ingestion import ConditionalDownloader, SnapshotStore
from .freeze import load_current_freeze
from .identity import IdentityRegistry
from .model import EloModel


@dataclass(frozen=True)
class PredictionRequest:
    team_a: str
    team_b: str
    format: str = "bo3"


class PredictionService:
    def __init__(
        self,
        snapshot_root: Path,
        *,
        project_root: Path = Path("."),
        max_age_hours: int = 192,
        model_factory: Callable[..., EloModel] = EloModel,
    ):
        self.snapshot_root = snapshot_root
        self.data_root = snapshot_root.parent
        self.project_root = project_root
        self.max_age_hours = max_age_hours
        self.model_factory = model_factory

    def predict(self, request: PredictionRequest) -> dict[str, Any]:
        freeze, artifacts = load_current_freeze(self.data_root, self.project_root)
        metadata = json.loads(artifacts["snapshot_metadata"].read_text(encoding="utf-8"))
        age_hours = (datetime.now(UTC) - parse_iso(metadata["retrieved_at"])).total_seconds() / 3600
        if age_hours < -(5 / 60) or age_hours > self.max_age_hours:
            raise ValueError(f"frozen snapshot is outside the freshness window ({age_hours:.1f}h)")
        registry = IdentityRegistry(artifacts["identity_canonical_teams"])
        team_a = registry.resolve(provider="request", name=request.team_a)
        team_b = registry.resolve(provider="request", name=request.team_b)
        if team_a.canonical_id == team_b.canonical_id:
            raise ValueError("a team cannot play against itself")
        result = self.model_factory(ratings_file=artifacts["ratings"]).predict_match(
            team_a.display_name, team_b.display_name, request.format
        )
        return {
            **result,
            "canonical_team_a_id": team_a.canonical_id,
            "canonical_team_b_id": team_b.canonical_id,
            "domain": "lol",
            "model_name": "elo-h1",
            "model_version": "h1-approved/1",
            "predicted_at": datetime.now(UTC).isoformat(),
            "data_as_of": metadata["observed_at"],
            "freeze_id": freeze["freeze_id"],
            "input_provenance": {
                "freeze_id": freeze["freeze_id"],
                "freeze_manifest_hash": freeze["manifest_hash"],
                "snapshot_hash": freeze["snapshot"]["payload_sha256"],
                "ratings_hash": freeze["artifacts"]["ratings"]["sha256"],
            },
            "scientific_status": "APPROVED_H1",
            "degraded": False,
            "degraded_reasons": [],
        }


class IngestionService:
    def __init__(self, store: SnapshotStore):
        self.store = store

    def ingest(self, url: str):
        return ConditionalDownloader(self.store).fetch(url)


class RatingsService:
    def __init__(self, model: EloModel | None = None):
        self.model = model or EloModel()

    def update(self, *args: Any, **kwargs: Any):
        return self.model.update_ratings(*args, **kwargs)


class SettlementService:
    def settle(self, prediction: dict[str, Any], result: int) -> dict[str, Any]:
        if prediction.get("state") != "PRE_EVENT" or result not in (0, 1):
            raise ValueError("invalid settlement")
        return {**prediction, "state": "MATURED", "result": result, "settled_at": datetime.now(UTC).isoformat()}
