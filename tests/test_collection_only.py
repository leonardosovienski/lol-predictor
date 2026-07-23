import json
from datetime import datetime, timedelta, timezone

import pytest

from src.collection_only import CollectionError, collect, health, promote_to_trial


def _run(): return {"collection_run_id":"test-run", "mode":"COLLECTION_ONLY"}
def _event(**extra):
 base={"source":"oracle-elixir", "source_event_id":"series-1", "competition_id":"lck", "competition_name":"LCK", "format":"bo3", "scheduled_at":"2026-07-25T12:00:00Z", "team_a":"T1", "team_b":"Gen.G", "maps":[{"source_map_id":"m1","result":"a"}]}; base.update(extra); return base

def test_full_flow_series_and_maps_atomic(tmp_path):
 snap=collect(tmp_path,_run(),[_event(result="a",result_available_at="2026-07-25T15:00:00Z")])
 assert snap["status"]=="COLLECTED" and snap["events"][0]["lifecycle_status"]=="RESULT_OFFICIAL"
 assert snap["events"][0]["canonical_event_id"]=="oracle-elixir:series-1"

def test_no_events_and_pending_result_visible(tmp_path):
 assert collect(tmp_path,_run(),[])["status"]=="NO_UPSTREAM_EVENTS"
 collect(tmp_path,_run(),[_event(scheduled_at="2026-07-20T12:00:00Z")])
 assert health(tmp_path,now=datetime(2026,7,23,tzinfo=timezone.utc))["status"]=="PAST_EVENT_RESULT_PENDING"

def test_duplicate_ambiguous_and_trial_promotion_fail_closed(tmp_path,monkeypatch):
 with pytest.raises(CollectionError,match="duplicado"):
  collect(tmp_path,_run(),[_event(),_event()])
 monkeypatch.setattr("src.collection_only.resolve_team",lambda _name: (_ for _ in ()).throw(ValueError("ambígua")))
 assert "identidade" in collect(tmp_path,_run(),[_event()])["rejected"][0]["reason"]
 with pytest.raises(CollectionError,match="não pode"):
  promote_to_trial({})

def test_slo_alerts_after_48h_with_future_event(tmp_path):
 collect(tmp_path,_run(),[_event(scheduled_at="2026-07-25T12:00:00Z")],now=datetime(2026,7,20,tzinfo=timezone.utc))
 assert health(tmp_path,now=datetime(2026,7,23,tzinfo=timezone.utc))["status"]=="STALE_EXPECTED_EVENT"
