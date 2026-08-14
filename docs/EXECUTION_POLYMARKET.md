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

## Máquina de estados da ordem

Cada ordem local tem um `local_order_id` (gerado em `submit_order`,
independente do `bet_id`) e um histórico evento-sourced em
`data/orders.jsonl` — nenhuma linha é editada, só apendada, igual
`bets.jsonl`. `order_view(local_order_id)` reconstrói o estado atual
dobrando esse histórico.

```
CREATED -> SUBMITTED -> {ACCEPTED, FILLED, REJECTED, UNKNOWN}
ACCEPTED -> {PARTIALLY_FILLED, FILLED, CANCELLED, UNKNOWN}   (via reconcile_order)
PARTIALLY_FILLED -> {FILLED, CANCELLED, UNKNOWN}              (via reconcile_order)
{FILLED, CANCELLED, REJECTED} -> RECONCILED                   (confirmado contra a exchange)
```

`UNKNOWN` nunca é reenviado automaticamente. Se `transmit()` levanta uma
exceção (timeout, queda de rede — não sabemos se a exchange recebeu a
ordem), `submit_order` grava `UNKNOWN` e levanta `OrderStateUnknownError`;
uma segunda chamada com o mesmo `bet["id"]` devolve essa mesma ordem em
`UNKNOWN` sem retransmitir — só `reconcile_order` pode avançar dali.

`reconcile_order(local_order_id)` consulta `client.get_order()` e move o
estado adiante (ou confirma `RECONCILED`); é no-op idempotente se a ordem já
estiver num estado terminal (`FILLED`/`CANCELLED`/`REJECTED`/`RECONCILED`).
Se a ordem nunca recebeu um `exchange_order_id` (falhou antes da exchange
confirmar recebimento), reconciliação automática não é segura — levanta
`OrderStateUnknownError` pedindo verificação manual via `get_orders`/`get_trades`.

`cancel_order(local_order_id)` chama `client.cancel()`. **Ao contrário de
`submit_order`, não exige `go_gate`, aprovação manual nem
`LOL_POLYMARKET_LIVE_TRADING_CONFIRMED`** — cancelar só reduz risco que já
existe na exchange, nunca cria risco novo, então não pode ficar refém dos
mesmos interruptores que autorizam uma ordem nova. É o kill switch por
ordem individual (o `H4_COHORT_CONTRACT.md` já pede um "kill switch
central" mais amplo — isto cobre só o nível de ordem).

Os mapeamentos de status cru da API (`_interpret_post_order_response`,
`_interpret_order_status` — ex. `"live"`/`"matched"`/`"unmatched"`) são
melhor esforço a partir da documentação pública do `py-clob-client`;
qualquer status não reconhecido cai em `UNKNOWN` por construção. **Isso
precisa ser validado contra respostas reais da API antes de qualquer uso
com dinheiro de verdade** — não foi testado contra o serviço ao vivo.

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
