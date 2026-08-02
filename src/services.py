from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .data.ingestion import ConditionalDownloader, SnapshotStore, assert_fresh_snapshot
from .model import EloModel


@dataclass(frozen=True)
class PredictionRequest:
    team_a: str
    team_b: str
    format: str = "bo3"


class PredictionService:
    def __init__(
        self, snapshot_root: Path, *, max_age_hours: int = 192, model_factory: Callable[[], EloModel] = EloModel
    ):
        self.snapshot_root, self.max_age_hours, self.model_factory = snapshot_root, max_age_hours, model_factory

    def predict(self, request: PredictionRequest) -> dict[str, Any]:
        snapshot = assert_fresh_snapshot(self.snapshot_root, max_age_hours=self.max_age_hours)
        result = self.model_factory().predict_match(request.team_a, request.team_b, request.format)
        return {
            **result,
            "domain": "lol",
            "model_name": "elo-h1",
            "model_version": "h1-approved/1",
            "predicted_at": datetime.now(UTC).isoformat(),
            "data_as_of": snapshot["observed_at"],
            "input_provenance": {"snapshot_hash": snapshot["hash"]},
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
