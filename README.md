# lol-predictor

Current operational and scientific reconciliation: [`docs/OPERATING_STATE.md`](docs/OPERATING_STATE.md).

O refresh semanal usa o download oficial do Oracle's Elixir. Se o Google
Drive oficial estiver temporariamente limitado, uma segunda URL explicitamente
aprovada pode ser fornecida em `ORACLES_ELIXIR_<ANO>_URL`; o CSV só substitui
o cache após validação de tamanho, UTF-8 e colunas estruturais. Mirrors não
configurados nunca são usados silenciosamente. O bucket S3 publicado pela
própria API do Oracle's Elixir também é tentado, mas um arquivo com data máxima
anterior à do cache local é rejeitado para impedir redução silenciosa da amostra.

**Ingestão resiliente (2026-07-21):** o download agora usa ETag/Last-Modified,
retry limitado, validação de conteúdo e snapshots imutáveis em runtime. O
serving falha fechado quando não há snapshot publicado e com menos de 192 h;
não usa silenciosamente um CSV raw expirado. Consulte
[`docs/INGESTION_RESILIENCE.md`](docs/INGESTION_RESILIENCE.md) para o contrato,
tentativas históricas e runbook.

> **Status: Fase 1 CONCLUÍDA (2026-07-11).** Backtest prequential sobre
> 3.877 mapas do Oracle's Elixir: **H1 (Elo vencedor) COMPROVADA** (Brier
> 0,4432 vs banda 0,4612, acerto 64,6%, DM p=0,0006) e **H2 (abates por time)
> REFUTADA** — a média da liga vence; o serving de kills usa só ela. Elo
> vivido de 82 identidades canônicas materializado em `data/ratings.json`.
> **Sem apostas reais.** A Fase 1b agora possui fonte pública read-only de
> probabilidades negociadas (Polymarket); coleta e avaliação são apenas shadow.
> Relatório: `docs/RELATORIO_FASE1.md`. Não é ferramenta de investimento.
>
> **Hardening 2026-07-19/20**: auditoria hostil de identidade/lifecycle/ratings
> fechou 12 bugs/lacunas reais (empate/placar inválido em `update_ratings`, KeyError
> com `ratings_file` customizado, NaN/Inf em ratings, substring ambígua no
> `resolve_team`, `prediction_id` desconhecido na maturação, ausência de
> normalização Unicode NFC, colisão regional, timestamps, série incompleta e
> concorrência/atomicidade de ratings e lifecycle). Na época: 81 testes verdes
> só em `tests/test_hostile_audit.py` (suíte completa atual, verificada em
> CI: 148 testes verdes). Detalhe em `HANDOFF.md`.

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
uv run lol-predictor predict T1 Gen.G --format bo3
.venv\Scripts\python.exe -m src.predict T1 Gen.G --market kills --kills-line 26.5 --json
.venv\Scripts\python.exe -m src.predict "Bilibili Gaming" "G2 Esports" --format bo5

# Testes e CI
uv run pytest -v -W error
uv run ruff check src
uv run pyright

# Scheduler portátil e validado pelo predictor_ops
uv run lol-scheduler validate jobs.json
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
  config.py                 # load_config/load_teams/resolve_team
  model.py                  # EloModel (match/kills/update_ratings)
  predict.py                # CLI de serving + PredictionPoint + telemetria
  data/riot_provider.py     # stub (Riot API vs Oracle's Elixir — decisão da Fase 1)
data/teams_lol.json         # 30 times Tier 1 (LCK 10, LPL 10, LEC 6, LCS 4)
scripts/ci_check.py         # 3 barreiras: pytest, .ps1 ASCII, parse+smoke
tests/                      # suíte estrita: modelo, serving, lifecycle, refresh e higiene
```

`predictor-core`/`predictor-ops` não são vendorizados: são wheels externas resolvidas
via `[tool.uv.sources]` a partir das GitHub Releases de core-predictor/tools-predictor,
com hash fixado em `uv.lock`.

## Roadmap

| Fase | Escopo | Status |
|---|---|---|
| 0 | Esqueleto: estrutura, vendor, Elo + kills, serving, CI | ✅ |
| 1 | Histórico + backtest walk-forward H1 | ✅ |
| 2 | Governança, lifecycle e refresh observável | ✅; refresh natural de 20/07 ainda será observado |
| 3 | Mercado/shadow econômico | Fonte pública integrada; coleta prospectiva pronta, sem trading |

Coleta manual de uma cotação PRE_EVENT (arquivo ignorado pelo Git):

```powershell
python scripts/collect_polymarket_shadow.py "T1" "Gen.G"
```

A coleta exige moneyline exato, order book com bid/ask dos dois lados,
timestamp anterior ao jogo e identidade inequívoca. Polymarket é mercado de
previsão, não bookmaker; `decimal_a/b` são apenas `1/probabilidade`.

Operação prospectiva:

```powershell
python scripts/collect_polymarket_upcoming.py --horizon-hours 72
python scripts/market_shadow_status.py
powershell -ExecutionPolicy Bypass -File scripts/install_market_shadow_task.ps1 -RunNow
```

A tarefa `lol-market-shadow` coleta a cada 30 minutos. O pré-registro
`h4-lol-market-shadow-prospectivo` exclui probes anteriores a 20/07 06:20:41Z,
exige 50 partidas maturadas, 30 dias, 3 competições e IC bootstrap antes de
qualquer conclusão. Não existe caminho de aposta real.

A coorte H4 auditável usa `data/shadow/h4_signals.jsonl`, não promove cotações
legadas sem competição e provenance completas, e exige resultado oficial antes
de contar maturação. Rode `python scripts/market_shadow_status.py`; o avaliador
`scripts/evaluate_h4_gate.py` só aceita `READY_FOR_EVALUATION`. Mesmo o máximo
veredito (`GATE_PASSED_FOR_PROSPECTIVE_SHADOW`) não habilita dinheiro real.

**Encerramento H4 V2 (2026-07-23):** a decisão humana encerrou a coorte antes
da amostra mínima, sem aprovação ou refutação. O registro versionado
`data/h4_v2_closure.json` fixa `CLOSED_BY_HUMAN_DECISION` e `NO_GO`; coleta e
avaliação falham fechadas até existir uma nova decisão humana auditável.

**Collection-only (2026-07-23):** `lol-archival-collection` arquiva somente
dados esportivos oficiais em storage separado, sem reabrir H4 ou produzir gate.
Contrato e operação em `docs/COLLECTION_ONLY_HANDOFF.md`.

Backtest separado H4‑R (não conta no gate prospectivo):

```powershell
python scripts/backtest_market_retrospective.py `
  --output data/reports/h4r_polymarket_retrospective_2026-07-20.json
```

Resultado em 177 partidas/28 competições: Brier Elo 0,4320 contra mercado
0,4023; ROI shadow +10,57% em 116 sinais. Os dois IC95% cruzam zero, portanto
o veredito retrospectivo é `INCONCLUSIVO` e a H4 prospectiva continua intacta.
