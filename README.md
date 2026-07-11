# lol-predictor

> **Status: Fase 0 — esqueleto funcional (2026-07-10).** Modelo Elo + totais
> de abates rodando, CI verde, vendor no predictor_core v1.1.0. **Backtest e
> operação real ainda NÃO existem** — nenhuma previsão daqui tem edge
> demonstrado. Não é ferramenta de investimento.

Laboratório de previsão de **partidas de League of Legends** (vencedor da
série e total de abates), sétimo consumidor do ecossistema `predictor_core`.
100% local (Python 3.13 + arquivos), sem cloud.

## Modelo (Fase 0)

**Vencedor**: Elo por MAPA (logística clássica /400) + combinatória exata da
série (BO1/BO3/BO5) → prob de cada time, prob da zebra, mapas esperados.
K por formato: BO1=32, BO3=40, BO5=48; `update_ratings` conserva soma zero e
persiste em `data/ratings.json`.

**Total de abates**: total por mapa ≈ Normal(kpg_a + kpg_b, σ) — mesmo padrão
do nba-predictor. Fase 0 usa a média da liga (28 abates/mapa, placeholder
declarado no config); `data/team_stats.json` diferencia por time quando a
Fase 1 materializar. Linha default 24.5.

**Semente do Elo**: bandas por liga ancoradas nos **Power Scores regionais
oficiais do Global Power Rankings split-2 2026** (LCK 1425 > LPL 1419 >
LEC 1297 > LCS 1081) + sinais editoriais da era (HLE/Gen.G/T1 no topo da
LCK; BLG/JDG na LPL; G2 top-3 global). A ordem intra-liga é **estimativa
declarada** — não existe ranking mundial oficial de 30 times; a Fase 1
recalibra com resultados reais (Oracle's Elixir / Riot API).

Extensões da Fase 1+: draft/counter-picks, early game (first blood/tower),
desempenho por patch.

## Uso

```bash
.venv\Scripts\python.exe -m src.predict T1 Gen.G --format bo3
.venv\Scripts\python.exe -m src.predict T1 Gen.G --market kills --kills-line 26.5 --json
.venv\Scripts\python.exe -m src.predict "Bilibili Gaming" "G2 Esports" --format bo5

# Testes e CI
.venv\Scripts\python.exe -m pytest tests/ -v
.venv\Scripts\python.exe scripts/ci_check.py
```

Toda previsão é carimbada com `PredictionPoint` do core (matures_at = início
+ 1h/2h30/4h por formato), registrada em `data/predictions.jsonl`
(append-only, override por env) e emitida na telemetria (domínio `lol`).

## Estrutura

```
config.yaml                 # game, formato/linha default, K base, placeholders
src/
  config.py                 # load_config/load_teams/resolve_team (+vendor no path)
  model.py                  # EloModel (match/kills/update_ratings)
  predict.py                # CLI de serving + PredictionPoint + telemetria
  data/riot_provider.py     # stub (Riot API vs Oracle's Elixir — decisão da Fase 1)
data/teams_lol.json         # 30 times Tier 1 (LCK 10, LPL 10, LEC 6, LCS 4)
scripts/ci_check.py         # 3 barreiras: pytest, .ps1 ASCII, parse+smoke
tests/                      # 25 testes (modelo, serving, config, core, higiene)
vendor/predictor_core/      # v1.1.0 via sync_core (NÃO editar à mão)
```

## Roadmap

| Fase | Escopo | Status |
|---|---|---|
| 0 | Esqueleto: estrutura, vendor, Elo + kills, serving, CI | ✅ |
| 1 | Histórico LCK/LPL/LEC/LCS (Oracle's Elixir) + backtest walk-forward | ⏳ prompt separado |
| 2 | Governança: harness + TrialRegistry + GO/NO-GO (padrão da plataforma) | ⏳ |
| 3 | Operação: odds, bet_log, settle | ⏳ (só após GO) |
