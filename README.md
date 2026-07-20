# lol-predictor

> **Status: Fase 1 CONCLUÍDA (2026-07-11).** Backtest prequential sobre
> 3.877 mapas do Oracle's Elixir: **H1 (Elo vencedor) COMPROVADA** (Brier
> 0,4432 vs banda 0,4612, acerto 64,6%, DM p=0,0006) e **H2 (abates por time)
> REFUTADA** — a média da liga vence; o serving de kills usa só ela. Elo
> vivido de 82 identidades canônicas materializado em `data/ratings.json`.
> **Sem odds, sem
> apostas** — métrica é probabilística (Fase 1b exigiria fonte de odds).
> Relatório: `docs/RELATORIO_FASE1.md`. Não é ferramenta de investimento.
>
> **Hardening 2026-07-19/20**: auditoria hostil de identidade/lifecycle/ratings
> fechou 12 bugs/lacunas reais (empate/placar inválido em `update_ratings`, KeyError
> com `ratings_file` customizado, NaN/Inf em ratings, substring ambígua no
> `resolve_team`, `prediction_id` desconhecido na maturação, ausência de
> normalização Unicode NFC, colisão regional, timestamps, série incompleta e
> concorrência/atomicidade de ratings e lifecycle). Suíte: 71
> testes verdes (`tests/test_hostile_audit.py`). Detalhe em `HANDOFF.md`.

Laboratório de previsão de **partidas de League of Legends** (vencedor da
série e total de abates), sétimo consumidor do ecossistema `predictor_core`.
100% local (Python 3.13 + arquivos), sem cloud.

## Modelo (Fase 0)

**Vencedor**: Elo por MAPA (logística clássica /400) + combinatória exata da
série (BO1/BO3/BO5) → prob de cada time, prob da zebra, mapas esperados.
K por formato: BO1=32, BO3=40, BO5=48; `update_ratings` conserva soma zero e
persiste em `data/ratings.json`.

**Total de abates**: H2 por time foi refutada e está bloqueada no serving.
O caminho legado de total usa somente o baseline agregado declarado no config;
`team_stats.json` não é consumido. Não faz parte das previsões EWC.

**Calibração**: Platt H3 foi refutada e está bloqueada no serving mesmo se um
artefato experimental reaparecer. A probabilidade canônica é o Elo H1 cru.

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
.venv\Scripts\python.exe -m pytest tests/ -v -W error
.venv\Scripts\python.exe scripts/ci_check.py

# Scheduler semanal + prova inofensiva do caminho Windows Scheduler
powershell -ExecutionPolicy Bypass -File scripts\install_weekly_task.ps1 -Verify
```

Previsões oficiais de evento usam horário explícito, são bloqueadas a partir de
`scheduled_at` e percorrem PRE_EVENT → MATURED com resultado, acerto e Brier.
O ledger `data/predictions.jsonl` é append-only e versionado para preservar a
prova forward. Previsões ad hoc do CLI vão para `data/predictions_adhoc.jsonl`
(gitignored) e nunca tocam o ledger oficial.

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
tests/                      # suíte estrita: modelo, serving, lifecycle, refresh e higiene
vendor/predictor_core/      # v1.3.1 via sync_core (NÃO editar à mão)
```

## Roadmap

| Fase | Escopo | Status |
|---|---|---|
| 0 | Esqueleto: estrutura, vendor, Elo + kills, serving, CI | ✅ |
| 1 | Histórico + backtest walk-forward H1 | ✅ |
| 2 | Governança, lifecycle e refresh observável | ✅; refresh natural de 20/07 ainda será observado |
| 3 | Odds/shadow econômico | Não autorizado |
