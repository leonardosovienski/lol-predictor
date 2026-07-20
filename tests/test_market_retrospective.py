from scripts.backtest_market_retrospective import _bootstrap, _model_probability


def test_modelo_retro_nao_usa_jogo_futuro():
    base = [("2026-01-01 00:00:00", "g1", "T1", "Gen.G", "a")]
    future = base + [("2026-01-03 00:00:00", "g2", "T1", "Gen.G", "b")]
    cutoff = "2026-01-02 00:00:00"
    assert _model_probability(base, cutoff, "T1", "Gen.G", "bo3") == \
        _model_probability(future, cutoff, "T1", "Gen.G", "bo3")


def test_bootstrap_deterministico():
    rows = [{"x": value} for value in (1.0, -1.0, .5, 0.0)]
    assert _bootstrap(rows, "x", 100) == _bootstrap(rows, "x", 100)
