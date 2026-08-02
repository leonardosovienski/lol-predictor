"""Frozen H4 prospective-shadow cohort, status and deterministic evaluation.

This is intentionally LoL-local: source identity, Polymarket provenance and
the pre-registered H4 criteria do not belong in predictor_core.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from random import Random
from typing import Any

SIGNAL_SCHEMA = "lol-h4-signal/1.0"
GATE_SCHEMA = "lol-h4-market-gate/1.0"
CLOSURE_SCHEMA = "lol-h4-closure/1.0"
CLOSURE_TRIAL = "h4-lol-market-shadow-prospectivo-v2"
# Registro canônico de encerramento. Some-lo NÃO reabre a coorte: `closure_status`
# falha fechado neste caminho específico (espelha a garantia equivalente do
# cs-predictor, `beyond_market_closure.closure_record`). Caminhos de fixture
# continuam devolvendo None quando ausentes, para não travar teste em tmp_path.
DEFAULT_CLOSURE_RECORD = Path(__file__).resolve().parents[1] / "data" / "h4_v2_closure.json"
# Reabrir exige decisão humana auditável, nunca edição silenciosa de status.
REOPENING_REQUIRED_FIELDS = frozenset({"reopened_at_utc", "reopening_decision", "supersedes_commit"})


class H4Error(ValueError):
    pass


def _dt(value: Any, field: str) -> datetime:
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise H4Error(f"{field} inválido") from exc
    if result.tzinfo is None:
        raise H4Error(f"{field} sem timezone")
    return result.astimezone(UTC)


def _finite(value: Any, field: str, *, lower: float = 0.0, upper: float = 1.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise H4Error(f"{field} inválido") from exc
    if not math.isfinite(result) or not lower < result < upper:
        raise H4Error(f"{field} fora do intervalo")
    return result


def _hash(value: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, sort_keys=True, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def build_signal(
    quote: dict[str, Any],
    *,
    trial_id: str,
    code_commit: str,
    competition_id: str,
    competition_name: str,
    region: str | None,
    tournament: str | None,
    split: str | None,
    patch: str | None,
) -> dict[str, Any]:
    """Make one frozen signal from a pre-event quote; never infer competition."""
    if not competition_id or not competition_name:
        raise H4Error("competição/proveniência ausente; sinal inelegível")
    required = (
        "event_id",
        "team_a",
        "team_b",
        "observed_at",
        "published_at",
        "scheduled_at",
        "model_probability_a",
        "model_probability_b",
        "probability_a",
        "probability_b",
        "decimal_a",
        "decimal_b",
        "ratings_sha256",
        "source",
        "market_id",
        "condition_id",
        "format",
    )
    missing = [key for key in required if quote.get(key) in (None, "")]
    if missing:
        raise H4Error(f"quote sem campos de provenance: {missing}")
    predicted, available, start = (
        _dt(quote["observed_at"], "predicted_at"),
        _dt(quote["published_at"], "available_at"),
        _dt(quote["scheduled_at"], "event_start_at"),
    )
    if not available <= predicted < start:
        raise H4Error("violação temporal do sinal")
    pa, pb = (
        _finite(quote["model_probability_a"], "model_probability_a"),
        _finite(quote["model_probability_b"], "model_probability_b"),
    )
    ma, mb = (
        _finite(quote["probability_a"], "market_probability_a"),
        _finite(quote["probability_b"], "market_probability_b"),
    )
    if abs(pa + pb - 1) > 1e-6 or abs(ma + mb - 1) > 1e-6:
        raise H4Error("probabilidades não normalizadas")
    selection = "team_a" if abs(pa - ma) >= abs(pb - mb) else "team_b"
    model_p, market_p = (pa, ma) if selection == "team_a" else (pb, mb)
    odds = float(quote["decimal_a"] if selection == "team_a" else quote["decimal_b"])
    if not math.isfinite(odds) or odds <= 1:
        raise H4Error("odds capturada inválida")
    canonical_event_id = f"polymarket:{quote['condition_id']}"
    provenance = {
        "trial_id": trial_id,
        "code_commit": code_commit,
        "source": quote["source"],
        "source_event_id": str(quote["event_id"]),
        "market_id": str(quote["market_id"]),
        "condition_id": str(quote["condition_id"]),
        "snapshot_hash": quote["ratings_sha256"],
        "available_at": available.isoformat(),
        "retrieved_at": predicted.isoformat(),
    }
    signal_id = _hash(
        {
            "canonical_event_id": canonical_event_id,
            "selection": selection,
            "predicted_at": predicted.isoformat(),
            "provenance": provenance,
        }
    )
    return {
        "schema_version": SIGNAL_SCHEMA,
        "signal_id": signal_id,
        "trial_id": trial_id,
        "model_version": quote.get("model_name", "elo-h1-series"),
        "code_commit": code_commit,
        "event_id": str(quote["event_id"]),
        "canonical_event_id": canonical_event_id,
        "competition_id": competition_id,
        "competition_name": competition_name,
        "region": region,
        "tournament": tournament,
        "split": split,
        "patch": patch,
        "team_a_id": quote["team_a"],
        "team_b_id": quote["team_b"],
        "predicted_at": predicted.isoformat(),
        "event_start_at": start.isoformat(),
        "source": quote["source"],
        "source_event_id": str(quote["event_id"]),
        "retrieved_at": predicted.isoformat(),
        "available_at": available.isoformat(),
        "snapshot_hash": quote["ratings_sha256"],
        "snapshot_status": "FROZEN_VALID",
        "provenance_hash": _hash(provenance),
        "market": "series_moneyline",
        "selection": selection,
        "model_probability": model_p,
        "market_probability": market_p,
        "captured_odds": odds,
        "odds_captured_at": predicted.isoformat(),
        "result": None,
        "result_available_at": None,
        "settlement_status": "PENDING",
    }


def _trial(trials_path: Path) -> dict[str, Any]:
    return next(
        row
        for row in json.loads(trials_path.read_text(encoding="utf-8"))
        if row["name"] == "h4-lol-market-shadow-prospectivo-v2"
    )


def closure_status(path: Path) -> dict[str, Any] | None:
    """Devolve o encerramento humano que BLOQUEIA a coorte; None se ela está aberta.

    Malformado, ilegível ou com status desconhecido falha fechado. Reabertura só
    vale com `REOPENED_BY_HUMAN_DECISION` E os três campos de decisão auditável —
    declarar o status sem eles é registro inválido, não coorte aberta.

    Remover o registro canônico (`DEFAULT_CLOSURE_RECORD`) também falha fechado:
    antes de 2026-07-25 o arquivo ausente devolvia None e reabria a coorte por
    apagamento, destruindo os contadores e hashes preservados no próprio registro.
    """
    if not path.exists():
        if Path(path).resolve() == DEFAULT_CLOSURE_RECORD.resolve():
            raise H4Error("registro de encerramento H4 ausente; a coorte não pode ser reaberta por remoção de arquivo")
        return None
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise H4Error("registro de encerramento H4 ilegível; reinício bloqueado") from exc
    status = record.get("scientific_status")
    if (
        record.get("schema_version") != CLOSURE_SCHEMA
        or record.get("trial") != CLOSURE_TRIAL
        or status not in {"CLOSED_BY_HUMAN_DECISION", "REOPENED_BY_HUMAN_DECISION"}
        or record.get("operational_status") != "NO_GO"
    ):
        raise H4Error("registro de encerramento H4 inválido; reinício bloqueado")
    if status == "REOPENED_BY_HUMAN_DECISION":
        if not REOPENING_REQUIRED_FIELDS.issubset(record):
            raise H4Error("reabertura sem nova decisão humana auditável")
        return None  # coorte reaberta: nada a bloquear
    return record


def assert_h4_open(closure_path: Path) -> None:
    if closure_status(closure_path) is not None:
        raise H4Error("H4 V2 encerrada por decisão humana; nova decisão auditável é obrigatória")


def _rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    except (OSError, json.JSONDecodeError) as exc:
        raise H4Error("coorte JSONL ilegível") from exc


def validate_signal(row: dict[str, Any], *, trial_id: str) -> None:
    required = {
        "signal_id",
        "trial_id",
        "model_version",
        "code_commit",
        "event_id",
        "canonical_event_id",
        "competition_id",
        "competition_name",
        "predicted_at",
        "event_start_at",
        "source",
        "source_event_id",
        "retrieved_at",
        "available_at",
        "snapshot_hash",
        "snapshot_status",
        "schema_version",
        "provenance_hash",
        "market",
        "selection",
        "model_probability",
        "market_probability",
        "captured_odds",
        "odds_captured_at",
        "settlement_status",
    }
    missing = [x for x in required if row.get(x) in (None, "")]
    if missing or row.get("schema_version") != SIGNAL_SCHEMA or row.get("trial_id") != trial_id:
        raise H4Error(f"schema/provenance inválido: {missing}")
    if (
        not isinstance(row["snapshot_hash"], str)
        or len(row["snapshot_hash"]) != 64
        or row["snapshot_status"] != "FROZEN_VALID"
    ):
        raise H4Error("snapshot stale/inválido")
    predicted, available, start = (
        _dt(row["predicted_at"], "predicted_at"),
        _dt(row["available_at"], "available_at"),
        _dt(row["event_start_at"], "event_start_at"),
    )
    if (
        not available <= predicted < start
        or _dt(row["retrieved_at"], "retrieved_at") != predicted
        or _dt(row["odds_captured_at"], "odds_captured_at") != predicted
    ):
        raise H4Error("violação temporal")
    _finite(row["model_probability"], "model_probability")
    _finite(row["market_probability"], "market_probability")
    if not math.isfinite(float(row["captured_odds"])) or float(row["captured_odds"]) <= 1:
        raise H4Error("odds inválida")


def cohort_status(
    signals_path: Path, trials_path: Path, *, now: datetime | None = None, closure_path: Path | None = None
) -> dict[str, Any]:
    trial, observed = _trial(trials_path), (now or datetime.now(UTC)).astimezone(UTC)
    if closure_path is not None:
        closed = closure_status(closure_path)
        if closed is not None:
            return {
                "trial": trial["name"],
                "registered_at": trial["registered_at"],
                "state": "CLOSED_BY_HUMAN_DECISION",
                "decision_ready": False,
                "operational_status": "NO_GO",
                "closure": closed,
            }
    p, start = trial["params"], _dt(trial["params"]["collection_start_exclusive"], "collection_start")
    rows, issues = _rows(signals_path), []
    valid = []
    for row in rows:
        try:
            validate_signal(row, trial_id=trial["name"])
            if _dt(row["predicted_at"], "predicted_at") <= start:
                raise H4Error("pré-coorte")
            valid.append(row)
        except H4Error as exc:
            issues.append(str(exc))
    event_counts = Counter(row["canonical_event_id"] for row in valid)
    if any(count > 1 for count in event_counts.values()):
        issues.append("múltiplos sinais para o mesmo evento")
    models = {row["model_version"] for row in valid}
    if len(models) > 1:
        issues.append("modelo alterado na janela")
    mature = [row for row in valid if _dt(row["event_start_at"], "event_start_at") < observed]
    settled = [row for row in mature if row.get("settlement_status") == "OFFICIAL" and row.get("result") in (0, 1)]
    if len(settled) != len(mature):
        issues.append("eventos passados sem resultado oficial persistido")
    days = max(0, (observed - start).total_seconds() / 86400)
    competitions = sorted({row["competition_id"] for row in settled})
    counts = {
        "matured_matches": len(settled),
        "calendar_days": days,
        "eligible_signals": len(valid),
        "competitions": competitions,
        "competition_count": len(competitions),
        "raw_signals": len(rows),
    }
    if issues:
        state = "DATA_QUALITY_BLOCKED"
    elif days < p["min_calendar_days"]:
        state = "WAITING_FOR_TIME_WINDOW"
    elif len(settled) < p["min_matured_matches"]:
        state = "WAITING_FOR_MATURED_EVENTS"
    elif len(valid) < p["min_shadow_signals"]:
        state = "WAITING_FOR_SIGNALS"
    elif len(competitions) < p["min_competitions"]:
        state = "WAITING_FOR_COMPETITION_COVERAGE"
    else:
        state = "READY_FOR_EVALUATION"
    return {
        "trial": trial["name"],
        "registered_at": trial["registered_at"],
        "state": state,
        "decision_ready": state == "READY_FOR_EVALUATION",
        "issues": sorted(set(issues)),
        "requirements": {
            "matured_matches": p["min_matured_matches"],
            "calendar_days": p["min_calendar_days"],
            "eligible_signals": p["min_shadow_signals"],
            "competitions": p["min_competitions"],
        },
        **counts,
    }


def _bootstrap(values: list[tuple[float, float]], *, seed: int = 13, n: int = 2000) -> dict[str, list[float]]:
    rng, size = Random(seed), len(values)
    brier, roi = [], []
    for _ in range(n):
        sample = [values[rng.randrange(size)] for _ in range(size)]
        brier.append(sum(x for x, _ in sample) / size)
        roi.append(sum(y for _, y in sample) / size)
    brier.sort()
    roi.sort()
    return {
        "brier_difference_ci95": [brier[int(0.025 * n)], brier[int(0.975 * n) - 1]],
        "roi_ci95": [roi[int(0.025 * n)], roi[int(0.975 * n) - 1]],
    }


def evaluate(
    signals_path: Path,
    trials_path: Path,
    output: Path,
    *,
    now: datetime | None = None,
    code_commit: str = "UNKNOWN",
    closure_path: Path | None = None,
) -> dict[str, Any]:
    if closure_path is not None:
        assert_h4_open(closure_path)
    state = cohort_status(signals_path, trials_path, now=now)
    if state["state"] != "READY_FOR_EVALUATION":
        raise H4Error(f"H4 não está pronto: {state['state']}")
    trial, rows = _trial(trials_path), _rows(signals_path)
    current = (now or datetime.now(UTC)).astimezone(UTC)
    eligible = [
        r
        for r in rows
        if _dt(r["event_start_at"], "event_start_at") < current and r.get("settlement_status") == "OFFICIAL"
    ]
    diffs, rois, model_briers, market_briers, log_losses = [], [], [], [], []
    for r in eligible:
        y, pm, pk, odds = (
            int(r["result"]),
            float(r["model_probability"]),
            float(r["market_probability"]),
            float(r["captured_odds"]),
        )
        model_briers.append((pm - y) ** 2)
        market_briers.append((pk - y) ** 2)
        diffs.append((pm - y) ** 2 - (pk - y) ** 2)
        log_losses.append(-(y * math.log(pm) + (1 - y) * math.log(1 - pm)))
        rois.append((odds - 1) if y else -1)
    boot = _bootstrap(list(zip(diffs, rois, strict=False)))
    bci, rci = boot["brier_difference_ci95"], boot["roi_ci95"]
    if bci[1] < 0 and rci[0] > 0:
        verdict = "GATE_PASSED_FOR_PROSPECTIVE_SHADOW"
    elif bci[0] > 0 or rci[1] < 0:
        verdict = "NO_GO_CONFIRMED"
    else:
        verdict = "INCONCLUSIVE"
    comp_counts = Counter(r["competition_id"] for r in eligible)
    total = len(eligible)
    equity, peak, drawdown = 0.0, 0.0, 0.0
    for value in rois:
        equity += value
        peak = max(peak, equity)
        drawdown = min(drawdown, equity - peak)
    calibration = [
        {
            "bin": f"{i / 5:.1f}-{(i + 1) / 5:.1f}",
            "n": sum(i / 5 <= float(r["model_probability"]) < (i + 1) / 5 for r in eligible),
        }
        for i in range(5)
    ]
    gate = {
        "schema_version": GATE_SCHEMA,
        "trial": trial["name"],
        "verdict": verdict,
        "evaluated_at": current.isoformat(),
        "code_commit": code_commit,
        "criteria": state["requirements"],
        "matured_matches": total,
        "required_matured_matches": trial["params"]["min_matured_matches"],
        "calendar_days": state["calendar_days"],
        "required_calendar_days": trial["params"]["min_calendar_days"],
        "eligible_signals": state["eligible_signals"],
        "competition_count": len(comp_counts),
        "competitions": dict(sorted(comp_counts.items())),
        "hhi": sum((n / total) ** 2 for n in comp_counts.values()),
        "brier_model": sum(model_briers) / total,
        "brier_market": sum(market_briers) / total,
        "paired_brier_difference": sum(diffs) / total,
        "log_loss_model": sum(log_losses) / total,
        "shadow_roi": sum(rois) / total,
        "max_drawdown_units": drawdown,
        "calibration": calibration,
        "bootstrap": boot,
        "clv": None,
        "coverage": total / state["eligible_signals"],
        "signals_sha256": hashlib.sha256(signals_path.read_bytes()).hexdigest(),
        "status": state,
    }
    _atomic_json(output, gate)
    return gate
