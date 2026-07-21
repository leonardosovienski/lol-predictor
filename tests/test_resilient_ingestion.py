from __future__ import annotations

import io
import json
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError

import pytest

from src.data.ingestion import (
    ConditionalDownloader, DownloadPolicy, IngestionError, SnapshotStore,
    assert_fresh_snapshot, validate_oracle_csv,
)


class Response(io.BytesIO):
    def __init__(self, value: bytes, headers: dict[str, str] | None = None):
        super().__init__(value)
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


def csv_bytes(*, date: str = "2026-07-20", rows: int = 2) -> bytes:
    header = "gameid,league,teamname,date,result\n"
    body = "".join(f"g{i},LCK,T{i},{date},1\n" for i in range(rows))
    return (header + body).encode()


def write_csv(tmp_path: Path, value: bytes | None = None) -> Path:
    path = tmp_path / "source.csv"
    path.write_bytes(csv_bytes() if value is None else value)
    return path


def test_200_publishes_metadata_and_conditional_headers(tmp_path):
    store = SnapshotStore(tmp_path / "ingestion")
    seen = []

    def opener(request, **_kwargs):
        seen.append(dict(request.header_items()))
        return Response(csv_bytes(), {"ETag": '"v1"', "Last-Modified": "Mon, 20 Jul 2026 00:00:00 GMT"})

    status, metadata = ConditionalDownloader(store, opener=opener).fetch("https://source.example/oe.csv")
    assert status == "PUBLISHED" and metadata["row_count"] == 2
    assert {"source", "retrieved_at", "source_last_modified", "sha256", "schema_version", "temporal_range_start", "temporal_range_end", "row_count", "latest_patch", "validations_executed", "ingestion_version", "source_status"} <= set(metadata)
    status, _ = ConditionalDownloader(store, opener=opener).fetch("https://source.example/oe.csv")
    assert status == "UNCHANGED"
    assert any(key.casefold() == "if-none-match" for key in seen[-1])


def test_304_preserves_current_snapshot(tmp_path):
    store = SnapshotStore(tmp_path / "ingestion")
    store.publish(write_csv(tmp_path), source="fixture")
    before = store.current()

    def opener(*_args, **_kwargs):
        raise HTTPError("https://source.example", 304, "not modified", {}, None)

    status, metadata = ConditionalDownloader(store, opener=opener).fetch("https://source.example")
    assert status == "NOT_MODIFIED" and metadata is not None and store.current() == before


def test_same_hash_and_changed_hash_are_explicit_snapshots(tmp_path):
    store = SnapshotStore(tmp_path / "ingestion")
    first = store.publish(write_csv(tmp_path), source="fixture")
    with pytest.raises(IngestionError, match="já existe"):
        store.publish(write_csv(tmp_path), source="fixture")
    changed = write_csv(tmp_path, csv_bytes(date="2026-07-21"))
    second = store.publish(changed, source="fixture")
    assert first["sha256"] != second["sha256"]


def test_429_honours_bounded_retry_after(tmp_path):
    store = SnapshotStore(tmp_path / "ingestion")
    answers = iter([
        HTTPError("https://source.example", 429, "slow", {"Retry-After": "1"}, None),
        Response(csv_bytes()),
    ])
    waits = []

    def opener(*_args, **_kwargs):
        answer = next(answers)
        if isinstance(answer, Exception):
            raise answer
        return answer

    status, _ = ConditionalDownloader(store, opener=opener, sleeper=waits.append).fetch("https://source.example")
    assert status == "PUBLISHED" and waits == [1.0]


def test_500_timeout_and_interrupted_response_fail_closed(tmp_path):
    store = SnapshotStore(tmp_path / "ingestion")
    policy = DownloadPolicy(max_attempts=2, base_backoff_seconds=0)
    calls = 0

    def failing(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise HTTPError("https://source.example", 500, "error", {}, None)
        raise TimeoutError("deadline")

    with pytest.raises(IngestionError, match="tentativas limitadas"):
        ConditionalDownloader(store, policy=policy, opener=failing, sleeper=lambda _x: None).fetch("https://source.example")
    assert json.loads((store.root / "last_failure.json").read_text())["status"] == "FAILED"


@pytest.mark.parametrize("bad", [b"", b"<html>quota exceeded</html>", b"gameid,league\ng,LCK\n", b"gameid,league,teamname,date,result\ng,LCK,T1,nope,1\n"])
def test_empty_html_schema_and_timestamp_are_rejected(tmp_path, bad):
    path = write_csv(tmp_path, bad)
    with pytest.raises(IngestionError):
        validate_oracle_csv(path)


def test_stale_or_invalid_snapshot_blocks_serving(tmp_path):
    store = SnapshotStore(tmp_path / "ingestion")
    store.publish(write_csv(tmp_path), source="fixture")
    metadata_path = next(store.snapshots.glob("*/metadata.json"))
    metadata = json.loads(metadata_path.read_text())
    metadata["retrieved_at"] = "2026-01-01T00:00:00Z"
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    with pytest.raises(IngestionError, match="janela de frescor"):
        assert_fresh_snapshot(store.root, max_age_hours=1, now=datetime(2026, 7, 21, tzinfo=timezone.utc))


def test_missing_snapshot_blocks_serving(tmp_path):
    with pytest.raises(IngestionError, match="nenhum snapshot"):
        assert_fresh_snapshot(tmp_path / "missing", max_age_hours=192)


def test_atomic_pointer_preserves_previous_on_replace_failure(tmp_path, monkeypatch):
    store = SnapshotStore(tmp_path / "ingestion")
    store.publish(write_csv(tmp_path), source="fixture")
    before = store.pointer.read_bytes()
    import src.data.ingestion as module
    real_replace = module.os.replace

    def fail_pointer(src, dst):
        if Path(dst) == store.pointer:
            raise OSError("interrupted publication")
        return real_replace(src, dst)

    monkeypatch.setattr(module.os, "replace", fail_pointer)
    with pytest.raises(OSError):
        store.publish(write_csv(tmp_path, csv_bytes(date="2026-07-21")), source="fixture")
    assert store.pointer.read_bytes() == before


def test_concurrent_publication_never_corrupts_pointer(tmp_path):
    store = SnapshotStore(tmp_path / "ingestion")
    errors = []

    def publish(day: str):
        try:
            source = tmp_path / f"{day}.csv"
            source.write_bytes(csv_bytes(date=day))
            store.publish(source, source="fixture")
        except Exception as exc:  # one can lose only on exact snapshot collision
            errors.append(exc)

    threads = [threading.Thread(target=publish, args=(f"2026-07-2{i}",)) for i in (1, 2)]
    [thread.start() for thread in threads]
    [thread.join() for thread in threads]
    assert store.current_payload() is not None
    assert json.loads(store.pointer.read_text())["snapshot"]
