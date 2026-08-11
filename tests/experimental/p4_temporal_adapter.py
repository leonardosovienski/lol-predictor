"""P4-B experimental adapter for the canonical LoL EWC ledger."""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from predictor_core.data.contracts import PredictionPoint
from predictor_core.measurement.replay import replay


class ExperimentalTemporalError(ValueError):
    """A synthetic LoL temporal invariant was violated."""


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ExperimentalTemporalError("value must be finite canonical JSON") from exc


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _time(value: Any, field: str) -> datetime:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ExperimentalTemporalError(f"invalid {field}") from exc
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ExperimentalTemporalError(f"{field} must be timezone-aware")
    return value.astimezone(UTC)


@dataclass(frozen=True)
class ExperimentalLolTemporalRecord:
    """Private test representation; deliberately not a Core/domain API."""

    schema_version: str
    prediction_id: str
    predicted_at: str
    cutoff_at: str
    event_start_at: str
    matures_at: str
    result_available_at: str
    matured_at: str
    prediction_payload_hash: str
    result_payload_hash: str
    metric_name: str
    metric_scale: str
    metric_value: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def adapt_ewc_records(
    pre: dict[str, Any],
    matured: dict[str, Any],
    *,
    result_available_at: datetime,
    expected_result_payload_hash: str | None = None,
) -> ExperimentalLolTemporalRecord:
    """Validate a canonical EWC PRE_EVENT/MATURED pair without changing it."""
    if pre.get("lifecycle_status") != "PRE_EVENT":
        raise ExperimentalTemporalError("expected PRE_EVENT record")
    if matured.get("lifecycle_status") != "MATURED":
        raise ExperimentalTemporalError("expected MATURED record")
    if any(pre.get(field) is not None for field in ("result", "brier", "correct")):
        raise ExperimentalTemporalError("PRE_EVENT contains post-event data")
    if pre.get("prediction_id") != matured.get("prediction_id"):
        raise ExperimentalTemporalError("prediction identity mismatch")

    permitted_changes = {"lifecycle_status", "matured_at", "result", "brier", "correct"}
    for field, value in pre.items():
        if field not in permitted_changes and matured.get(field) != value:
            raise ExperimentalTemporalError(f"retroactive PRE_EVENT mutation: {field}")

    predicted = _time(pre.get("predicted_at"), "predicted_at")
    event_start = _time(pre.get("scheduled_at"), "scheduled_at")
    matures_at = _time(pre.get("matures_at"), "matures_at")
    available = _time(result_available_at, "result_available_at")
    matured_at = _time(matured.get("matured_at"), "matured_at")
    if predicted >= event_start:
        raise ExperimentalTemporalError("predicted_at must be before scheduled_at cutoff")
    if matures_at <= event_start:
        raise ExperimentalTemporalError("matures_at must be after event_start_at")
    if available < event_start:
        raise ExperimentalTemporalError("result_available_at must be at or after event_start_at")
    if available <= predicted:
        raise ExperimentalTemporalError("result must not be available at prediction time")
    if matured_at < available:
        raise ExperimentalTemporalError("matured_at must be at or after result_available_at")

    point = PredictionPoint(predicted_at=predicted, matures_at=matures_at, value=pre.get("value"))
    if not point.is_mature(matured_at):
        raise ExperimentalTemporalError("premature maturation")

    result = matured.get("result")
    if not isinstance(result, dict) or result.get("winner") not in (pre.get("team_a"), pre.get("team_b")):
        raise ExperimentalTemporalError("valid observed result is required")
    metric = matured.get("brier")
    if not isinstance(metric, (int, float)) or not math.isfinite(float(metric)):
        raise ExperimentalTemporalError("native metric must be finite")
    prediction_hash = _hash(pre)
    result_hash = _hash(result)
    if expected_result_payload_hash is not None and result_hash != expected_result_payload_hash:
        raise ExperimentalTemporalError("result payload hash mismatch")

    def utc_text(value: datetime) -> str:
        return value.isoformat().replace("+00:00", "Z")

    return ExperimentalLolTemporalRecord(
        schema_version="p4-lol-temporal-experiment/1",
        prediction_id=pre["prediction_id"],
        predicted_at=utc_text(predicted),
        cutoff_at=utc_text(event_start),
        event_start_at=utc_text(event_start),
        matures_at=utc_text(matures_at),
        result_available_at=utc_text(available),
        matured_at=utc_text(matured_at),
        prediction_payload_hash=prediction_hash,
        result_payload_hash=result_hash,
        metric_name="series_brier_multiclass",
        metric_scale="lol-native-two-outcome-sum-of-squared-errors",
        metric_value=float(metric),
    )


def replay_record(
    record: ExperimentalLolTemporalRecord,
    *,
    input_hash: str,
    expected_input_hash: str | None = None,
) -> dict[str, Any]:
    if expected_input_hash is not None and input_hash != expected_input_hash:
        raise ExperimentalTemporalError("replay input hash mismatch")
    event = {"input_hash": input_hash, "record": record.to_dict()}
    return replay([event], lambda past: past.latest, key=lambda row: row["record"]["predicted_at"])[0]


def write_immutable_golden(path: Path, value: dict[str, Any]) -> None:
    encoded = _canonical(value) + b"\n"
    if path.exists():
        if path.read_bytes() != encoded:
            raise ExperimentalTemporalError("immutable golden overwrite rejected")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)
