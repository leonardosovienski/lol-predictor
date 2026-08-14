"""Transmissão real de ordem para o Polymarket CLOB — inerte até `go_gate()` retornar "GO".

Este módulo existe só para a canalização de transmissão já estar pronta com
antecedência; ele não autoriza nada por conta própria. `submit_order()`
reavalia `go_gate()` e a aprovação manual de forma independente do que o
chamador afirma sobre `bet` — nunca confia em um estado já validado alhures —
e credenciais só são lidas de variáveis de ambiente, nunca persistidas em
disco nem devolvidas em qualquer valor de retorno.

Camadas de bloqueio, na ordem em que são verificadas:

1. `go_gate()` precisa devolver "GO". Hoje ele está sempre "NO-GO" por
   construção (ver `betting.go_gate`); este módulo não contorna isso.
2. `bet["real"]` precisa ser True e carregar uma aprovação manual cujo
   fingerprint bate com a seleção/odds/probabilidade/banca desta ordem —
   revalidada aqui contra o arquivo de aprovação, não só o dict do chamador.
3. `LOL_POLYMARKET_LIVE_TRADING_CONFIRMED=true` precisa estar no ambiente —
   um segundo opt-in humano explícito, além do gate e da aprovação, para que
   nenhum script que apenas importe esta função dispare uma ordem sem querer.
4. O mesmo bet nunca é submetido duas vezes (idempotência via o ledger local
   de ordens).

`py-clob-client` (dependência do extra opcional `lol-predictor[execution]`)
só é importado depois que todas as camadas acima já passaram.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from .betting import go_gate
from .config import ROOT
from .manual_approval import bet_fingerprint, require_manual_approval

_LIVE_TRADING_CONFIRM_ENV = "LOL_POLYMARKET_LIVE_TRADING_CONFIRMED"


class ExecutionBlockedError(PermissionError):
    """Uma ordem real não pode ser transmitida ainda."""


class _ClobClient(Protocol):
    def create_order(self, order_args: Any) -> Any: ...
    def post_order(self, signed_order: Any, order_type: Any) -> Any: ...


def build_client(*, chain_id: int = 137) -> _ClobClient:
    """Monta um `ClobClient` autenticado a partir de segredos do ambiente.

    Import adiado: `py-clob-client` é um extra opcional (`lol-predictor[execution]`),
    então a instalação base nunca precisa da stack web3.
    """
    private_key = os.environ.get("LOL_POLYMARKET_PRIVATE_KEY")
    if not private_key:
        raise ExecutionBlockedError("LOL_POLYMARKET_PRIVATE_KEY ausente; execução real exige a chave da carteira")
    signature_type = int(os.environ.get("LOL_POLYMARKET_SIGNATURE_TYPE", "0"))
    funder = os.environ.get("LOL_POLYMARKET_FUNDER")
    if signature_type != 0 and not funder:
        raise ExecutionBlockedError("LOL_POLYMARKET_FUNDER ausente; obrigatório para signature_type != 0")

    try:
        from py_clob_client.client import ClobClient
    except ImportError as exc:
        raise ExecutionBlockedError("py-clob-client não instalado; use `pip install lol-predictor[execution]`") from exc

    host = os.environ.get("LOL_POLYMARKET_CLOB_URL", "https://clob.polymarket.com")
    kwargs: dict[str, Any] = {"key": private_key, "chain_id": chain_id, "signature_type": signature_type}
    if funder:
        kwargs["funder"] = funder
    client = ClobClient(host, **kwargs)
    client.set_api_creds(client.create_or_derive_api_creds())
    return client


def _live_transmit(client: _ClobClient, *, token_id: str, side: str, price: float, size: float) -> dict:
    from py_clob_client.clob_types import OrderArgs, OrderType
    from py_clob_client.order_builder.constants import BUY, SELL

    order_args = OrderArgs(token_id=token_id, price=round(price, 4), size=round(size, 2), side=BUY if side == "BUY" else SELL)
    signed = client.create_order(order_args)
    response = client.post_order(signed, OrderType.GTC)
    return response if isinstance(response, dict) else {"raw": str(response)}


def _orders_path(path: str | Path | None) -> Path:
    return Path(path or os.environ.get("ORDERS_LOG_PATH", ROOT / "data" / "orders.jsonl"))


def _already_submitted(bet_id: str, *, path: str | Path | None) -> dict | None:
    target = _orders_path(path)
    if not target.exists():
        return None
    for line in target.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if row.get("event") == "order_submitted" and row.get("bet_id") == bet_id:
            return row
    return None


def _audit(row: dict, *, path: str | Path | None) -> dict:
    # `row` is built entirely from operational fields (id/timestamp/token_id/
    # side/price/size/approval_id/CLOB response) — credentials never reach
    # it, so there is nothing here that needs redaction before it hits disk.
    target = _orders_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(row, ensure_ascii=False, sort_keys=True)
    with target.open("a", encoding="utf-8", newline="\n") as f:
        f.write(text + "\n")
        f.flush()
        os.fsync(f.fileno())
    return row


def submit_order(
    bet: dict,
    *,
    token_id: str,
    side: str,
    price: float,
    size: float,
    gate_path: str | Path | None = None,
    approval_path: str | Path | None = None,
    orders_path: str | Path | None = None,
    client_factory=build_client,
    transmit=_live_transmit,
) -> dict:
    """Transmite uma ordem real para um `bet` já registrado por `betting.record_bet(real=True)`.

    Levanta `ExecutionBlockedError` (ou `PermissionError`, da aprovação
    manual) em qualquer camada que não passar; nunca transmite parcialmente.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError("side deve ser BUY ou SELL")
    if not (0 < price < 1):
        raise ValueError("price deve estar em (0, 1)")
    if size <= 0:
        raise ValueError("size deve ser positivo")

    decision = go_gate(gate_path)
    if decision["decision"] != "GO":
        raise ExecutionBlockedError(f"execução real bloqueada pelo gate financeiro: {decision['reason']}")

    if not bet.get("real"):
        raise ExecutionBlockedError("execução real exige um bet registrado com real=True")
    approval = bet.get("manual_approval")
    if not isinstance(approval, dict) or not approval.get("approval_id"):
        raise ExecutionBlockedError("bet sem aprovação manual associada")
    # `approval` embutido em `bet` é só uma cópia; a fonte de verdade é o
    # arquivo em disco — revalidado aqui, nunca apenas confiado.
    require_manual_approval(
        approval_path,
        fingerprint=bet_fingerprint(
            market=bet.get("market", "moneyline"),
            selection=bet["selection"],
            prob_model=bet["prob_model"],
            decimal_odds=bet["decimal_odds"],
            bankroll=bet["bankroll"],
        ),
    )

    if os.environ.get(_LIVE_TRADING_CONFIRM_ENV, "").strip().lower() != "true":
        raise ExecutionBlockedError(f"defina {_LIVE_TRADING_CONFIRM_ENV}=true para autorizar a transmissão real")

    if existing := _already_submitted(bet["id"], path=orders_path):
        return existing

    client = client_factory()
    response = transmit(client, token_id=token_id, side=side, price=price, size=size)

    row = {
        "id": str(uuid.uuid4()),
        "event": "order_submitted",
        "bet_id": bet["id"],
        "domain": "lol",
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "token_id": token_id,
        "side": side,
        "price": price,
        "size": size,
        "approval_id": approval["approval_id"],
        "clob_response": response,
    }
    return _audit(row, path=orders_path)
