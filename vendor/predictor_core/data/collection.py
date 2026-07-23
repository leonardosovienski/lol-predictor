"""Contrato COLLECTION_ONLY para arquivo operacional, nunca para ciência.

O arquivo registra fatos de coleta e a sua proveniência. Ele não conhece
trials, métricas, gates ou capital; tentar promover um registro daqui é erro
explícito. Consumidores podem projetar o JSONL em SQLite, mas o log original é
append-only para preservar a história de transições.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from predictor_core.kernel.jsonl_store import JsonlStore
from predictor_core.kernel.timeindex import NaiveDatetimeError, iso_z, to_utc, utcnow

__all__ = [
    "COLLECTION_SCHEMA_VERSION", "LifecycleState", "ObservationEnvelope",
    "CollectionArchive", "CollectionTransitionError", "ScientificPromotionError",
    "aggregate_funnel",
]

COLLECTION_SCHEMA_VERSION = "collection-only/1"


class LifecycleState:
    DISCOVERED = "DISCOVERED"
    VALIDATED = "VALIDATED"
    SNAPSHOT_RECORDED = "SNAPSHOT_RECORDED"
    EVENT_STARTED = "EVENT_STARTED"
    OFFICIAL_RESULT_FOUND = "OFFICIAL_RESULT_FOUND"
    COMPLETE = "COMPLETE"
    REJECTED = "REJECTED"
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"
    IDENTITY_AMBIGUOUS = "IDENTITY_AMBIGUOUS"
    STALE = "STALE"
    CLOSED = "CLOSED"


_ORDERED = (LifecycleState.DISCOVERED, LifecycleState.VALIDATED,
            LifecycleState.SNAPSHOT_RECORDED, LifecycleState.EVENT_STARTED,
            LifecycleState.OFFICIAL_RESULT_FOUND, LifecycleState.COMPLETE)
_TERMINAL = {LifecycleState.COMPLETE, LifecycleState.REJECTED,
             LifecycleState.SOURCE_UNAVAILABLE, LifecycleState.IDENTITY_AMBIGUOUS,
             LifecycleState.STALE, LifecycleState.CLOSED}
_ALL = set(_ORDERED) | _TERMINAL
_REJECTION_STATES = {LifecycleState.REJECTED, LifecycleState.SOURCE_UNAVAILABLE,
                     LifecycleState.IDENTITY_AMBIGUOUS, LifecycleState.STALE,
                     LifecycleState.CLOSED}


class CollectionTransitionError(ValueError):
    """Transição ou alteração de um fato arquivístico inválida."""


class ScientificPromotionError(PermissionError):
    """COLLECTION_ONLY não pode ser convertido em evidência de trial/gate."""


def _utc(value: datetime, field: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field} deve ser datetime UTC aware")
    try:
        return to_utc(value)
    except NaiveDatetimeError as exc:
        raise ValueError(f"{field} deve ter timezone") from exc


def _hash(value: str, field: str) -> None:
    if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value.lower()):
        raise ValueError(f"{field} deve ser SHA-256 hexadecimal")


def _json_object(value: Mapping[str, Any] | None, field: str) -> Mapping[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise TypeError(f"{field} deve ser objeto JSON")
    try:
        json.dumps(dict(value), allow_nan=False, sort_keys=True)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} não é serializável em JSON") from exc
    return dict(value)


@dataclass(frozen=True)
class ObservationEnvelope:
    """Fato versionado de uma coleta, independente de qualquer experimento.

    `created_at` é a primeira vez que o fato entrou no arquivo; transições só
    alteram `updated_at` e `lifecycle_state`. Assim uma importação antiga não
    pode se disfarçar de observação nova e o `collection_run_id` nunca muda.
    """
    collection_run_id: str
    project: str
    domain: str
    canonical_event_id: str
    observed_at: datetime
    scheduled_at: datetime
    source: str
    source_record_id: str
    provenance_hash: str
    source_snapshot_hash: str
    code_commit: str
    core_version: str
    participants: Mapping[str, Any]
    competition: Mapping[str, Any]
    lifecycle_state: str = LifecycleState.DISCOVERED
    rejection_reason: str | None = None
    official_result: Mapping[str, Any] | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    schema_version: str = COLLECTION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for field in ("collection_run_id", "project", "domain", "canonical_event_id",
                      "source", "source_record_id", "code_commit", "core_version"):
            if not isinstance(getattr(self, field), str) or not getattr(self, field).strip():
                raise ValueError(f"{field} é obrigatório")
        if "trial" in self.collection_run_id.casefold():
            raise ValueError("collection_run_id não pode ser trial_id")
        if self.schema_version != COLLECTION_SCHEMA_VERSION:
            raise ValueError("schema_version COLLECTION_ONLY incompatível")
        if self.lifecycle_state not in _ALL:
            raise ValueError("lifecycle_state científico ou desconhecido")
        _hash(self.provenance_hash, "provenance_hash")
        _hash(self.source_snapshot_hash, "source_snapshot_hash")
        observed, scheduled = _utc(self.observed_at, "observed_at"), _utc(self.scheduled_at, "scheduled_at")
        created = _utc(self.created_at or observed, "created_at")
        updated = _utc(self.updated_at or created, "updated_at")
        if created < observed or updated < created:
            raise ValueError("created_at/updated_at não podem preceder o fato observado")
        if self.lifecycle_state == LifecycleState.COMPLETE and self.official_result is None:
            raise ValueError("COMPLETE exige official_result")
        if self.lifecycle_state == LifecycleState.OFFICIAL_RESULT_FOUND and self.official_result is None:
            raise ValueError("OFFICIAL_RESULT_FOUND exige official_result")
        if self.lifecycle_state in _REJECTION_STATES and not self.rejection_reason:
            raise ValueError("estado terminal de rejeição exige rejection_reason")
        participants = _json_object(self.participants, "participants")
        competition = _json_object(self.competition, "competition")
        official = _json_object(self.official_result, "official_result")
        if not participants or not competition:
            raise ValueError("participants e competition são obrigatórios")
        object.__setattr__(self, "observed_at", observed)
        object.__setattr__(self, "scheduled_at", scheduled)
        object.__setattr__(self, "created_at", created)
        object.__setattr__(self, "updated_at", updated)
        object.__setattr__(self, "participants", participants)
        object.__setattr__(self, "competition", competition)
        object.__setattr__(self, "official_result", official)

    @property
    def is_terminal(self) -> bool:
        return self.lifecycle_state in _TERMINAL

    def transition(self, state: str, *, at: datetime | None = None,
                   official_result: Mapping[str, Any] | None = None,
                   rejection_reason: str | None = None) -> "ObservationEnvelope":
        """Aplica a próxima transição, ou devolve o mesmo objeto no retry idempotente."""
        if state not in _ALL:
            raise CollectionTransitionError("estado científico ou desconhecido")
        if state == self.lifecycle_state:
            if official_result not in (None, self.official_result) or rejection_reason not in (None, self.rejection_reason):
                raise CollectionTransitionError("retry não pode alterar o fato arquivado")
            return self
        if self.is_terminal:
            raise CollectionTransitionError("estado terminal não aceita transições")
        if state in _ORDERED:
            expected = _ORDERED[_ORDERED.index(self.lifecycle_state) + 1] if self.lifecycle_state in _ORDERED and self.lifecycle_state != LifecycleState.COMPLETE else None
            if state != expected:
                raise CollectionTransitionError(f"transição inválida: {self.lifecycle_state} -> {state}")
        # Estados terminais operacionais podem encerrar qualquer etapa ativa.
        stamp = _utc(at or utcnow(), "at")
        if stamp < self.updated_at:
            raise CollectionTransitionError("transição não pode voltar no tempo")
        return replace(self, lifecycle_state=state,
                       official_result=official_result if official_result is not None else self.official_result,
                       rejection_reason=rejection_reason if rejection_reason is not None else self.rejection_reason,
                       updated_at=stamp)

    def to_dict(self) -> dict[str, Any]:
        return {"schema_version": self.schema_version, "collection_run_id": self.collection_run_id,
                "project": self.project, "domain": self.domain,
                "canonical_event_id": self.canonical_event_id, "observed_at": iso_z(self.observed_at),
                "scheduled_at": iso_z(self.scheduled_at), "source": self.source,
                "source_record_id": self.source_record_id, "provenance_hash": self.provenance_hash,
                "source_snapshot_hash": self.source_snapshot_hash, "code_commit": self.code_commit,
                "core_version": self.core_version, "participants": dict(self.participants),
                "competition": dict(self.competition), "lifecycle_state": self.lifecycle_state,
                "rejection_reason": self.rejection_reason, "official_result": self.official_result,
                "created_at": iso_z(self.created_at), "updated_at": iso_z(self.updated_at)}

    @classmethod
    def from_dict(cls, row: Mapping[str, Any]) -> "ObservationEnvelope":
        from predictor_core.kernel.timeindex import parse_iso
        data = dict(row)
        for field in ("observed_at", "scheduled_at", "created_at", "updated_at"):
            data[field] = parse_iso(data[field])
        return cls(**data)

    def as_scientific_trial(self) -> None:
        raise ScientificPromotionError("COLLECTION_ONLY nunca pode entrar em trial ou gate")


class CollectionArchive:
    """Histórico append-only de envelopes e transições COLLECTION_ONLY."""
    def __init__(self, path: str | Path):
        self.store = JsonlStore(path)

    def _events(self) -> Iterable[dict[str, Any]]:
        for row in self.store:
            if row.get("record_type") != "collection_transition":
                raise ValueError("arquivo contém registro que não é COLLECTION_ONLY")
            yield row

    def history(self, collection_run_id: str, canonical_event_id: str) -> list[ObservationEnvelope]:
        return [ObservationEnvelope.from_dict(row["envelope"]) for row in self._events()
                if row.get("collection_run_id") == collection_run_id and row.get("canonical_event_id") == canonical_event_id]

    def append(self, envelope: ObservationEnvelope, *, previous: ObservationEnvelope | None = None) -> ObservationEnvelope:
        history = self.history(envelope.collection_run_id, envelope.canonical_event_id)
        current = history[-1] if history else None
        if previous is not None and current != previous:
            raise CollectionTransitionError("predecessor não confere com histórico arquivado")
        if current is not None and envelope == current:
            return current
        if current is None and previous is not None:
            raise CollectionTransitionError("primeiro registro não pode ter predecessor")
        if current is not None:
            if envelope.created_at != current.created_at or envelope.collection_run_id != current.collection_run_id:
                raise CollectionTransitionError("coleta antiga não pode ser reclassificada como nova")
            if envelope.lifecycle_state == current.lifecycle_state:
                raise CollectionTransitionError("atualização sem transição é proibida")
            expected = current.transition(envelope.lifecycle_state, at=envelope.updated_at,
                                          official_result=envelope.official_result,
                                          rejection_reason=envelope.rejection_reason)
            if expected != envelope:
                raise CollectionTransitionError("envelope de transição diverge do contrato")
        self.store.append({"record_type": "collection_transition", "collection_only": True,
                           "collection_run_id": envelope.collection_run_id,
                           "canonical_event_id": envelope.canonical_event_id,
                           "previous_state": None if current is None else current.lifecycle_state,
                           "state": envelope.lifecycle_state, "envelope": envelope.to_dict()})
        return envelope


def aggregate_funnel(envelopes: Iterable[ObservationEnvelope], *,
                     project: str | None = None, collection_run_id: str | None = None,
                     start_at: datetime | None = None, end_at: datetime | None = None) -> dict[str, Any]:
    """Agrega o último estado de cada evento por projeto/run/janela observada."""
    start = _utc(start_at, "start_at") if start_at else None
    end = _utc(end_at, "end_at") if end_at else None
    latest: dict[tuple[str, str], ObservationEnvelope] = {}
    for item in envelopes:
        if project is not None and item.project != project:
            continue
        if collection_run_id is not None and item.collection_run_id != collection_run_id:
            continue
        if start and item.observed_at < start or end and item.observed_at >= end:
            continue
        key = (item.collection_run_id, item.canonical_event_id)
        if key not in latest or latest[key].updated_at <= item.updated_at:
            latest[key] = item
    states = {state: 0 for state in sorted(_ALL)}
    for item in latest.values():
        states[item.lifecycle_state] += 1
    return {"schema_version": COLLECTION_SCHEMA_VERSION, "collection_only": True,
            "project": project, "collection_run_id": collection_run_id,
            "window_start": None if start is None else iso_z(start),
            "window_end": None if end is None else iso_z(end),
            "events": len(latest), "states": states,
            "complete": states[LifecycleState.COMPLETE],
            "terminal": sum(states[s] for s in _TERMINAL)}
