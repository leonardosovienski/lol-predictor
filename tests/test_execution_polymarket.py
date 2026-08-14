import json

import pytest

import src.execution_polymarket as execution_polymarket
from src.execution_polymarket import ExecutionBlockedError, submit_order
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
    monkeypatch.setattr(execution_polymarket, "go_gate", lambda *_: {"decision": "GO", "reason": "test"})
    paper_bet = {**REAL_BET, "real": False}
    with pytest.raises(ExecutionBlockedError, match="real=True"):
        submit_order(paper_bet, **_order_kwargs(), client_factory=_never_called, transmit=_never_called)


def test_blocked_when_bet_has_no_manual_approval(monkeypatch, tmp_path):
    monkeypatch.setattr(execution_polymarket, "go_gate", lambda *_: {"decision": "GO", "reason": "test"})
    bet = {**REAL_BET, "manual_approval": None}
    with pytest.raises(ExecutionBlockedError, match="aprovação manual"):
        submit_order(bet, **_order_kwargs(), client_factory=_never_called, transmit=_never_called)


def test_blocked_when_approval_file_does_not_match(monkeypatch, tmp_path):
    monkeypatch.setattr(execution_polymarket, "go_gate", lambda *_: {"decision": "GO", "reason": "test"})
    with pytest.raises(PermissionError, match="aprovação manual"):
        submit_order(
            REAL_BET,
            **_order_kwargs(),
            approval_path=tmp_path / "missing-approval.json",
            client_factory=_never_called,
            transmit=_never_called,
        )


def test_blocked_without_live_trading_confirmation_env(monkeypatch, tmp_path):
    monkeypatch.setattr(execution_polymarket, "go_gate", lambda *_: {"decision": "GO", "reason": "test"})
    monkeypatch.delenv(execution_polymarket._LIVE_TRADING_CONFIRM_ENV, raising=False)
    approval = tmp_path / "approval.json"
    approval.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "status": "APPROVED",
                "approval_id": "manual-1",
                "approved_by": "operator",
                "approved_at": "2020-01-01T00:00:00+00:00",
                "expires_at": "2099-01-01T00:00:00+00:00",
                "bet_fingerprint": bet_fingerprint(
                    market="moneyline", selection="T1", prob_model=0.6, decimal_odds=2.0, bankroll=1000
                ),
            }
        )
    )
    with pytest.raises(ExecutionBlockedError, match=execution_polymarket._LIVE_TRADING_CONFIRM_ENV):
        submit_order(
            REAL_BET,
            **_order_kwargs(),
            approval_path=approval,
            client_factory=_never_called,
            transmit=_never_called,
        )


def test_full_chain_passes_and_is_idempotent(monkeypatch, tmp_path):
    monkeypatch.setattr(execution_polymarket, "go_gate", lambda *_: {"decision": "GO", "reason": "test"})
    monkeypatch.setenv(execution_polymarket._LIVE_TRADING_CONFIRM_ENV, "true")
    approval = tmp_path / "approval.json"
    approval.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "status": "APPROVED",
                "approval_id": "manual-1",
                "approved_by": "operator",
                "approved_at": "2020-01-01T00:00:00+00:00",
                "expires_at": "2099-01-01T00:00:00+00:00",
                "bet_fingerprint": bet_fingerprint(
                    market="moneyline", selection="T1", prob_model=0.6, decimal_odds=2.0, bankroll=1000
                ),
            }
        )
    )
    orders = tmp_path / "orders.jsonl"
    calls = {"factory": 0, "transmit": 0}

    def fake_factory():
        calls["factory"] += 1
        return object()

    def fake_transmit(client, **kwargs):
        calls["transmit"] += 1
        return {"status": "matched", "orderID": "0xabc"}

    row = submit_order(
        REAL_BET,
        **_order_kwargs(),
        approval_path=approval,
        orders_path=orders,
        client_factory=fake_factory,
        transmit=fake_transmit,
    )
    assert row["event"] == "order_submitted" and row["bet_id"] == "bet-1"
    assert row["clob_response"] == {"status": "matched", "orderID": "0xabc"}
    assert calls == {"factory": 1, "transmit": 1}

    again = submit_order(
        REAL_BET,
        **_order_kwargs(),
        approval_path=approval,
        orders_path=orders,
        client_factory=fake_factory,
        transmit=fake_transmit,
    )
    assert again == row
    assert calls == {"factory": 1, "transmit": 1}  # não retransmite a mesma bet


def test_build_client_fails_closed_without_private_key(monkeypatch):
    monkeypatch.delenv("LOL_POLYMARKET_PRIVATE_KEY", raising=False)
    with pytest.raises(ExecutionBlockedError, match="PRIVATE_KEY"):
        execution_polymarket.build_client()
