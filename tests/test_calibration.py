"""Platt (N+1) no LoL — módulo compartilhado; REFUTADA em 2026-07-11, então
o serving DEVE seguir cru até prova em contrário."""
import pytest

from src.calibration import PlattCalibrator
from src.model import EloModel


def test_identidade_sem_fit():
    assert PlattCalibrator().apply(0.42) == pytest.approx(0.42, abs=1e-9)


def test_serving_cru_enquanto_refutada(tmp_path):
    """h3-lol-elo-platt REFUTADA (DM p=0.36): calibration_platt.json NÃO
    pode existir — o serving usa a prob crua do Elo."""
    m = EloModel(ratings_file=tmp_path / "r.json")
    assert m.platt is None, (
        "calibration_platt.json presente com a trial REFUTADA — remova ou "
        "re-execute scripts/backtest_calibracao.py com veredito novo")
    r = m.predict_match("T1", "Gen.G", "bo3")
    assert r["model"] == "elo-fase0"
    assert r["p_map_a"] == r["p_map_a_raw"]
