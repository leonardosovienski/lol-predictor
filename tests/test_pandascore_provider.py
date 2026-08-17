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


def test_match_context_reports_optional_fields_without_promoting_them():
    payload = {
        "opponents": [
            {"opponent": {"id": 1, "name": "T1", "players": [
                {"id": index, "name": f"a{index}", "role": role}
                for index, role in enumerate(("top", "jun", "mid", "adc", "sup"), 1)
            ]}},
            {"opponent": {"id": 2, "name": "Gen.G", "players": [
                {"id": index, "name": f"b{index}", "role": role}
                for index, role in enumerate(("top", "jun", "mid", "adc", "sup"), 11)
            ]}},
        ],
        "videogame": {"version": "26.16"},
        "games": [{"id": 1, "picks": ["A"], "bans": ["B"]}],
        "substitutes": [{"id": 99}],
    }
    provider = PandaScoreProvider(token="fixture", get_json=lambda _url, _headers: payload)
    context = provider.fetch_match_context("42", observed_at=datetime(2026, 8, 17, tzinfo=timezone.utc))
    assert context["full_five_player_rosters"] == 2
    assert context["patch"] == "26.16"
    assert context["draft_fields_available"] is True
    assert context["draft_timeline_available"] is False
    assert context["shadow_only"] is True
