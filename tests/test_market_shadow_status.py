import json
from datetime import datetime, timezone

from scripts.market_shadow_status import status


def test_status_exclui_probe_e_escolhe_ultima_cotacao(tmp_path):
    trials = tmp_path / "trials.json"
    trials.write_text(json.dumps([{
        "name": "h4-lol-market-shadow-prospectivo",
        "registered_at": "2026-07-20T10:00:00Z",
        "params": {"collection_start_exclusive": "2026-07-20T10:00:00Z",
                   "closing_cutoff_minutes_before_start": 15,
                   "max_spread": .1, "min_liquidity": 1000,
                   "min_matured_matches": 50, "min_calendar_days": 30},
    }]), encoding="utf-8")
    base = {"condition_id": "c1", "published_at": "2026-07-20T11:00:00+00:00",
            "scheduled_at": "2026-07-21T11:00:00+00:00", "max_spread": .02,
            "liquidity": 2000, "model_probability_a": .6,
            "model_probability_b": .4, "ratings_sha256": "x"}
    quotes = tmp_path / "quotes.jsonl"
    rows = [
        {**base, "observed_at": "2026-07-20T09:00:00+00:00",
         "published_at": "2026-07-20T09:00:00+00:00"},
        {**base, "observed_at": "2026-07-20T11:00:00+00:00"},
        {**base, "observed_at": "2026-07-20T12:00:00+00:00",
         "published_at": "2026-07-20T12:00:00+00:00"},
    ]
    quotes.write_text("\n".join(json.dumps(row) for row in rows) + "\n",
                      encoding="utf-8")
    report = status(quotes, trials,
                    now=datetime(2026, 7, 22, tzinfo=timezone.utc))
    assert report["raw_quotes"] == 3
    assert report["eligible_quotes"] == 2
    assert report["eligible_matches"] == 1
    assert report["matured_matches"] == 1
    assert report["verdict"] == "PENDING_SAMPLE"
