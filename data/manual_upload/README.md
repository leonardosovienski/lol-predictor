# `data/manual_upload/` — exceção deliberada, não é o caminho canônico

Este diretório existe fora do padrão do projeto. O padrão é: dado bruto de
terceiro (Oracle's Elixir) nunca entra no controle de versão — é sempre
baixado em runtime pelo pipeline resiliente (`ORACLES_ELIXIR_<ANO>_URL`,
`src/data/ingestion.py`, `docs/INGESTION_RESILIENCE.md`) e vive em
`data/raw/`/`data/ingestion/`, ambos no `.gitignore`.

## O que tem aqui e por quê

- `2025_LoL_esports_match_data_from_OraclesElixir.csv` (~79 MB)
- `2026_LoL_esports_match_data_from_OraclesElixir.csv` (~52 MB)
- `run_ingestion.sh` — helper que aponta `ORACLES_ELIXIR_<ANO>_URL` para os
  dois arquivos acima via `file://` e roda `scripts/atualiza_semanal_payload.py`

Em 2026-08-03, um ambiente de execução usado para verificar a ingestão
ponta a ponta tinha uma política de proxy de rede que bloqueava
especificamente o host oficial do Google Drive (`drive.google.com` e
variantes) e o mirror S3 já estava permanentemente fora do ar (confirmado,
não suposição). Sem nenhuma fonte alcançável, os dois CSVs foram baixados
manualmente pelo operador (fora deste ambiente) e enviados diretamente,
para permitir a verificação real do pipeline: download → validação →
ingest → ratings → snapshot assinado → previsão servida. Rodado duas vezes
com o mesmo CSV, mesmo hash em cada etapa, mesma previsão até a 4ª
casa decimal — confirma reprodutibilidade determinística, não é achado
novo sobre o modelo em si.

**Nota sobre o ano de 2025:** o pipeline semanal (`atualiza_semanal_payload.py`)
só baixa e processa o ano corrente — `SnapshotStore` mantém um único
snapshot ativo por vez. O CSV de 2025 aqui não é consumido por essa rotina;
fica disponível para uso manual em scripts de backtest/histórico
(`scripts/backtest_walkforward.py` e afins), que leem `data/lol.db`
diretamente e não passam por este mecanismo de override.

## Por que isto é uma exceção, não o novo normal

Commitar ~130 MB de dado de terceiro no histórico do Git contraria a
decisão de arquitetura registrada no `.gitignore` do projeto e nunca sai do
histórico sozinho, mesmo se o arquivo for apagado depois. Foi feito aqui
por decisão explícita do operador, documentada, não por default do
processo normal de ingestão.

## Quando remover

Assim que a ingestão automática voltar a rodar com acesso de rede normal
(produção real, ou qualquer ambiente sem essa política de proxy), este
diretório inteiro pode ser removido — ele não é insumo de nenhum teste
(`tests/`) nem de nenhum script de produção; é conveniência pontual desta
verificação manual.
