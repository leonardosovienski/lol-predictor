# Prompt para a próxima conversa

Você será o responsável pelo acompanhamento individual do `lol-predictor`.
Comece lendo `HANDOFF.md`, este arquivo e o último commit (`git log -1`).
Não refaça decisões já encerradas.

## Estado canônico

- Elo H1 cru é o único modelo canônico de vencedor.
- Platt H3 foi refutada e está bloqueada no serving.
- Kills por time H2 foi refutada e está bloqueada; não reabrir.
- Não há odds, apostas ou shadow econômico autorizado.
- Não introduzir patch, draft, lado ou roster ad hoc.
- Não transformar acurácia em edge financeiro.
- Replays EWC/Tier 1 são diagnósticos; não são prova forward completa.
- O backtest prequential após normalização tem n=3.053, Brier 0,4432 contra
  0,4612 do baseline, acerto 64,6% e DM p=0,0006.
- Ratings operacionais atuais: hash
  `92b6c18123c712291b6a1bbedc91b8f705071b28bdda095e7d413b8984c06821`.
- As quartas da EWC permanecem congeladas no snapshot pré-evento original
  `d45a06c250b24fb69a758bd5362c6a803b8829b949f4b1823b5910cd528f262c`,
  reproduzível por `data/snapshots/ewc_2026_pre_event_ratings.json`.
- Ledger versionado: `data/predictions.jsonl`; antes dos resultados possui
  quatro PRE_EVENT e hash
  `93a866be57ddfbda7eb27a0ad80319875093b40506250d1d1be15ced69ecae72`.

## Previsões abertas das quartas — 17/07/2026 BRT

- 08:00 HLE × T1, MD3: HLE 54,31%.
- 08:00 Gen.G × JD Gaming, MD3: Gen.G 80,78%.
- 10:30 AG.AL/Anyone's Legend × Karmine Corp, MD3: KC 51,64%.
- 10:30 Bilibili Gaming × Dplus Kia, MD3: BLG 93,66%.
- `matures_at`: 10:30 BRT para os dois primeiros; 13:00 BRT para os dois últimos.

## Primeira tarefa

Depois que cada `matures_at` tiver passado, consulte fontes públicas atuais e
confirme vencedor e placar. Crie um JSON temporário no formato abaixo, usando
nomes canônicos e placares coerentes com MD3:

```json
{
  "results": [
    {"team_a": "Hanwha Life Esports", "team_b": "T1", "winner": "...", "score": "2-0"}
  ]
}
```

Feche o lifecycle com:

```powershell
.\.venv\Scripts\python.exe scripts\predict_ewc_opening.py `
  --fixture data\fixtures\ewc_quarterfinals_2026.json `
  --ledger data\predictions.jsonl `
  --mature-results CAMINHO_DO_JSON `
  --json --strict
```

O runner deve criar MATURED idempotente com resultado, Brier multiclasse e
acerto. Nunca edite probabilidades PRE_EVENT depois do resultado. Atualize o
hash do ledger, `HANDOFF.md`, rode CI estrito e faça commit.

## Rodadas seguintes

- Só criar previsões de semifinal/final depois de participantes e horários
  públicos estarem confirmados.
- Dentro deste bracket curto, continuar usando o snapshot EWC congelado; não
  atualizar Elo com resultados intra-EWC.
- Registrar antes de `scheduled_at`. O código deve bloquear previsão in-play.
- Registrar times, aliases, região, ratings, freshness, formato, horário,
  probabilidades, limitações, hashes e commit; depois registrar resultado,
  Brier e acerto.

## Refresh semanal

A tarefa `lol-ratings-semanal` está instalada. O caminho Windows Scheduler foi
provado por uma tarefa inofensiva e o atestado está em
`data/scheduler_probe_attestation.json`. Após 20/07/2026 08:30 BRT, validar a
primeira execução natural: Scheduler, runner, heartbeat, events JSONL, lock,
artifact, health, hashes antes/depois, mudanças esperadas de rating e ausência
de falha silenciosa. Não confundir a prova do Scheduler com a observação natural.

Ao final de cada rodada, entregue um resumo objetivo e mantenha o repositório
limpo e em uma branch referenciada.
