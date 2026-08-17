# Pré/pós-draft: contrato shadow

Esta cadeia é uma hipótese nova e não altera H4, kills, `go_gate()` ou a
decisão de capital `NO_GO`.

## Auditoria de cobertura

```powershell
lol-predictor audit-draft-coverage --horizon-hours 168
```

O relatório padrão é `data/reports/draft_coverage_latest.json`. Falha de rede
ou credencial ausente é registrada como indisponibilidade (`events: null`),
nunca como zero eventos. A auditoria mede IDs canônicos por fornecedor,
eventos futuros, resolução de identidade, sobreposição PandaScore/Polymarket e
presença observada de roster, substitutos, patch e campos de draft.

`PANDASCORE_TOKEN` deve ser configurado no ambiente para auditar PandaScore. O
segredo não é serializado. GRID permanece sem adapter e sem alegação de
cobertura.

## Observação econômica

Cada registro `lol-draft-market-observation/1.0` exige:

- mercado `SERIES_WINNER` ou `MAP_WINNER`;
- momento `PRE_DRAFT`, `POST_DRAFT` ou `CLOSING`;
- evento, competição, seleção, cutoff e settlement policy explícitos;
- roster de cinco titulares conhecido até o momento da decisão;
- patch;
- best bid/ask, tamanho no melhor nível e probabilidade do modelo;
- draft ordenado para `POST_DRAFT` e `CLOSING`.

`PRE_DRAFT` deve preceder o primeiro ban e não pode carregar informação do
draft. `POST_DRAFT` só aceita book publicado após o draft completo. A cadeia
comparável exige os três momentos no mesmo evento, mercado, seleção e regra de
settlement.

Odds econômicas usam o ask executável. Midpoint continua disponível apenas
para diagnóstico. Todos os registros declaram `mode: SHADOW` e
`capital_authorized: false`.

## Gate de continuidade

A modelagem pós-draft continua bloqueada até o relatório comprovar:

1. fonte esportiva e Polymarket disponíveis;
2. sobreposição canônica suficiente;
3. roster prospectivo completo;
4. timeline ordenada do draft;
5. mercado de série ou mapa com books nos três momentos.

Campos agregados de picks/bans não são classificados como timeline. Nenhum
resultado técnico promove automaticamente shadow para paper ou capital real.
