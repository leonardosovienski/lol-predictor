# Execução real de ordem (Polymarket)

`src/execution_polymarket.py` é a canalização de transmissão de ordem real
para o Polymarket CLOB. Ela existe para que, no dia em que o gate financeiro
legitimamente autorizar dinheiro real, a integração já esteja pronta — **ela
não move essa data para mais perto**, e hoje está estruturalmente inerte.

## Status atual: inerte

`go_gate()` (`src/betting.py`) está com todo caminho de código retornando
`"NO-GO"`, independentemente do que `data/market_gate.json` contiver.
`submit_order()` chama `go_gate()` de verdade e recusa qualquer transmissão
enquanto a decisão não for `"GO"`. Nenhuma alteração deste módulo muda esse
fato — ver `docs/RELATORIO_FASE1.md` / README.md para o porquê (backtest
retrospectivo H4-R inconclusivo: os dois IC95% cruzam zero) e
`docs/H4_COHORT_CONTRACT.md` para o histórico de tentativas de contornar o
gate (todas rejeitadas).

## Camadas de bloqueio (todas verificadas dentro de `submit_order`, nesta ordem)

1. **Gate financeiro** — `go_gate(gate_path)["decision"] == "GO"`. Hoje nunca
   é verdade.
2. **Bet real com aprovação manual válida** — `bet["real"]` precisa ser
   `True`, e a aprovação embutida em `bet["manual_approval"]` é revalidada
   contra o arquivo em disco (`require_manual_approval` +
   `bet_fingerprint`), amarrada à seleção/odds/probabilidade/banca exatas
   desta ordem. O dict que o chamador passa nunca é confiado sozinho.
3. **Confirmação explícita de live trading** — a variável de ambiente
   `LOL_POLYMARKET_LIVE_TRADING_CONFIRMED` precisa valer `"true"`. Isto é um
   segundo opt-in humano, independente do gate e da aprovação, para que
   nenhum script que apenas importe a função dispare uma ordem sem querer.
4. **Idempotência** — o mesmo `bet["id"]` nunca é retransmitido; uma segunda
   chamada devolve o registro já gravado em `data/orders.jsonl`
   (gitignored) sem tocar a rede.

Se qualquer camada falhar, `submit_order` levanta `ExecutionBlockedError`
(ou `PermissionError`, vindo da aprovação manual) e não transmite nada,
parcial ou totalmente.

## Credenciais

Lidas só de variáveis de ambiente, **fora** de `Settings`/pydantic (para
nunca aparecer em serialização ou log estruturado):

- `LOL_POLYMARKET_PRIVATE_KEY` — chave da carteira que assina as ordens.
- `LOL_POLYMARKET_FUNDER` — endereço com os fundos (obrigatório se
  `LOL_POLYMARKET_SIGNATURE_TYPE != 0`, i.e. carteira proxy/email).
- `LOL_POLYMARKET_SIGNATURE_TYPE` — `0` (EOA), `1` (email/Magic) ou `2`
  (proxy de navegador); default `0`.
- `LOL_POLYMARKET_LIVE_TRADING_CONFIRMED` — `"true"` para autorizar
  transmissão (camada 3 acima).

Nenhuma delas deve ir para `.env` versionado ou log: `build_client()` só as
lê de `os.environ`, nunca as coloca em `Settings`/pydantic (que poderia ser
serializado em log estruturado). O ledger `data/orders.jsonl` é construído só
com campos operacionais (`token_id`/`side`/`price`/`size`/`approval_id`/
resposta do CLOB) — a chave/credenciais nunca chegam a esse dict, então não
há necessidade (nem seria seguro: um passe de redação por substring sobre um
JSON pode corromper campos legítimos que colidam com um segredo curto) de
redigir o payload antes de gravar.

## Dependência opcional

`py-clob-client` só é importado dentro de `build_client()`/`_live_transmit()`,
depois que as camadas 1–3 já passaram. Instale com:

```bash
uv sync --extra execution
# ou
pip install "lol-predictor[execution]"
```

A suíte de testes (`tests/test_execution_polymarket.py`) nunca precisa desse
extra instalado: `client_factory` e `transmit` são injetáveis, e os testes
usam duplos de teste no lugar do cliente real — o mesmo padrão de
`PolymarketProvider(get_json=...)`.

## Reabrir o caminho de dinheiro real de verdade

Não é este módulo que decide isso. Requer, na ordem do
`H4_COHORT_CONTRACT.md`/`data/h4_v2_closure.json`:

1. A coorte H4 V2 sair de `NO_GO` por uma nova decisão humana auditável.
2. A amostra pré-registrada (50 partidas maturadas, 30 dias corridos, 30
   sinais, 3 competições) ser atingida organicamente.
3. `h4_gate.evaluate()` produzir `GATE_PASSED_FOR_PROSPECTIVE_SHADOW` com os
   dois IC95% (diferença de Brier e ROI shadow) inteiramente do lado
   favorável — não apenas o ponto estimado.
4. Só então `go_gate()` em `src/betting.py` seria alterado, por um commit
   separado e explícito, para poder retornar `"GO"` sob essas condições.

Nenhum desses quatro passos é alcançado por editar `execution_polymarket.py`.
