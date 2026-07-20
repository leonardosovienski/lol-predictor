import json
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

import pytest

from src.data.polymarket_provider import DataUnavailableError, PolymarketProvider


EVENT = {
    "events": [{
        "id": "e1", "startTime": "2026-07-21T18:00:00Z", "liquidity": 5000,
        "markets": [{
            "id": "m1", "conditionId": "c1", "liquidity": "4000",
            "question": "LoL: T1 vs Gen.G (BO3) - Test",
            "sportsMarketType": "moneyline",
            "outcomes": json.dumps(["T1", "Gen.G"]),
            "clobTokenIds": json.dumps(["token-a", "token-b"]),
        }],
    }]
}


def transport(url):
    parsed = urlparse(url)
    if parsed.path == "/public-search":
        assert parse_qs(parsed.query)["q"] == ["LoL: T1 vs Gen.G"]
        return EVENT
    token = parse_qs(parsed.query)["token_id"][0]
    if token == "token-a":
        return {"timestamp": "2026-07-20T12:00:00Z",
                "bids": [{"price": "0.54"}], "asks": [{"price": "0.56"}]}
    return {"timestamp": 1784548800000,
            "bids": [{"price": "0.44"}], "asks": [{"price": "0.46"}]}


def test_quote_point_in_time_com_proveniencia():
    quote = PolymarketProvider(get_json=transport).fetch_match(
        "T1", "Gen.G", datetime(2026, 7, 20, 13, tzinfo=timezone.utc))
    assert quote["source_kind"] == "prediction_market"
    assert quote["format"] == "bo3"
    assert quote["read_only"] is True
    assert len(quote["quote_id"]) == 64
    assert quote["probability_a"] == .55
    assert quote["probability_b"] == .45
    assert quote["decimal_a"] == round(1 / .55, 6)
    assert quote["published_at"] <= quote["observed_at"] < quote["scheduled_at"]


def test_mercado_ambiguo_ou_ausente_falha():
    provider = PolymarketProvider(get_json=lambda _url: {"events": []})
    with pytest.raises(DataUnavailableError, match="encontrados 0"):
        provider.fetch_match("T1", "Gen.G",
                             datetime(2026, 7, 20, tzinfo=timezone.utc))


def test_rejeita_book_sem_liquidez_dos_dois_lados():
    def broken(url):
        if "/public-search" in url:
            return EVENT
        return {"timestamp": "2026-07-20T12:00:00Z", "bids": [], "asks": []}
    with pytest.raises(DataUnavailableError, match="ambos os lados"):
        PolymarketProvider(get_json=broken).fetch_match(
            "T1", "Gen.G", datetime(2026, 7, 20, 13, tzinfo=timezone.utc))


def test_rejeita_lookahead_e_timestamp_ingenuo():
    provider = PolymarketProvider(get_json=transport)
    with pytest.raises(DataUnavailableError, match="não é PRE_EVENT"):
        provider.fetch_match("T1", "Gen.G",
                             datetime(2026, 7, 22, tzinfo=timezone.utc))
    with pytest.raises(ValueError, match="timezone"):
        provider.fetch_match("T1", "Gen.G", datetime(2026, 7, 20))


def test_descobre_apenas_moneyline_futura():
    payload = [{
        "id": 1, "startTime": "2026-07-21T18:00:00Z",
        "markets": [EVENT["events"][0]["markets"][0]],
    }, {
        "id": 2, "startTime": "2026-07-19T18:00:00Z",
        "markets": [EVENT["events"][0]["markets"][0]],
    }]
    provider = PolymarketProvider(get_json=lambda _url: payload)
    rows = provider.list_upcoming_matches(
        horizon_hours=48, now=datetime(2026, 7, 20, 13, tzinfo=timezone.utc))
    assert rows == [{"team_a": "T1", "team_b": "Gen.G",
                     "scheduled_at": "2026-07-21T18:00:00+00:00",
                     "event_id": "1"}]
