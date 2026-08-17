from importlib.metadata import entry_points, version
from pathlib import Path

import predictor_core
import predictor_ops


def test_shared_dependencies_are_external_wheels():
    assert version("predictor-core") == "2.3.0"
    assert version("predictor-ops") == "3.1.0"
    assert "site-packages" in str(Path(predictor_core.__file__).resolve())
    assert "site-packages" in str(Path(predictor_ops.__file__).resolve())


def test_plugin_entry_point_is_loadable():
    plugin = next(ep for ep in entry_points(group="predictor.plugins") if ep.name == "lol").load()
    instance = plugin()
    assert instance.health()["domain"] == "lol"
    assert callable(instance.capabilities)
    assert instance.capabilities()["supports_prediction"] is True


def test_plugin_accepts_gateway_wire_request(monkeypatch, tmp_path):
    from src.plugin import LolPredictorPlugin

    plugin = LolPredictorPlugin()
    monkeypatch.setattr(
        "src.plugin.PredictionService.predict",
        lambda _self, request: {"team_a": request.team_a, "team_b": request.team_b, "format": request.format},
    )
    monkeypatch.setattr("src.plugin.Settings.data_root", tmp_path, raising=False)

    result = plugin.predict({"team_a": "T1", "team_b": "Gen.G", "format": "bo3"})

    assert result == {"team_a": "T1", "team_b": "Gen.G", "format": "bo3"}
