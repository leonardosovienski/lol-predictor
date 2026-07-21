# Ingestão resiliente do Oracle's Elixir

## Decisão operacional

O refresh é semanal (segunda, 08:30 BRT). A janela máxima de frescor é **192
horas**: sete dias do ciclo mais 24 horas para indisponibilidade operacional.
Ela é configurada em `config.yaml`. Sem um snapshot publicado, íntegro e dentro
dessa janela, `python -m src.predict` falha fechado. O runner de replay por
fixture continua deliberadamente separado: ele usa o snapshot histórico que o
próprio fixture declara e não é serving atual.

Uma amostra mínima fica em `docs/ingestion_config.example.yaml`; URLs de
contingência continuam exclusivamente em `ORACLES_ELIXIR_<ANO>_URL`.

Fluxo: origem oficial -> requisição condicional -> arquivo temporário ->
validação -> snapshot imutável -> ponteiro atômico -> ingest/serving.

`data/ingestion/` é runtime ignorado pelo Git. Cada snapshot contém
`payload.csv` e `metadata.json`; `current.json` é o único ponteiro mutável. A
troca do ponteiro só acontece depois de `fsync` e `os.replace`; uma falha deixa
o snapshot anterior consumível.

## PAST_ATTEMPT_LEDGER

| ID | Tentativa/hipótese | Mudança/evidência | Resultado | Estado |
|---|---|---|---|---|
| ING-01 | CSV oficial do Drive é fonte primária suficiente | OracleProvider local desde a Fase 1 | Dados históricos utilizáveis, mas quota/CDN são externos | STILL_ACTIVE |
| ING-02 | Bucket S3 oficial reduz indisponibilidade | Fallback oficial adicionado em `5311cb7` | Fonte existe; não deve regredir cobertura | PARTIALLY_WORKED |
| ING-03 | URL explicitamente aprovada permite contingência sem scraping | `ORACLES_ELIXIR_<ANO>_URL` | Prioridade explícita, sem mirror silencioso | WORKED |
| ING-04 | Temp + validação mínima evita HTML/quota | `5311cb7`, testes de HTML/cache | Impediu publicação de página de erro | WORKED |
| ING-05 | Data máxima impede regressão | `855f964`, teste de cache mais novo | Cache antigo preservado | WORKED |
| ING-06 | Scheduler/runner prova execução observável | task `lol-ratings-semanal`, envelope operacional | Executa; sem snapshot/freshness até esta rodada | PARTIALLY_WORKED |
| ING-07 | OracleProvider agrega localmente e deduplica no SQLite | `game_id` PK, testes Fase 1 | Reprocessamento idempotente | WORKED |
| ING-08 | PandaScore histórico pode complementar investigação | provider sombra, sem consumo pelo serving | Não é fonte canônica de produção | STILL_ACTIVE |
| ING-09 | ETag/retry/snapshot/frescor eliminam publicação parcial | `src.data.ingestion`, testes hostis desta rodada | Implementado e verificado localmente | WORKED |

## Contrato técnico

- HTTP envia `User-Agent`, `If-None-Match` e `If-Modified-Since` quando há
  estado anterior. `304` preserva o snapshot; sem validator, SHA-256 identifica
  conteúdo idêntico.
- Timeout é 30 s, no máximo 3 tentativas e 90 s totais. `429` respeita
  `Retry-After` limitado a 10 s; 5xx, timeout e falha de rede usam backoff
  exponencial com jitter. A falha final é persistida em `last_failure.json`.
- O CSV rejeita vazio, HTML/erro, encoding inválido, colunas essenciais
  ausentes, amostra pequena, identidade incompleta e timestamp inválido. Uma
  cobertura temporal que termina antes do snapshot vigente é rejeitada.
- Metadados incluem fonte, recuperação, `Last-Modified`, SHA-256, versão de
  schema/ingestão, faixa temporal, linhas, patch (quando a fonte o fornecer),
  validações e status.
- Não há symlink, overwrite de raw cache nem promoção para `predictor_core`.
  Alias de equipe continua responsabilidade do resolvedor LoL; não há
  aproximação automática na ingestão.

## EXPERIMENT_LEDGER

| ID | Ciclo controlado | Resultado observável | Decisão |
|---|---|---|---|
| EXP-ING-01 | respostas 200/304 + ETag | ponteiro preservado em 304; header condicional enviado | aceitar |
| EXP-ING-02 | HTML/schema/timestamp/arquivo vazio | todos rejeitados antes de publicação | aceitar |
| EXP-ING-03 | 429, 500 e timeout | retry limitado, `Retry-After`, falha persistida | aceitar |
| EXP-ING-04 | interrupção em `os.replace` e concorrência | ponteiro anterior íntegro; JSON atual legível | aceitar |
| EXP-ING-05 | snapshot expirado | serving retorna erro e não grava previsão | aceitar |

## Runbook

1. Rode `python scripts/atualiza_semanal.py` ou aguarde a tarefa semanal.
2. Confirme `data/ingestion/current.json`, seu `metadata.json` e o
   `last_failure.json` somente quando houver falha. Não edite snapshots.
3. Se a fonte estiver indisponível, o último snapshot pode permanecer para
   forense, mas o serving bloqueia ao ultrapassar 192 h. Corrija a fonte ou
   forneça uma URL aprovada; não copie CSV de mirror desconhecido.
4. Rode `python -m pytest -q -W error` e `python scripts/ci_check.py` após
   alteração de código. Não comite `data/ingestion/`, raw, logs ou bancos.
