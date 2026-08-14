import json
import threading

import pytest

import src.execution_polymarket as execution_polymarket
from src.execution_polymarket import (
    ExecutionBlockedError,
    OrderStateUnknownError,
    cancel_order,
    order_fingerprint,
    order_view,
    reconcile_order,
    submit_order,
)
from src.manual_approval import bet_fingerprint

REAL_BET = {
    "id": "bet-1",
    "real": True,
    "selection": "T1",
    "prob_model": 0.6,
    "decimal_odds": 2.0,
    "bankroll": 1000,
    "manual_approval": {"approval_id": "manual-1"},
}


def _order_kwargs(**overrides):
    kwargs = {"token_id": "token-a", "side": "BUY", "price": 0.55, "size": 10.0}
    kwargs.update(overrides)
    return kwargs


def _never_called(*_a, **_kw):
    raise AssertionError("client_factory/transmit não deveria ser chamado")


def _write_approval(path, **overrides):
    payload = {
        "schema_version": 1,
        "status": "APPROVED",
        "approval_id": "manual-1",
        "approved_by": "operator",
        "approved_at": "2020-01-01T00:00:00+00:00",
        "expires_at": "2099-01-01T00:00:00+00:00",
        "bet_fingerprint": bet_fingerprint(
            market="moneyline", selection="T1", prob_model=0.6, decimal_odds=2.0, bankroll=1000
        ),
        "order_fingerprint": order_fingerprint(token_id="token-a", side="BUY", price=0.55, size=10.0),
    }
    payload.update(overrides)
    path.write_text(json.dumps(payload))
    return path


def _go(monkeypatch):
    monkeypatch.setattr(execution_polymarket, "go_gate", lambda *_: {"decision": "GO", "reason": "test"})


def _confirm_live_trading(monkeypatch):
    monkeypatch.setenv(execution_polymarket._LIVE_TRADING_CONFIRM_ENV, "true")


# --- submit_order: camadas de bloqueio -------------------------------------


def test_bad_side_or_price_or_size_fails_before_any_gate(tmp_path):
    with pytest.raises(ValueError, match="side"):
        submit_order(REAL_BET, **_order_kwargs(side="HOLD"), client_factory=_never_called, transmit=_never_called)
    with pytest.raises(ValueError, match="price"):
        submit_order(REAL_BET, **_order_kwargs(price=1.5), client_factory=_never_called, transmit=_never_called)
    with pytest.raises(ValueError, match="size"):
        submit_order(REAL_BET, **_order_kwargs(size=0), client_factory=_never_called, transmit=_never_called)


def test_blocked_when_gate_is_not_go(tmp_path):
    with pytest.raises(ExecutionBlockedError, match="gate financeiro"):
        submit_order(
            REAL_BET,
            **_order_kwargs(),
            gate_path=tmp_path / "missing-gate.json",
            client_factory=_never_called,
            transmit=_never_called,
        )


def test_blocked_when_bet_is_not_real(monkeypatch, tmp_path):
    _go(monkeypatch)
    paper_bet = {**REAL_BET, "real": False}
    with pytest.raises(ExecutionBlockedError, match="real=True"):
        submit_order(paper_bet, **_order_kwargs(), client_factory=_never_called, transmit=_never_called)


def test_blocked_when_bet_has_no_manual_approval(monkeypatch, tmp_path):
    _go(monkeypatch)
    bet = {**REAL_BET, "manual_approval": None}
    with pytest.raises(ExecutionBlockedError, match="aprovação manual"):
        submit_order(bet, **_order_kwargs(), client_factory=_never_called, transmit=_never_called)


def test_blocked_when_approval_file_does_not_match(monkeypatch, tmp_path):
    _go(monkeypatch)
    with pytest.raises(PermissionError, match="aprovação manual"):
        submit_order(
            REAL_BET,
            **_order_kwargs(),
            approval_path=tmp_path / "missing-approval.json",
            client_factory=_never_called,
            transmit=_never_called,
        )


def test_blocked_when_order_fingerprint_does_not_match_approval(monkeypatch, tmp_path):
    """A aprovação amarra token_id/side/price/size — não só o bet abstrato.
    Sem isto, uma aprovação válida pro bet autorizaria qualquer size/price
    que o chamador passasse a submit_order."""
    _go(monkeypatch)
    approval = _write_approval(tmp_path / "approval.json")  # aprovado pra size=10.0
    with pytest.raises(PermissionError, match="token_id/side/price/size"):
        submit_order(
            REAL_BET,
            **_order_kwargs(size=999.0),
            approval_path=approval,
            client_factory=_never_called,
            transmit=_never_called,
        )


def test_blocked_without_live_trading_confirmation_env(monkeypatch, tmp_path):
    _go(monkeypatch)
    monkeypatch.delenv(execution_polymarket._LIVE_TRADING_CONFIRM_ENV, raising=False)
    approval = _write_approval(tmp_path / "approval.json")
    with pytest.raises(ExecutionBlockedError, match=execution_polymarket._LIVE_TRADING_CONFIRM_ENV):
        submit_order(
            REAL_BET,
            **_order_kwargs(),
            approval_path=approval,
            client_factory=_never_called,
            transmit=_never_called,
        )


# --- submit_order: caminho feliz e idempotência -----------------------------


def test_full_chain_reaches_accepted_and_is_idempotent(monkeypatch, tmp_path):
    _go(monkeypatch)
    _confirm_live_trading(monkeypatch)
    approval = _write_approval(tmp_path / "approval.json")
    orders = tmp_path / "orders.jsonl"
    calls = {"factory": 0, "transmit": 0}

    def fake_factory():
        calls["factory"] += 1
        return object()

    def fake_transmit(client, **kwargs):
        calls["transmit"] += 1
        return {"success": True, "orderID": "0xabc", "status": "live"}

    view = submit_order(
        REAL_BET,
        **_order_kwargs(),
        approval_path=approval,
        orders_path=orders,
        client_factory=fake_factory,
        transmit=fake_transmit,
    )
    assert view["state"] == execution_polymarket.ACCEPTED
    assert view["exchange_order_id"] == "0xabc"
    assert [e["event"] for e in view["events"]] == ["order_created", "order_submitted", "order_result"]
    assert calls == {"factory": 1, "transmit": 1}

    again = submit_order(
        REAL_BET,
        **_order_kwargs(),
        approval_path=approval,
        orders_path=orders,
        client_factory=fake_factory,
        transmit=fake_transmit,
    )
    assert again["local_order_id"] == view["local_order_id"]
    assert calls == {"factory": 1, "transmit": 1}  # não retransmite a mesma bet


def test_immediate_match_reaches_filled(monkeypatch, tmp_path):
    _go(monkeypatch)
    _confirm_live_trading(monkeypatch)
    approval = _write_approval(tmp_path / "approval.json")

    view = submit_order(
        REAL_BET,
        **_order_kwargs(),
        approval_path=approval,
        orders_path=tmp_path / "orders.jsonl",
        client_factory=lambda: object(),
        transmit=lambda client, **kw: {"success": True, "orderID": "0xabc", "status": "matched"},
    )
    assert view["state"] == execution_polymarket.FILLED
    assert view["size_matched"] == 10.0


def test_exchange_rejection_is_never_retried_silently(monkeypatch, tmp_path):
    _go(monkeypatch)
    _confirm_live_trading(monkeypatch)
    approval = _write_approval(tmp_path / "approval.json")

    view = submit_order(
        REAL_BET,
        **_order_kwargs(),
        approval_path=approval,
        orders_path=tmp_path / "orders.jsonl",
        client_factory=lambda: object(),
        transmit=lambda client, **kw: {"success": False, "errorMsg": "insufficient balance"},
    )
    assert view["state"] == execution_polymarket.REJECTED


def test_transport_failure_raises_state_unknown_and_never_retransmits(monkeypatch, tmp_path):
    _go(monkeypatch)
    _confirm_live_trading(monkeypatch)
    approval = _write_approval(tmp_path / "approval.json")
    orders = tmp_path / "orders.jsonl"
    calls = {"transmit": 0}

    def flaky_transmit(client, **kwargs):
        calls["transmit"] += 1
        raise TimeoutError("network dropped mid-request")

    with pytest.raises(OrderStateUnknownError, match="reconcilie"):
        submit_order(
            REAL_BET,
            **_order_kwargs(),
            approval_path=approval,
            orders_path=orders,
            client_factory=lambda: object(),
            transmit=flaky_transmit,
        )
    assert calls["transmit"] == 1

    # Reenvio da MESMA bet não deve tentar transmitir de novo — a ordem já
    # existe (em UNKNOWN); resolver isso é trabalho do reconcile_order.
    again = submit_order(
        REAL_BET,
        **_order_kwargs(),
        approval_path=approval,
        orders_path=orders,
        client_factory=_never_called,
        transmit=flaky_transmit,
    )
    assert again["state"] == execution_polymarket.UNKNOWN
    assert calls["transmit"] == 1


def test_client_factory_failure_leaves_order_resumable_not_poisoned(monkeypatch, tmp_path):
    """Uma ordem presa em CREATED (client_factory falhou antes de qualquer
    chamada de rede pra exchange) tem que ser retomável — nunca virar um
    bet_id morto que nem retransmite nem consegue ser reconciliado/cancelado
    (ela nunca teve exchange_order_id pra começo de conversa)."""
    _go(monkeypatch)
    _confirm_live_trading(monkeypatch)
    approval = _write_approval(tmp_path / "approval.json")
    orders = tmp_path / "orders.jsonl"

    def failing_factory():
        raise ExecutionBlockedError("LOL_POLYMARKET_PRIVATE_KEY ausente (simulado)")

    with pytest.raises(ExecutionBlockedError):
        submit_order(
            REAL_BET,
            **_order_kwargs(),
            approval_path=approval,
            orders_path=orders,
            client_factory=failing_factory,
            transmit=_never_called,
        )
    stuck_id = json.loads(orders.read_text(encoding="utf-8").splitlines()[0])["local_order_id"]
    assert order_view(stuck_id, orders_path=orders)["state"] == execution_polymarket.CREATED

    calls = {"transmit": 0}

    def fake_transmit(client, **kw):
        calls["transmit"] += 1
        return {"success": True, "orderID": "0xabc", "status": "live"}

    resumed = submit_order(
        REAL_BET,
        **_order_kwargs(),
        approval_path=approval,
        orders_path=orders,
        client_factory=lambda: object(),
        transmit=fake_transmit,
    )
    assert resumed["local_order_id"] == stuck_id
    assert resumed["state"] == execution_polymarket.ACCEPTED
    assert calls["transmit"] == 1


def test_concurrent_submit_order_for_same_bet_transmits_only_once(monkeypatch, tmp_path):
    """Duas chamadas concorrentes de submit_order pro mesmo bet_id não podem
    resultar em duas transmissões — o cheque de idempotência + a escrita do
    local_order_id precisam ser atômicos entre threads."""
    _go(monkeypatch)
    _confirm_live_trading(monkeypatch)
    approval = _write_approval(tmp_path / "approval.json")
    orders = tmp_path / "orders.jsonl"
    calls = {"transmit": 0}
    lock = threading.Lock()
    barrier = threading.Barrier(2)

    def fake_transmit(client, **kw):
        with lock:
            calls["transmit"] += 1
        return {"success": True, "orderID": "0xabc", "status": "live"}

    def run(results):
        barrier.wait()
        results.append(
            submit_order(
                REAL_BET,
                **_order_kwargs(),
                approval_path=approval,
                orders_path=orders,
                client_factory=lambda: object(),
                transmit=fake_transmit,
            )
        )

    results: list[dict] = []
    threads = [threading.Thread(target=run, args=(results,)) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert calls["transmit"] == 1
    assert results[0]["local_order_id"] == results[1]["local_order_id"]


# --- reconcile_order ---------------------------------------------------------


def _submit_accepted(tmp_path, orders_path, *, order_id="0xabc"):
    approval = _write_approval(tmp_path / "approval.json")
    return submit_order(
        REAL_BET,
        **_order_kwargs(),
        approval_path=approval,
        orders_path=orders_path,
        client_factory=lambda: object(),
        transmit=lambda client, **kw: {"success": True, "orderID": order_id, "status": "live"},
    )


def test_reconcile_unknown_local_order_id_raises(tmp_path):
    with pytest.raises(ValueError, match="desconhecido"):
        reconcile_order("nope", orders_path=tmp_path / "orders.jsonl")


def _raise_timeout(client, **kwargs):
    raise TimeoutError("boom")


def test_reconcile_without_exchange_order_id_raises_state_unknown(monkeypatch, tmp_path):
    _go(monkeypatch)
    _confirm_live_trading(monkeypatch)
    orders = tmp_path / "orders.jsonl"
    approval = _write_approval(tmp_path / "approval.json")
    with pytest.raises(OrderStateUnknownError):
        submit_order(
            REAL_BET,
            **_order_kwargs(),
            approval_path=approval,
            orders_path=orders,
            client_factory=lambda: object(),
            transmit=_raise_timeout,
        )
    # Descobre o local_order_id real pela leitura do ledger (ele nunca
    # recebeu exchange_order_id, porque a transmissão falhou antes disso).
    local_order_id = json.loads(orders.read_text(encoding="utf-8").splitlines()[0])["local_order_id"]
    with pytest.raises(OrderStateUnknownError, match="nunca recebeu"):
        reconcile_order(local_order_id, orders_path=orders, client_factory=_never_called, get_order=_never_called)


def test_reconcile_terminal_state_is_a_noop(monkeypatch, tmp_path):
    _go(monkeypatch)
    _confirm_live_trading(monkeypatch)
    orders = tmp_path / "orders.jsonl"
    view = _submit_accepted(tmp_path, orders)
    filled = reconcile_order(
        view["local_order_id"],
        orders_path=orders,
        client_factory=lambda: object(),
        get_order=lambda client, order_id: {"status": "matched", "size_matched": "10.0"},
    )
    assert filled["state"] == execution_polymarket.RECONCILED

    # Reconciliar de novo é no-op — não chama get_order outra vez.
    again = reconcile_order(
        view["local_order_id"], orders_path=orders, client_factory=_never_called, get_order=_never_called
    )
    assert again == filled


def test_reconcile_partial_fill_then_full_fill(monkeypatch, tmp_path):
    _go(monkeypatch)
    _confirm_live_trading(monkeypatch)
    orders = tmp_path / "orders.jsonl"
    view = _submit_accepted(tmp_path, orders)

    partial = reconcile_order(
        view["local_order_id"],
        orders_path=orders,
        client_factory=lambda: object(),
        get_order=lambda client, order_id: {"status": "live", "size_matched": "4.0"},
    )
    assert partial["state"] == execution_polymarket.PARTIALLY_FILLED
    assert partial["size_matched"] == 4.0

    full = reconcile_order(
        partial["local_order_id"],
        orders_path=orders,
        client_factory=lambda: object(),
        get_order=lambda client, order_id: {"status": "matched", "size_matched": "10.0"},
    )
    assert full["state"] == execution_polymarket.RECONCILED
    assert full["size_matched"] == 10.0


def test_reconcile_treats_full_size_matched_while_still_live_as_filled(monkeypatch, tmp_path):
    """A CLOB às vezes reporta size_matched == pedido antes de o status virar
    'matched'; isso tem que contar como FILLED (e então RECONCILED), não
    ACCEPTED preso esperando uma reconciliação futura que não vai achar
    nada novo."""
    _go(monkeypatch)
    _confirm_live_trading(monkeypatch)
    orders = tmp_path / "orders.jsonl"
    view = _submit_accepted(tmp_path, orders)  # size=10.0 (default de _order_kwargs)

    result = reconcile_order(
        view["local_order_id"],
        orders_path=orders,
        client_factory=lambda: object(),
        get_order=lambda client, order_id: {"status": "live", "size_matched": "10.0"},
    )
    assert result["state"] == execution_polymarket.RECONCILED
    assert result["size_matched"] == 10.0


def test_reconcile_unrecognized_status_stays_unknown(monkeypatch, tmp_path):
    _go(monkeypatch)
    _confirm_live_trading(monkeypatch)
    orders = tmp_path / "orders.jsonl"
    view = _submit_accepted(tmp_path, orders)

    result = reconcile_order(
        view["local_order_id"],
        orders_path=orders,
        client_factory=lambda: object(),
        get_order=lambda client, order_id: {"status": "some-new-status-we-have-never-seen"},
    )
    assert result["state"] == execution_polymarket.UNKNOWN


# --- cancel_order -------------------------------------------------------------


def test_cancel_unknown_local_order_id_raises(tmp_path):
    with pytest.raises(ValueError, match="desconhecido"):
        cancel_order("nope", orders_path=tmp_path / "orders.jsonl")


def test_cancel_requires_no_gate_or_approval(monkeypatch, tmp_path):
    """cancel_order tem que funcionar mesmo com o gate financeiro em NO-GO —
    é o kill switch, não pode depender do mesmo interruptor que autoriza risco."""
    _go(monkeypatch)
    _confirm_live_trading(monkeypatch)
    orders = tmp_path / "orders.jsonl"
    view = _submit_accepted(tmp_path, orders)

    # Agora simula o gate voltando pra NO-GO — cancelar ainda tem que funcionar.
    monkeypatch.setattr(execution_polymarket, "go_gate", lambda *_: {"decision": "NO-GO", "reason": "test"})
    monkeypatch.delenv(execution_polymarket._LIVE_TRADING_CONFIRM_ENV, raising=False)

    cancelled = cancel_order(
        view["local_order_id"],
        orders_path=orders,
        client_factory=lambda: object(),
        cancel=lambda client, order_id: {"canceled": [order_id]},
    )
    assert cancelled["state"] == execution_polymarket.CANCELLED


def test_cancel_terminal_state_is_a_noop(monkeypatch, tmp_path):
    _go(monkeypatch)
    _confirm_live_trading(monkeypatch)
    orders = tmp_path / "orders.jsonl"
    view = _submit_accepted(tmp_path, orders)
    first = cancel_order(
        view["local_order_id"], orders_path=orders, client_factory=lambda: object(), cancel=lambda c, o: {"ok": True}
    )
    again = cancel_order(view["local_order_id"], orders_path=orders, client_factory=_never_called, cancel=_never_called)
    assert again == first


# --- order_view ---------------------------------------------------------------


def test_order_view_unknown_id_returns_none(tmp_path):
    assert order_view("nope", orders_path=tmp_path / "orders.jsonl") is None


def test_build_client_fails_closed_without_private_key(monkeypatch):
    monkeypatch.delenv("LOL_POLYMARKET_PRIVATE_KEY", raising=False)
    with pytest.raises(ExecutionBlockedError, match="PRIVATE_KEY"):
        execution_polymarket.build_client()
