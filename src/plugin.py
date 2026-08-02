from importlib.metadata import version
from typing import Any

from .services import PredictionRequest, PredictionService
from .settings import Settings


class LolPredictorPlugin:
    domain = "lol"
    capabilities = ("prediction", "collection", "settlement", "health")

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or Settings()

    def predict(self, request: PredictionRequest) -> dict[str, Any]:
        return PredictionService(
            self.settings.data_root / "ingestion", max_age_hours=self.settings.max_snapshot_staleness_hours
        ).predict(request)

    def health(self) -> dict[str, Any]:
        providers = {
            "oracles_elixir": {"enabled": True, "capabilities": ["historical_games", "conditional_download"]},
            "polymarket": {"enabled": True, "capabilities": ["read_only_market", "shadow"]},
        }
        return {
            "status": "SUCCEEDED",
            "domain": self.domain,
            "version": version("lol-predictor"),
            "providers": providers,
        }


plugin = LolPredictorPlugin
