from scripts.collect_polymarket_upcoming import resolve_market_team


def test_alias_polymarket_explicito():
    assert resolve_market_team("Nongshim Red Force") == "Nongshim RedForce"
