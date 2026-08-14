"""Transmissão real de ordem para o Polymarket CLOB — inerte até `go_gate()` retornar "GO".

Este módulo existe só para a canalização de transmissão já estar pronta com
antecedência; ele não autoriza nada por conta própria. `submit_order()`
reavalia `go_gate()` e a aprovação manual de forma independente do que o
chamador afirma sobre `bet` — nunca confia em um estado já validado alhures —
e credenciais só são lidas de variáveis de ambiente, nunca persistidas em
disco nem devolvidas em qualquer valor de retorno.

Camadas de bloqueio pra CRIAR risco novo (`submit_order`), na ordem em que
são verificadas:

1. `go_gate()` precisa devolver "GO". Hoje ele está sempre "NO-GO" por
   construção (ver `betting.go_gate`); este módulo não contorna isso.
2. `bet["real"]` precisa ser True e carregar uma aprovação manual cujo
   fingerprint bate com a seleção/odds/probabilidade/banca desta ordem —
   revalidada aqui contra o arquivo de aprovação, não só o dict do chamador.
3. `LOL_POLYMARKET_LIVE_TRADING_CONFIRMED=true` precisa estar no ambiente —
   um segundo opt-in humano explícito, além do gate e da aprovação, para que
   nenhum script que apenas importe esta função dispare uma ordem sem querer.
4. O mesmo bet nunca é submetido duas vezes (idempotência via o ledger local
   de ordens, chaveado por `bet_id`).

`reconcile_order()` e `cancel_order()` são o oposto: NÃO exigem gate,
aprovação nem confirmação de live trading, de propósito — elas só reduzem ou
esclarecem risco que já existe (ou existiu) na exchange, nunca criam risco
novo. Gatear a saída atrás dos mesmos interruptores que gateiam a entrada
tornaria impossível cancelar ou investigar uma ordem depois que o estado dos
gates mudasse — o oposto de um kill switch.

Máquina de estados por ordem local (evento-sourced em `data/orders.jsonl`,
nunca editado/apagado, só apendado — mesmo padrão de `bets.jsonl`):

    CREATED -> SUBMITTED -> {ACCEPTED, FILLED, REJECTED, UNKNOWN}
    ACCEPTED -> {PARTIALLY_FILLED, FILLED, CANCELLED, UNKNOWN} (via reconcile_order)
    PARTIALLY_FILLED -> {FILLED, CANCELLED, UNKNOWN} (via reconcile_order)
    {FILLED, CANCELLED, REJECTED} -> RECONCILED (confirmado contra a exchange)

UNKNOWN nunca é reenviado automaticamente: se a transmissão falha sem
confirmação (timeout, queda de rede — não sabemos se a exchange recebeu a
ordem), `submit_order` levanta `OrderStateUnknownError` e exige uma chamada
explícita a `reconcile_order()` antes de qualquer decisão nova. Isto é
deliberado: reenviar às cegas pode duplicar uma ordem real.

`py-clob-client` (dependência do extra opcional `lol-predictor[execution]`)
só é importado depois que todas as camadas de `submit_order` já passaram —
`reconcile_order`/`cancel_order` importam assim que chamados, já que não têm
camada de bloqueio equivalente.

Os nomes de status crus (`status`/`size_matched` na resposta do CLOB, ex.
"live"/"matched"/"unmatched") em `_interpret_post_order_response` e
`_interpret_order_status` são melhor esforço a partir da documentação
pública do `py-clob-client`; qualquer status não reconhecido cai em UNKNOWN
por construção, nunca é otimisticamente tratado como sucesso. Antes deste
código valer pra dinheiro real, alguém precisa validar esses dois mapeamentos
contra respostas reais da API (ou de um ambiente de teste da Polymarket).
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from .betting import go_gate
from .config import ROOT
from .manual_approval import bet_fingerprint, require_manual_approval

_LIVE_TRADING_CONFIRM_ENV = "LOL_POLYMARKET_LIVE_TRADING_CONFIRMED"

# Serializa a seção crítica de submit_order (checar se já existe ordem pra
# este bet_id + reivindicar um local_order_id) contra outra thread deste
# processo (_ORDERS_LOCK) e contra outro processo (_file_lock, mesmo padrão
# de model.py/_RATINGS_LOCK+_file_lock). Sem isto, duas chamadas
# concorrentes pro mesmo bet_id podiam ambas passar pelo cheque de
# idempotência antes de qualquer uma escrever sua linha, e transmitir a
# MESMA aposta aprovada duas vezes.
_ORDERS_LOCK = threading.Lock()


@contextmanager
def _file_lock(path: Path):
    """Serializa writers locais também entre processos (Windows/POSIX)."""
    lock_path = path.with_suffix(path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "a+b") as lock:
        lock.seek(0)
        if lock.tell() == 0:
            lock.write(b"0")
            lock.flush()
        lock.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl

            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            lock.seek(0)
            if os.name == "nt":
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


CREATED = "CREATED"
SUBMITTED = "SUBMITTED"
ACCEPTED = "ACCEPTED"
PARTIALLY_FILLED = "PARTIALLY_FILLED"
FILLED = "FILLED"
CANCELLED = "CANCELLED"
REJECTED = "REJECTED"
UNKNOWN = "UNKNOWN"
RECONCILED = "RECONCILED"

# Estados em que cancel_order/reconcile_order são no-ops idempotentes (a
# ordem já está encerrada, do nosso lado ou do lado da exchange).
TERMINAL_STATES = {FILLED, CANCELLED, REJECTED, RECONCILED}


class ExecutionBlockedError(PermissionError):
    """Uma ordem real não pode ser transmitida ainda."""


class OrderStateUnknownError(RuntimeError):
    """O estado real da ordem na exchange é desconhecido; nunca reenvie sem reconciliar."""


class _ClobClient(Protocol):
    def create_order(self, order_args: Any) -> Any: ...
    def post_order(self, signed_order: Any, order_type: Any) -> Any: ...
    def get_order(self, order_id: str) -> Any: ...
    def cancel(self, order_id: str) -> Any: ...


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
        from py_clob_client.client import ClobClient  # pyright: ignore[reportMissingImports]
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
    from py_clob_client.clob_types import OrderArgs, OrderType  # pyright: ignore[reportMissingImports]
    from py_clob_client.order_builder.constants import BUY, SELL  # pyright: ignore[reportMissingImports]

    order_args = OrderArgs(
        token_id=token_id, price=round(price, 4), size=round(size, 2), side=BUY if side == "BUY" else SELL
    )
    signed = client.create_order(order_args)
    response = client.post_order(signed, OrderType.GTC)
    return response if isinstance(response, dict) else {"raw": str(response)}


def _live_get_order(client: _ClobClient, order_id: str) -> dict:
    response = client.get_order(order_id)
    return response if isinstance(response, dict) else {"raw": str(response)}


def _live_cancel(client: _ClobClient, order_id: str) -> dict:
    response = client.cancel(order_id)
    return response if isinstance(response, dict) else {"raw": str(response)}


def _orders_path(path: str | Path | None) -> Path:
    return Path(path or os.environ.get("ORDERS_LOG_PATH", ROOT / "data" / "orders.jsonl"))


def _read_rows(path: str | Path | None) -> list[dict]:
    target = _orders_path(path)
    if not target.exists():
        return []
    return [json.loads(line) for line in target.read_text(encoding="utf-8").splitlines() if line.strip()]


def _audit(row: dict, *, path: str | Path | None) -> dict:
    # `row` é construído só com campos operacionais (id/timestamp/estado/
    # token_id/side/price/size/approval_id/resposta do CLOB) — credenciais
    # nunca chegam aqui, então não há nada pra redigir antes de gravar.
    target = _orders_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(row, ensure_ascii=False, sort_keys=True)
    with target.open("a", encoding="utf-8", newline="\n") as f:
        f.write(text + "\n")
        f.flush()
        os.fsync(f.fileno())
    return row


def order_view(local_order_id: str, *, orders_path: str | Path | None = None) -> dict | None:
    """Reconstrói o estado atual de uma ordem local a partir do ledger append-only.

    Evento-sourced de propósito: nenhuma linha é editada; isto só reproduz
    "o que sabemos agora" a partir de "o que aconteceu, em ordem".
    """
    rows = [r for r in _read_rows(orders_path) if r.get("local_order_id") == local_order_id]
    if not rows:
        return None
    first, last = rows[0], rows[-1]
    exchange_order_id = next((r["exchange_order_id"] for r in reversed(rows) if r.get("exchange_order_id")), None)
    return {
        "local_order_id": local_order_id,
        "bet_id": first.get("bet_id"),
        "token_id": first.get("token_id"),
        "side": first.get("side"),
        "price": first.get("price"),
        "size": first.get("size"),
        "state": last["state"],
        "exchange_order_id": exchange_order_id,
        "size_matched": last.get("size_matched"),
        "events": [{"event": r["event"], "state": r["state"], "created_at": r["created_at"]} for r in rows],
    }


def _existing_order_for_bet(bet_id: str, *, orders_path: str | Path | None = None) -> dict | None:
    for row in _read_rows(orders_path):
        if row.get("event") == "order_created" and row.get("bet_id") == bet_id:
            return order_view(row["local_order_id"], orders_path=orders_path)
    return None


def order_fingerprint(*, token_id: str, side: str, price: float, size: float) -> str:
    """Amarra a aprovação manual a token_id/side/price/size exatos da ordem.

    `bet_fingerprint` (manual_approval.py, compartilhado com betting.py) só
    cobre seleção/odds/probabilidade/banca — nunca conheceu token_id/price/
    size, que são os campos que de fato determinam o que é transmitido pra
    exchange. Sem isto, uma aprovação válida pra um bet aprovado autorizaria
    silenciosamente qualquer price/size passado a `submit_order`."""
    payload = {"token_id": token_id, "side": side, "price": round(float(price), 8), "size": round(float(size), 8)}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _require_order_fingerprint(approval_path: str | Path | None, *, expected: str) -> None:
    try:
        approval_record = json.loads(Path(approval_path).read_text(encoding="utf-8"))  # type: ignore[arg-type]
    except (OSError, TypeError, ValueError) as exc:
        raise PermissionError("arquivo de aprovação manual inválido") from exc
    if approval_record.get("order_fingerprint") != expected:
        raise PermissionError("aprovação manual não amarra token_id/side/price/size desta ordem")


def _interpret_post_order_response(response: Any, requested_size: float) -> tuple[str, str | None, float | None]:
    """Melhor esforço pra normalizar a resposta de `client.post_order`.

    Tolerante de propósito: qualquer campo/formato não reconhecido cai em
    UNKNOWN, nunca é tratado como sucesso otimista — ver o aviso no docstring
    do módulo sobre validar isto contra a API real antes de usar de verdade.
    """
    if not isinstance(response, dict):
        return UNKNOWN, None, None
    exchange_order_id = response.get("orderID") or response.get("order_id")
    if response.get("success") is False:
        return REJECTED, exchange_order_id, None
    raw_status = str(response.get("status", "")).strip().lower()
    if raw_status == "matched":
        return FILLED, exchange_order_id, requested_size
    if raw_status in ("live", "delayed"):
        return ACCEPTED, exchange_order_id, 0.0
    if raw_status == "unmatched":
        return REJECTED, exchange_order_id, None
    if response.get("success") is True and exchange_order_id:
        return ACCEPTED, exchange_order_id, None
    return UNKNOWN, exchange_order_id, None


def _interpret_order_status(response: Any, requested_size: float) -> tuple[str, float | None]:
    """Melhor esforço pra normalizar a resposta de `client.get_order`. Mesmo
    aviso de tolerância/UNKNOWN-por-padrão de `_interpret_post_order_response`."""
    if not isinstance(response, dict):
        return UNKNOWN, None
    raw_status = str(response.get("status", "")).strip().lower()
    try:
        size_matched = float(response["size_matched"]) if response.get("size_matched") is not None else None
    except (TypeError, ValueError):
        size_matched = None
    if raw_status in ("cancelled", "canceled"):
        return CANCELLED, size_matched
    if raw_status == "matched":
        return FILLED, size_matched if size_matched is not None else requested_size
    if raw_status in ("live", "delayed"):
        if size_matched is not None and requested_size and size_matched >= requested_size:
            # A CLOB às vezes reporta o preenchimento antes de virar
            # "matched"; um size_matched que já bate o pedido é FILLED de
            # fato, não ACCEPTED — senão a ordem fica presa esperando uma
            # reconciliação futura que nunca vai "achar" nada novo.
            return FILLED, size_matched
        if size_matched and requested_size and 0 < size_matched < requested_size:
            return PARTIALLY_FILLED, size_matched
        return ACCEPTED, size_matched
    if raw_status == "unmatched":
        return REJECTED, size_matched
    return UNKNOWN, size_matched


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
    manual) em qualquer camada de bloqueio que não passar — nunca transmite
    parcialmente. Levanta `OrderStateUnknownError` se a transmissão falhar
    sem confirmação (chame `reconcile_order` depois, nunca reenvie direto).
    Devolve a `order_view()` da ordem local em qualquer outro caso, incluindo
    reenvio idempotente do mesmo `bet["id"]`.
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
    # bet_fingerprint amarra seleção/odds/probabilidade/banca; nunca soube
    # de token_id/price/size — sem este segundo cheque, uma aprovação válida
    # pro bet autorizaria silenciosamente qualquer ordem passada aqui.
    _require_order_fingerprint(
        approval_path, expected=order_fingerprint(token_id=token_id, side=side, price=price, size=size)
    )

    if os.environ.get(_LIVE_TRADING_CONFIRM_ENV, "").strip().lower() != "true":
        raise ExecutionBlockedError(f"defina {_LIVE_TRADING_CONFIRM_ENV}=true para autorizar a transmissão real")

    def _now() -> str:
        return datetime.now(UTC).isoformat(timespec="seconds")

    def _row(local_order_id: str, event: str, state: str, **fields: Any) -> dict:
        return {
            "id": str(uuid.uuid4()),
            "event": event,
            "state": state,
            "local_order_id": local_order_id,
            "bet_id": bet["id"],
            "domain": "lol",
            "created_at": _now(),
            **fields,
        }

    # Seção crítica: reivindicar (ou retomar) o local_order_id deste bet_id
    # é a única parte que precisa de exclusão mútua — o resto (montar
    # cliente, transmitir) é I/O de rede e não deve segurar o lock.
    #
    # Uma ordem presa em CREATED (client_factory ou qualquer coisa antes de
    # SUBMITTED falhou numa tentativa anterior) é seguramente retomável: nós
    # SABEMOS que nada foi transmitido ainda, então não é o mesmo caso de
    # UNKNOWN (onde a rede pode ou não ter recebido a ordem). Só a partir de
    # SUBMITTED em diante é que a ordem para de ser retomável por aqui.
    orders_target = _orders_path(orders_path)
    with _ORDERS_LOCK, _file_lock(orders_target):
        existing = _existing_order_for_bet(bet["id"], orders_path=orders_path)
        if existing is not None and existing["state"] != CREATED:
            return existing
        if existing is not None:
            local_order_id = existing["local_order_id"]
        else:
            local_order_id = str(uuid.uuid4())
            _audit(
                _row(
                    local_order_id,
                    "order_created",
                    CREATED,
                    token_id=token_id,
                    side=side,
                    price=price,
                    size=size,
                    approval_id=approval["approval_id"],
                ),
                path=orders_path,
            )

    client = client_factory()

    _audit(_row(local_order_id, "order_submitted", SUBMITTED), path=orders_path)

    try:
        response = transmit(client, token_id=token_id, side=side, price=price, size=size)
    except Exception as exc:
        _audit(
            _row(local_order_id, "order_result", UNKNOWN, exchange_order_id=None, error=f"{type(exc).__name__}: {exc}"),
            path=orders_path,
        )
        raise OrderStateUnknownError(
            f"transmissão falhou sem confirmação (local_order_id={local_order_id}); "
            "não sabemos se a exchange recebeu a ordem — reconcilie antes de tentar de novo"
        ) from exc

    state, exchange_order_id, size_matched = _interpret_post_order_response(response, size)
    _audit(
        _row(
            local_order_id,
            "order_result",
            state,
            exchange_order_id=exchange_order_id,
            size_matched=size_matched,
            clob_response=response,
        ),
        path=orders_path,
    )
    final_view = order_view(local_order_id, orders_path=orders_path)
    assert final_view is not None  # acabamos de gravar uma linha pra este id
    return final_view


def reconcile_order(
    local_order_id: str,
    *,
    orders_path: str | Path | None = None,
    client_factory=build_client,
    get_order=_live_get_order,
) -> dict:
    """Consulta a exchange pelo estado real de uma ordem já criada.

    Sempre permitido, independente do gate financeiro: reconciliar não cria
    risco novo, só resolve incerteza sobre risco que já existe (ou existiu)
    na exchange. No-op idempotente se a ordem já estiver num estado terminal.
    """
    view = order_view(local_order_id, orders_path=orders_path)
    if view is None:
        raise ValueError(f"local_order_id desconhecido: {local_order_id}")
    if view["state"] in TERMINAL_STATES:
        return view
    if not view.get("exchange_order_id"):
        raise OrderStateUnknownError(
            f"local_order_id={local_order_id} nunca recebeu um id da exchange; "
            "reconciliação automática não é segura aqui — verifique manualmente via get_orders/get_trades"
        )

    client = client_factory()
    response = get_order(client, view["exchange_order_id"])
    resolved_state, size_matched = _interpret_order_status(response, view.get("size") or 0.0)
    final_state = RECONCILED if resolved_state in (FILLED, CANCELLED, REJECTED) else resolved_state

    row = {
        "id": str(uuid.uuid4()),
        "event": "order_reconciled",
        "state": final_state,
        "resolved_as": resolved_state,
        "local_order_id": local_order_id,
        "bet_id": view.get("bet_id"),
        "domain": "lol",
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "exchange_order_id": view["exchange_order_id"],
        "size_matched": size_matched,
        "clob_response": response,
    }
    _audit(row, path=orders_path)
    final_view = order_view(local_order_id, orders_path=orders_path)
    assert final_view is not None  # acabamos de gravar uma linha pra este id
    return final_view


def cancel_order(
    local_order_id: str,
    *,
    orders_path: str | Path | None = None,
    client_factory=build_client,
    cancel=_live_cancel,
) -> dict:
    """Cancela uma ordem local ainda aberta na exchange.

    Deliberadamente sem go_gate/aprovação/LIVE_TRADING_CONFIRMED: reduzir
    risco precisa estar sempre disponível, mesmo que o estado desses gates
    mude depois que a ordem foi criada — este é o kill switch por ordem.
    """
    view = order_view(local_order_id, orders_path=orders_path)
    if view is None:
        raise ValueError(f"local_order_id desconhecido: {local_order_id}")
    if view["state"] in TERMINAL_STATES:
        return view
    if not view.get("exchange_order_id"):
        raise OrderStateUnknownError(
            f"local_order_id={local_order_id} sem exchange_order_id conhecido; "
            "não é seguro cancelar algo cujo envio nunca foi confirmado — reconcilie primeiro"
        )

    client = client_factory()
    response = cancel(client, view["exchange_order_id"])
    row = {
        "id": str(uuid.uuid4()),
        "event": "order_cancelled",
        "state": CANCELLED,
        "local_order_id": local_order_id,
        "bet_id": view.get("bet_id"),
        "domain": "lol",
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "exchange_order_id": view["exchange_order_id"],
        "clob_response": response,
    }
    _audit(row, path=orders_path)
    final_view = order_view(local_order_id, orders_path=orders_path)
    assert final_view is not None  # acabamos de gravar uma linha pra este id
    return final_view
