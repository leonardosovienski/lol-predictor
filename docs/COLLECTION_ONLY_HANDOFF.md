# COLLECTION_ONLY — handoff para tools

## Escopo e isolamento

`lol-archival-collection` é uma coleta arquivística de dados esportivos. Ela
publica snapshots no runtime externo `%LOCALAPPDATA%/predictor-tools/runtime/`
e usa o run versionado `data/collection_only_run.json`. Não lê nem escreve
H4, trials, cotações, `market_gate.json`, apostas ou estados científicos.

H4 V2 permanece `CLOSED_BY_HUMAN_DECISION`; a tarefa
`lol-market-shadow` deve ficar desabilitada.

## Contrato

Uma entrada requer fonte esportiva oficial, IDs de série e mapa, competição,
formato BO1/3/5, horário timezone-aware e dois times resolvidos sem ambiguidade.
`canonical_event_id = source:source_event_id`; mapas nunca viram séries por
inferência. Falhas de identidade, schema ou duplicidade são rejeitadas e não
publicam um snapshot parcial.

Lifecycle: `RESULT_PENDING`, `RESULT_OFFICIAL`, `NO_UPSTREAM_EVENTS`; o health
reporta `PAST_EVENT_RESULT_PENDING` e alerta `STALE_EXPECTED_EVENT` após 48 h
sem avanço se já existia evento futuro.

## Operação

Tarefa: `lol-archival-collection`, diária às 03:15 local, usando o
`operational_runner` com lock, timeout, log, heartbeat, evento e status JSON.
Sem entrada de upstream válida, emite
`NO_UPSTREAM_EVENTS`, que é estado normal. Use `--health` para o SLO.

Não promova observações para trial: o módulo recusa explicitamente. Qualquer
nova pesquisa precisa de decisão humana e artefatos próprios.
