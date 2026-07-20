from scripts.collect_polymarket_shadow import append_once


def test_append_quote_idempotente(tmp_path):
    path = tmp_path / "quotes.jsonl"
    quote = {"quote_id": "abc", "published_at": "2026-07-20T12:00:00+00:00"}
    assert append_once(path, quote) is True
    assert append_once(path, quote) is False
    assert len(path.read_text(encoding="utf-8").splitlines()) == 1
