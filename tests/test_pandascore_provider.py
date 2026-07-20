from datetime import datetime, timezone

from src.data.pandascore_provider import PandaScoreProvider


def test_pandascore_lol_normalizes_shadow_record_without_secret():
    payload = [{"id": 8, "scheduled_at": "2026-07-22T12:00:00Z",
                "number_of_games": 5,
                "opponents": [{"opponent": {"name": "T1"}},
                              {"opponent": {"name": "Gen.G"}}]}]
    provider = PandaScoreProvider(token="synthetic", get_json=lambda *_: payload)
    rows = provider.list_upcoming(observed_at=datetime(2026, 7, 20, tzinfo=timezone.utc))
    assert rows[0]["team_a"] == "T1"
    assert rows[0]["shadow_only"] is True
    assert "synthetic" not in repr(rows)
