from importlib.metadata import version
from typing import Any

from .services import PredictionRequest, PredictionService
from .settings import Settings


class LolPredictorPlugin:
    domain = "lol"

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or Settings()

    def capabilities(self) -> dict[str, Any]:
        """Return the aggregator-facing capability manifest.

        Keep the domain's richer operational metadata under ``extra`` while
        exposing the canonical boolean fields expected by the ecosystem
        gateway.  This is deliberately a plain mapping so the domain remains
        independent from the aggregator package.
        """
        return {
            "domain": self.domain,
            "supports_prediction": True,
            "supports_settlement": True,
            "supports_collection": True,
            "scientific_status": "APPROVED_H1_SHADOW_MARKET",
            "extra": {
                "market_shadow": True,
                "trading": False,
                "providers": ["oracles_elixir", "polymarket"],
            },
        }

    @staticmethod
    def _request(request: PredictionRequest | dict[str, Any]) -> PredictionRequest:
        if isinstance(request, PredictionRequest):
            return request
        if not isinstance(request, dict):
            raise TypeError("prediction request must be a mapping")
        try:
            return PredictionRequest(
                team_a=str(request["team_a"]),
                team_b=str(request["team_b"]),
                format=str(request.get("format", "bo3")),
            )
        except KeyError as exc:
            raise ValueError(f"missing prediction field: {exc.args[0]}") from exc

    def predict(self, request: PredictionRequest | dict[str, Any]) -> dict[str, Any]:
        request = self._request(request)
        return PredictionService(
            self.settings.data_root / "ingestion",
            project_root=self.settings.project_root,
            max_age_hours=self.settings.max_snapshot_staleness_hours,
        ).predict(request)

    def health(self) -> dict[str, Any]:
        from .operations import health

        providers = {
            "oracles_elixir": {"enabled": True, "capabilities": ["historical_games", "conditional_download"]},
            "polymarket": {"enabled": True, "capabilities": ["read_only_market", "shadow"]},
        }
        deep = health(self.settings)
        return {
            **deep,
            "domain": self.domain,
            "version": version("lol-predictor"),
            "details": {"providers": providers},
        }


plugin = LolPredictorPlugin
