# Migração 2.0

O runtime homologado é Python 3.13 com `uv`; 3.14 permanece experimental. `pyproject.toml`
e `uv.lock` são as fontes oficiais. `predictor_core>=2.2,<3` e
`predictor_ops>=3,<4` entram exclusivamente como wheels externas, publicadas como
GitHub Releases de core-predictor/tools-predictor, com hash fixado pelo lock
(`[tool.uv.sources]`) — não há wheelhouse vendorizado no repositório.

## Arquitetura

- `services.py`: previsão, ingestão, ratings e settlement.
- `plugin.py`: plugin canônico `predictor.plugins/lol` e health/capabilities.
- `repositories.py`: seams para PostgreSQL e Object Storage, preservando os arquivos oficiais.
- `data/ingestion.py`: snapshots imutáveis e publicação atômica; serving falha fechado.
- `cli.py`: adaptadores de CLI; `lol-scheduler` delega ao `predictor_ops`.

O runtime não usa vendor, repositório irmão, `PYTHONPATH`, alteração de caminhos ou Task
Scheduler. Adaptadores PowerShell foram isolados em `migration/windows/`; podem ser
removidos quando um ciclo semanal e um ciclo de settlement forem observados no scheduler
portátil. Rollback: reinstalar temporariamente as tarefas dessa pasta, sem reintroduzi-las
no container ou CI.

## Ciência

Elo H1, probabilidades BO1/BO3/BO5 e lifecycle são preservados pelos golden tests.
Kills continua no baseline agregado aprovado; Platt e apostas reais continuam fail-closed.
H4 permanece governado pelo artefato humano versionado e nunca é promovido por settings.

## Cobertura

A CI publica a cobertura global sem exclusões e, separadamente, aplica o mínimo de 80%
com branches ao runtime homologado: config, snapshot/ingestão, Elo/predict, H4, settings,
plugin e serviços. Módulos retrospectivos, adaptadores de pesquisa e compatibilidade ainda
aparecem no relatório global; não são silenciosamente removidos da medição.

## Instalação local com artefatos

`uv sync --all-groups` baixa `predictor-core`/`predictor-ops` diretamente das URLs de
GitHub Release declaradas em `[tool.uv.sources]`, validando o hash contra `uv.lock`.
Confirme `predictor_core.__file__`/`predictor_ops.__file__` em `site-packages`. Em
produção, injete `LOL_PROJECT_ROOT` e `LOL_DATA_ROOT`; arquivos oficiais não são
migrados destrutivamente.
