from __future__ import annotations

import json
import shutil
from pathlib import Path

from predictor_ops import JobConfig, RunStatus, run_job
from predictor_ops.models import RuntimeConfig

from src.data.ingestion import SnapshotStore


def test_predictor_ops_3_runs_two_idempotent_cycles(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    data_root.mkdir()
    shutil.copy2(Path(__file__).resolve().parents[1] / "data" / "canonical_teams.json", data_root)
    source = tmp_path / "source.csv"
    source.write_text(
        "gameid,league,teamname,date,result\ng1,LCK,T1,2026-08-08T00:00:00Z,1\ng1,LCK,Gen.G,2026-08-08T00:00:00Z,0\n",
        encoding="utf-8",
    )
    pointer = data_root / "ingestion" / "current.json"
    SnapshotStore(data_root / "ingestion").publish(source, source="fixture")
    executable = shutil.which("lol-predictor")
    assert executable is not None
    runtime = RuntimeConfig(root=tmp_path / "runtime", lock_stale_after_seconds=60)
    job = JobConfig(
        id="lol-publish-snapshot-pilot",
        command=[executable, "publish-snapshot"],
        environment={"LOL_DATA_ROOT": str(data_root), "LOL_MIN_FREE_DISK_MB": "1"},
        timeout_seconds=30,
        expected_artifact=pointer,
        scientific_state="COLLECTION_ONLY",
        runtime=runtime,
    )

    first = run_job(job)
    second = run_job(job)

    assert first.run_status is RunStatus.SUCCEEDED
    assert second.run_status is RunStatus.SUCCEEDED
    assert '"status": "PUBLISHED"' in first.record["output"]["text"]
    assert '"status": "SKIPPED"' in second.record["output"]["text"]
    job_root = runtime.root / job.id
    heartbeat = json.loads((job_root / "heartbeat.json").read_text(encoding="utf-8"))
    events = [json.loads(line) for line in (job_root / "events.jsonl").read_text(encoding="utf-8").splitlines()]
    assert heartbeat["run_status"] == "SUCCEEDED"
    assert heartbeat["scientific_state"] == "COLLECTION_ONLY"
    assert len(events) == 2
