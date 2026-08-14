from src.redaction import collect_sensitive_values, safe_redact_text


def test_collects_only_conventionally_sensitive_keys():
    environ = {"LOL_API_KEY": "abcdefgh12345678", "LOL_LOG_LEVEL": "INFO", "PATH": "/usr/bin"}
    assert collect_sensitive_values(environ) == {"abcdefgh12345678"}


def test_ignores_empty_values():
    assert collect_sensitive_values({"MY_SECRET": ""}) == set()


def test_short_values_are_still_collected():
    """A short 'secret' IS collected — it might be a real, if weak, credential.
    Collateral-redaction safety is safe_redact_text's job (boundary matching
    below), not collect_sensitive_values' — dropping short values here would
    silently stop protecting real short credentials."""
    environ = {"SOME_AUTH_DIGIT": "4", "OTHER_TOKEN": "3", "REAL_API_KEY": "abcdefgh12345678"}
    assert collect_sensitive_values(environ) == {"4", "3", "abcdefgh12345678"}


def test_safe_redact_text_replaces_longest_first():
    text = "token=abc123 and full=abc123xyz"
    redacted = safe_redact_text(text, ["abc123", "abc123xyz"])
    assert redacted == "token=[REDACTED] and full=[REDACTED]"


def test_safe_redact_text_never_touches_unrelated_digits():
    redacted = safe_redact_text("2026-08-14: 1576 games, hash e77fade6", ["abcdefgh12345678"])
    assert redacted == "2026-08-14: 1576 games, hash e77fade6"


def test_safe_redact_text_short_secret_does_not_corrupt_embedded_digits():
    """Regression: a 1-char sensitive value used to nuke every matching digit
    inside every date/count/hash in production log output — the actual
    incident that motivated this module's boundary-matching rewrite."""
    text = "2026-01-14 08:13:43 games=1576 league LPL=453 hash e77fade6"
    redacted = safe_redact_text(text, ["4", "3"])
    assert redacted == text  # nem "4" nem "3" aparecem como token isolado aqui


def test_safe_redact_text_short_secret_still_redacts_as_standalone_token():
    redacted = safe_redact_text("AUTH_PIN=4 confirmed", ["4"])
    assert redacted == "AUTH_PIN=[REDACTED] confirmed"
