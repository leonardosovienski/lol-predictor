from importlib.metadata import entry_points, version
from pathlib import Path
import predictor_core
import predictor_ops

def test_shared_dependencies_are_external_wheels():
    assert version("predictor-core") == "2.1.0"
    assert version("predictor-ops") == "2.0.1"
    assert "site-packages" in str(Path(predictor_core.__file__).resolve())
    assert "site-packages" in str(Path(predictor_ops.__file__).resolve())

def test_plugin_entry_point_is_loadable():
    plugin = next(ep for ep in entry_points(group="predictor.plugins") if ep.name == "lol").load()
    assert plugin().health()["domain"] == "lol"
