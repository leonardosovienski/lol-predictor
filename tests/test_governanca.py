import json

from scripts import governanca                                        # noqa: E402
from predictor_core.measurement.trials import register_trial          # noqa: E402
# ^ precisa vir depois de `scripts.governanca`, que insere vendor/ no sys.path

_H1_PARAMS = {"model": "elo-mapa", "k": 32, "seed": "bandas-gpr-2026",
              "default_seed_elo": 1400, "burnin_days": 90,
              "min_team_games": 10,
              "baseline": "elo-semente-congelado (banda regional)",
              "leagues": ["LCK", "LPL", "LEC", "LCS", "LTA N", "LTA S",
                          "LTA", "MSI", "WLDs", "FST", "EWC"],
              "period": "2025-01..2026-07"}
_H1_TEST_PERIOD = ["2025-01-12", "2026-07-10"]
_H1_PREREGISTRO = ("H1-LOL: Elo por mapa (prequential, prever-antes-de-atualizar) "
                    "prevê o vencedor melhor que a banda regional congelada. "
                    "COMPROVADA = Brier menor E Diebold-Mariano p<0.05 sobre "
                    "log-loss. Métrica probabilística (sem odds na Fase 1a).")
_H2_PARAMS = {"model": "normal-kills", "media": "time expanding (últimos 40)",
              "sigma": "por liga expanding", "linhas": [24.5, 27.5, 30.5],
              "baseline": "média/sigma da liga pura",
              "min_league_games": 30, "period": "2025-01..2026-07"}
_H2_PREREGISTRO = ("H2-LOL: Normal de abates com médias POR TIME bate a média da "
                    "liga pura. COMPROVADA = Brier menor com DM p<0.05 em >=2 das "
                    "3 linhas.")


def _seed_h1_e_h2_ja_registradas(trials_path, notes_h1):
    """Escreve h1/h2 já registradas (mesmos params/test_period que
    governanca.py usaria) — é o estado real de qualquer trials.json de
    produção depois da primeira rodada: reexecutar governanca.py sempre bate
    no caminho de UPDATE (params iguais) para as duas, nunca no de trial
    nova, então não precisa (nem pode) reusar o atestado de controle
    positivo da rodada anterior."""
    register_trial("h1-lol-elo-mapa-prequential", params=_H1_PARAMS,
                    sharpe=None, notes=notes_h1, path=trials_path,
                    test_period=_H1_TEST_PERIOD, power_attestation=False)
    register_trial("h2-lol-kills-normal-por-liga", params=_H2_PARAMS,
                    sharpe=None, notes=_H2_PREREGISTRO, path=trials_path,
                    test_period=_H1_TEST_PERIOD, power_attestation=False)


def test_rerodar_governanca_preserva_resultado_ja_anexado(tmp_path, monkeypatch):
    """Regressão 2026-08-01: register_trial reescreve `notes` inteira (não
    faz merge) — rodar governanca.py de novo depois que um backtest anexou
    "RESULTADO ..." às notes de h1/h2 revertia para o texto curto de
    pré-registro e apagava o resultado, sem erro nem aviso."""
    trials_path = tmp_path / "trials.json"
    resultado = _H1_PREREGISTRO + " | RESULTADO 2026-07-11: COMPROVADA — n=3053."
    _seed_h1_e_h2_ja_registradas(trials_path, resultado)

    monkeypatch.setattr(governanca, "TRIALS", trials_path)
    governanca.main()  # ex.: só para renovar o atestado, que expira em 7 dias

    after = json.loads(trials_path.read_text(encoding="utf-8"))
    h1_depois = next(t for t in after if t["name"] == "h1-lol-elo-mapa-prequential")
    assert h1_depois["notes"] == resultado


def test_primeiro_registro_sem_trial_previa_usa_o_texto_de_pre_registro():
    from predictor_core.measurement.trials import TrialRegistry
    reg = TrialRegistry.__new__(TrialRegistry)  # sem arquivo: load() = []
    reg.path = None
    reg.load = lambda: []
    texto = governanca._preregistration_notes(reg, "h1-lol-elo-mapa-prequential",
                                                _H1_PREREGISTRO)
    assert texto == _H1_PREREGISTRO


def test_registro_existente_ignora_o_default_e_preserva_o_que_esta_no_arquivo():
    from predictor_core.measurement.trials import TrialRegistry
    reg = TrialRegistry.__new__(TrialRegistry)
    reg.load = lambda: [{"name": "h1-lol-elo-mapa-prequential",
                          "notes": "texto real já com RESULTADO"}]
    texto = governanca._preregistration_notes(reg, "h1-lol-elo-mapa-prequential",
                                                "texto curto de pré-registro")
    assert texto == "texto real já com RESULTADO"
