"""Config e times — identidade do domínio LoL."""
import pytest

from src.config import load_config, load_teams, resolve_team


def test_config_dominio_lol():
    cfg = load_config()
    assert cfg["game"] == "League of Legends"
    assert cfg["default_format"] == "bo3"
    assert cfg["default_kills_line"] == 24.5
    assert cfg["k_factor_base"] == 32
    assert cfg["bankroll"] == 1000 and cfg["stake_unit"] == 50


def test_30_times_unicos_ligas_tier1():
    teams = load_teams()
    assert len(teams) == 30
    assert len({t["name"] for t in teams}) == 30
    ligas = {t["region"] for t in teams}
    assert ligas == {"LCK", "LPL", "LEC", "LCS"}
    # bandas por liga (âncora do GPR): melhor LCK > melhor LEC > melhor LCS
    top = {liga: max(t["initial_elo"] for t in teams if t["region"] == liga)
           for liga in ligas}
    assert top["LCK"] > top["LEC"] > top["LCS"]


def test_resolve_team_substring_e_erro():
    assert resolve_team("t1")["region"] == "LCK"
    assert resolve_team("Bilibili")["name"] == "Bilibili Gaming"
    assert resolve_team("Hanwha")["initial_elo"] == 1650
    with pytest.raises(ValueError):
        resolve_team("Time Fantasma")
