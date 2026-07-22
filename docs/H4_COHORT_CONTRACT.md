# Contrato H4 prospectivo

## PAST_ATTEMPT_LEDGER

| ID | Tentativa | Resultado | Estado |
|---|---|---|---|
| H4-01 | Oracle com fallback/rate-limit, snapshots e frescor | dados de ratings locais resilientes; não prova mercado | WORKED |
| H4-02 | Polymarket read-only com aliases e cutoff | coleta PRE_EVENT funciona | WORKED |
| H4-03 | Quotes legados como coorte H4 | sem competição, evento canônico e provenance completos | REJECTED |
| H4-04 | Status por horário de início | confundia evento passado com resultado maturado | FAILED |
| H4-05 | `market_gate.json` manual / `betting.py` | não havia avaliador e não pode autorizar dinheiro | REJECTED |
| H4-06 | Sinal versionado + resultado oficial + bootstrap | implementado nesta rodada | WORKED |

## EXPERIMENT_LEDGER

| ID | Hipótese e teste | Resultado | Decisão |
|---|---|---|---|
| EXP-H4-01 | 49/50, 29/30 dias, 2/3 competições | estados de espera distintos | manter gates |
| EXP-H4-02 | resultado ausente, provenance/snapshot/schema inválidos | `DATA_QUALITY_BLOCKED` | falhar fechado |
| EXP-H4-03 | 50 eventos, 3 competições e 30 dias | bootstrap determinístico e escrita atômica | aceitar avaliador |

`data/shadow/h4_signals.jsonl` é a coorte prospectiva. Um sinal exige evento e
equipes canônicos, competição explícita, commit, hash do snapshot, fonte,
horários disponíveis/preditos/início, probabilidades, odds e provenance hash.
Ausência de campo, schema drift, duplicidade, mudança de modelo, snapshot
inválido, lookahead ou evento sem resultado oficial bloqueia a qualidade.

O status só fica `READY_FOR_EVALUATION` com 50 eventos liquidados, 30 dias,
30 sinais e 3 competições. O avaliador calcula Brier, diferença pareada,
log-loss, calibração, ROI, IC bootstrap por evento, HHI, cobertura e drawdown;
publica `lol-h4-market-gate/1.0` com hashes e critérios.

Use `settle_h4_signals.py` com resultados oficiais (`canonical_event_id`,
`result`, `result_available_at`, `source=oracle-elixir|riot-esports`). Previsões e proveniência capturadas
nunca são alteradas. `GATE_PASSED_FOR_PROSPECTIVE_SHADOW` não autoriza dinheiro.
