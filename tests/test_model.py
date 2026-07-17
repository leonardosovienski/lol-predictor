"""Modelo Elo + totais de abates — Fase 0. Ratings em tmp_path."""
import pytest

from src.model import EloModel, series_probs


@pytest.fixture
def model(tmp_path):
    return EloModel(ratings_file=tmp_path / "ratings.json")


def test_predict_match_t1_geng(model):
    r = model.predict_match("T1", "Gen.G", "bo3")
    assert abs(r["prob_team_a"] + r["prob_team_b"] - 1.0) < 1e-6
    # Gen.G (1630) é favorito sobre T1 (1620) na semente atual
    fav_prob = max(r["prob_team_a"], r["prob_team_b"])
    assert fav_prob > 0.5
    assert r["prob_underdog"] == min(r["prob_team_a"], r["prob_team_b"])
    assert abs(sum(r["score_probs"].values()) - 1.0) < 1e-6


def test_series_probs_fechadas_e_formatos(model):
    d = series_probs(0.5, "bo3")
    assert abs(sum(d.values()) - 1.0) < 1e-9
    p1 = model.predict_match("Hanwha Life Esports", "100 Thieves", "bo1")["prob_team_a"]
    p5 = model.predict_match("Hanwha Life Esports", "100 Thieves", "bo5")["prob_team_a"]
    assert p1 < p5           # série longa favorece o favorito
    with pytest.raises(ValueError):
        series_probs(0.5, "bo7")


def test_kills_total_intervalo_realista(model):
    k = model.predict_kills_total("T1", "Gen.G")
    assert 15 <= k["total_projetado"] <= 40
    assert abs(k["over_prob"] + k["under_prob"] - 1.0) < 1e-6
    assert k["line"] == 24.5          # default do config


def test_kills_total_linha_move_probabilidade(model):
    baixa = model.predict_kills_total("T1", "Gen.G", line=20.5)
    alta = model.predict_kills_total("T1", "Gen.G", line=32.5)
    assert baixa["over_prob"] > alta["over_prob"]


def test_kills_total_nao_reativa_stats_por_time_refutadas(model):
    k = model.predict_kills_total("T1", "Gen.G")
    assert k["total_projetado"] == 28.0
    assert k["kpg_a"] == 14.0 and k["kpg_b"] == 14.0


def test_update_ratings_vencedor_sobe_soma_zero(model):
    antes_a, antes_b = model.ratings["T1"], model.ratings["Gen.G"]
    out = model.update_ratings("T1", "Gen.G", 2, 1)
    assert out["format"] == "bo3" and out["k"] == 40
    assert model.ratings["T1"] > antes_a
    assert model.ratings["Gen.G"] < antes_b
    assert abs((model.ratings["T1"] + model.ratings["Gen.G"])
               - (antes_a + antes_b)) < 1e-9


def test_k_por_formato_e_persistencia(model):
    assert model.update_ratings("Fnatic", "SK Gaming", 1, 0)["k"] == 32
    assert model.update_ratings("Fnatic", "SK Gaming", 3, 2)["k"] == 48
    recarregado = EloModel(ratings_file=model.path)
    assert recarregado.ratings["Fnatic"] == model.ratings["Fnatic"]


def test_update_formato_explicito_vence_inferencia(model):
    # 3-0 em BO5 seria inferido como BO3 (K=40); explícito corrige pra K=48
    assert model.update_ratings("T1", "Gen.G", 3, 0)["k"] == 40
    assert model.update_ratings("T1", "Gen.G", 3, 0, format="bo5")["k"] == 48
    with pytest.raises(ValueError):
        model.update_ratings("T1", "Gen.G", 2, 0, format="bo1")
    with pytest.raises(ValueError):
        model.update_ratings("T1", "Gen.G", 2, 1, format="bo7")


def test_update_persiste_so_ratings_vividos(tmp_path):
    ratings = tmp_path / "ratings.json"
    ratings.write_text('{"T1": 1700.0}', encoding="utf-8")
    model = EloModel(ratings_file=ratings)
    model.update_ratings("T1", "Gen.G", 2, 0)
    import json
    persisted = json.loads(ratings.read_text(encoding="utf-8"))
    # só o vivido (T1) e os atualizados (T1, Gen.G) — nenhuma semente intacta
    assert set(persisted) == {"T1", "Gen.G"}


def test_erros(model):
    with pytest.raises(ValueError):
        model.predict_match("Time Fantasma", "T1")
    with pytest.raises(ValueError):
        model.predict_match("T1", "t1")          # mesmo time
    with pytest.raises(ValueError):
        model.predict_match("T1", "Gen.G", "bo7")


def test_rating_vivido_normaliza_capitalizacao_da_semente(tmp_path):
    ratings = tmp_path / "ratings.json"
    ratings.write_text('{"BNK FEARX": 1460.5, "EDward Gaming": 1386.6}',
                       encoding="utf-8")
    model = EloModel(ratings_file=ratings)
    assert model.ratings["BNK FearX"] == 1460.5
    assert model.ratings["Edward Gaming"] == 1386.6
    assert "BNK FEARX" not in model.ratings and "EDward Gaming" not in model.ratings
