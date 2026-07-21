"""Resilient, local ingestion primitives for Oracle's Elixir CSV snapshots.

The module deliberately stays in the LoL domain.  It has no dependency on the
shared core: source-specific CSV rules, retention, and freshness are not a
cross-domain contract.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import random
import shutil
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


SCHEMA_VERSION = "oracle-csv/1"
INGESTION_VERSION = "2026.07.resilient.1"
REQUIRED_COLUMNS = frozenset({"gameid", "league", "teamname", "date", "result"})
MAX_BYTES = 150 * 1024 * 1024


class IngestionError(RuntimeError):
    """Data cannot be trusted for publication or serving."""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _parse_time(value: str, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise IngestionError(f"{field} inválido: {value!r}") from exc
    if parsed.tzinfo is None:
        raise IngestionError(f"{field} precisa de timezone: {value!r}")
    return parsed.astimezone(timezone.utc)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_oracle_csv(path: Path, *, min_rows: int = 2) -> dict[str, object]:
    """Validate a bounded Oracle CSV before it can become a snapshot.

    It intentionally validates only the common download contract.  The local
    ``OracleProvider`` applies the stricter game/side aggregation rules later.
    """
    if not path.is_file() or path.stat().st_size == 0:
        raise IngestionError("arquivo ausente ou vazio")
    if path.stat().st_size > MAX_BYTES:
        raise IngestionError("arquivo excede limite de tamanho")
    try:
        with path.open("r", encoding="utf-8-sig", errors="strict", newline="") as handle:
            sample = handle.read(512).lstrip().casefold()
            if sample.startswith("<html") or "quota exceeded" in sample or "access denied" in sample:
                raise IngestionError("resposta HTML/erro não é CSV")
            handle.seek(0)
            reader = csv.DictReader(handle)
            columns = {name.strip().casefold() for name in (reader.fieldnames or []) if name}
            missing = REQUIRED_COLUMNS - columns
            if missing:
                raise IngestionError(f"schema sem colunas obrigatórias: {sorted(missing)}")
            rows, dates, game_ids = 0, [], set()
            for row in reader:
                rows += 1
                game_id = (row.get("gameid") or "").strip()
                if not game_id or not (row.get("league") or "").strip() or not (row.get("teamname") or "").strip():
                    raise IngestionError("linha com identidade/cobertura ausente")
                if (row.get("result") or "").strip() not in {"0", "1"}:
                    raise IngestionError("resultado fora do tipo binário esperado")
                if game_id in game_ids and rows <= 2:
                    # OE legitimately has multiple team/player rows per game;
                    # duplicates are checked during aggregation, not here.
                    pass
                game_ids.add(game_id)
                raw_date = (row.get("date") or "").strip()
                if not raw_date:
                    raise IngestionError("linha sem timestamp")
                try:
                    dt = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
                except ValueError as exc:
                    raise IngestionError(f"timestamp inválido: {raw_date!r}") from exc
                dates.append(dt.date().isoformat())
            if rows < min_rows:
                raise IngestionError(f"amostra insuficiente: {rows} < {min_rows}")
    except (OSError, UnicodeError, csv.Error) as exc:
        raise IngestionError(f"CSV ilegível: {exc}") from exc
    return {
        "row_count": rows,
        "temporal_range_start": min(dates),
        "temporal_range_end": max(dates),
        "validations_executed": [
            "non_empty", "size_limit", "utf8", "not_html", "required_columns",
            "minimum_rows", "identity_coverage", "timestamps",
        ],
    }


@dataclass(frozen=True)
class DownloadPolicy:
    timeout_seconds: int = 30
    max_attempts: int = 3
    max_execution_seconds: int = 90
    base_backoff_seconds: float = 0.25
    user_agent: str = "lol-predictor-ingestion/1.0 (+local-resilient-cache)"


class SnapshotStore:
    """Immutable payload directories plus an atomically replaced JSON pointer."""

    def __init__(self, root: Path | str):
        self.root = Path(root)
        self.snapshots = self.root / "snapshots"
        self.pointer = self.root / "current.json"
        self.cache_state = self.root / "cache_state.json"

    def current(self) -> dict[str, object] | None:
        try:
            value = json.loads(self.pointer.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else None
        except (OSError, ValueError):
            return None

    def current_payload(self) -> Path | None:
        current = self.current()
        if not current or not isinstance(current.get("snapshot"), str):
            return None
        payload = self.snapshots / current["snapshot"] / "payload.csv"
        return payload if payload.is_file() else None

    def current_metadata(self) -> dict[str, object] | None:
        current = self.current()
        if not current or not isinstance(current.get("snapshot"), str):
            return None
        metadata = self.snapshots / current["snapshot"] / "metadata.json"
        try:
            value = json.loads(metadata.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else None
        except (OSError, ValueError):
            return None

    @staticmethod
    def _atomic_json(path: Path, value: Mapping[str, object]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(value, handle, ensure_ascii=False, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def publish(self, source_file: Path, *, source: str, source_headers: Mapping[str, str] | None = None) -> dict[str, object]:
        summary = validate_oracle_csv(source_file)
        previous = self.current_metadata()
        if previous and isinstance(previous.get("temporal_range_end"), str):
            if str(summary["temporal_range_end"]) < previous["temporal_range_end"]:
                raise IngestionError("regressão temporal: candidato termina antes do snapshot vigente")
        digest = _sha256(source_file)
        now = _utc_now()
        snapshot_id = f"{now.strftime('%Y%m%dT%H%M%SZ')}-{digest[:12]}"
        target = self.snapshots / snapshot_id
        if target.exists():
            raise IngestionError(f"snapshot imutável já existe: {snapshot_id}")
        target.mkdir(parents=True)
        payload = target / "payload.csv"
        try:
            with source_file.open("rb") as src, payload.open("xb") as dst:
                shutil.copyfileobj(src, dst, length=1024 * 1024)
                dst.flush()
                os.fsync(dst.fileno())
            headers = {str(k).casefold(): str(v) for k, v in (source_headers or {}).items()}
            metadata: dict[str, object] = {
                "source": source,
                "retrieved_at": _iso(now),
                "source_last_modified": headers.get("last-modified"),
                "sha256": digest,
                "schema_version": SCHEMA_VERSION,
                **summary,
                "latest_patch": None,
                "ingestion_version": INGESTION_VERSION,
                "source_status": "PUBLISHED",
            }
            self._atomic_json(target / "metadata.json", metadata)
            self._atomic_json(self.pointer, {"snapshot": snapshot_id, "published_at": _iso(now), "sha256": digest})
            return metadata
        except Exception:
            # No pointer changed before the final replace.  The incomplete
            # directory is intentionally left for forensic inspection.
            raise


def assert_fresh_snapshot(root: Path | str, *, max_age_hours: int, now: datetime | None = None) -> dict[str, object]:
    store = SnapshotStore(root)
    metadata = store.current_metadata()
    payload = store.current_payload()
    if metadata is None or payload is None:
        raise IngestionError("nenhum snapshot publicado; serving bloqueado")
    required = {"source", "retrieved_at", "sha256", "schema_version", "row_count", "source_status"}
    missing = required - set(metadata)
    if missing or metadata.get("source_status") != "PUBLISHED":
        raise IngestionError(f"metadata de snapshot incompleto: {sorted(missing)}")
    if metadata.get("sha256") != _sha256(payload):
        raise IngestionError("hash do snapshot não confere; serving bloqueado")
    reference = now or _utc_now()
    age = reference - _parse_time(str(metadata["retrieved_at"]), "retrieved_at")
    if age < timedelta(minutes=-5) or age > timedelta(hours=max_age_hours):
        raise IngestionError(f"snapshot fora da janela de frescor ({age.total_seconds() / 3600:.1f}h)")
    return metadata


class ConditionalDownloader:
    """Bounded HTTP fetcher with persisted validators and no partial publish."""

    def __init__(self, store: SnapshotStore, *, policy: DownloadPolicy = DownloadPolicy(),
                 opener: Callable[..., object] = urlopen, sleeper: Callable[[float], None] = time.sleep,
                 clock: Callable[[], float] = time.monotonic, rng: Callable[[], float] = random.random):
        self.store, self.policy = store, policy
        self.opener, self.sleeper, self.clock, self.rng = opener, sleeper, clock, rng

    def _state(self) -> dict[str, object]:
        try:
            state = json.loads(self.store.cache_state.read_text(encoding="utf-8"))
            return state if isinstance(state, dict) else {}
        except (OSError, ValueError):
            return {}

    def _delay(self, attempt: int, headers: Mapping[str, str] | None = None) -> float:
        retry_after = (headers or {}).get("Retry-After") or (headers or {}).get("retry-after")
        if retry_after:
            try:
                return min(float(retry_after), 10.0)
            except ValueError:
                try:
                    return min(max(0.0, (parsedate_to_datetime(retry_after) - _utc_now()).total_seconds()), 10.0)
                except (TypeError, ValueError):
                    pass
        return min(5.0, self.policy.base_backoff_seconds * (2 ** (attempt - 1)) + self.rng() * 0.1)

    def fetch(self, url: str) -> tuple[str, dict[str, object] | None]:
        state = self._state()
        headers = {"User-Agent": self.policy.user_agent, "Accept": "text/csv,*/*;q=0.1"}
        if state.get("url") == url:
            if isinstance(state.get("etag"), str):
                headers["If-None-Match"] = state["etag"]
            if isinstance(state.get("last_modified"), str):
                headers["If-Modified-Since"] = state["last_modified"]
        started = self.clock()
        final_error = "sem tentativa"
        for attempt in range(1, self.policy.max_attempts + 1):
            temporary: Path | None = None
            try:
                request = Request(url, headers=headers)
                with self.opener(request, timeout=self.policy.timeout_seconds) as response:
                    response_headers = dict(getattr(response, "headers", {}) or {})
                    self.store.root.mkdir(parents=True, exist_ok=True)
                    fd, name = tempfile.mkstemp(prefix="download-", suffix=".tmp", dir=self.store.root)
                    temporary = Path(name)
                    total = 0
                    with os.fdopen(fd, "wb") as handle:
                        while block := response.read(1024 * 1024):
                            total += len(block)
                            if total > MAX_BYTES:
                                raise IngestionError("download excede limite de tamanho")
                            handle.write(block)
                        handle.flush()
                        os.fsync(handle.fileno())
                previous = self.store.current_metadata()
                validate_oracle_csv(temporary)
                if previous and previous.get("sha256") == _sha256(temporary):
                    self.store._atomic_json(self.store.cache_state, {
                        "url": url, "etag": response_headers.get("ETag") or response_headers.get("Etag"),
                        "last_modified": response_headers.get("Last-Modified"), "sha256": previous["sha256"],
                        "last_success_at": _iso(_utc_now()),
                    })
                    return "UNCHANGED", previous
                metadata = self.store.publish(temporary, source=url, source_headers=response_headers)
                self.store._atomic_json(self.store.cache_state, {
                    "url": url, "etag": response_headers.get("ETag") or response_headers.get("Etag"),
                    "last_modified": response_headers.get("Last-Modified"), "sha256": metadata["sha256"],
                    "last_success_at": _iso(_utc_now()),
                })
                return "PUBLISHED", metadata
            except HTTPError as exc:
                if exc.code == 304 and self.store.current_payload() is not None:
                    exc.close()
                    return "NOT_MODIFIED", self.store.current_metadata()
                final_error = f"HTTP {exc.code}"
                retryable, response_headers = exc.code == 429 or 500 <= exc.code <= 599, dict(exc.headers or {})
                exc.close()
            except (URLError, TimeoutError, ConnectionError, OSError, IngestionError) as exc:
                final_error, response_headers = str(exc), {}
                retryable = not isinstance(exc, IngestionError) or not final_error.startswith((
                    "resposta HTML", "schema", "linha", "timestamp", "amostra", "arquivo", "regressão", "snapshot"))
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
            if not retryable or attempt >= self.policy.max_attempts or self.clock() - started >= self.policy.max_execution_seconds:
                break
            delay = self._delay(attempt, response_headers)
            if self.clock() - started + delay > self.policy.max_execution_seconds:
                break
            self.sleeper(delay)
        self.store._atomic_json(self.store.root / "last_failure.json", {
            "status": "FAILED", "url": url, "error": final_error,
            "recorded_at": _iso(_utc_now()), "attempts": self.policy.max_attempts,
        })
        raise IngestionError(f"download falhou após tentativas limitadas: {final_error}")
