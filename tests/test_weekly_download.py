from __future__ import annotations

import io

from scripts import atualiza_semanal_payload as weekly


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


def _csv_bytes(size: int = 1_000_100, date: str = "2026-07-20") -> bytes:
    header = b"gameid,league,teamname,date,result\n"
    row = f"g1,LCK,T1,{date},1\n".encode()
    repeats = (size - len(header)) // len(row) + 1
    return (header + row * repeats)[:size]


def test_configured_url_precedes_official_drive(monkeypatch):
    monkeypatch.setenv("ORACLES_ELIXIR_2026_URL", "https://example.invalid/oe.csv")
    urls = weekly._download_urls(2026)
    assert urls[0] == "https://example.invalid/oe.csv"
    assert "drive.usercontent.google.com" in urls[1]


def test_download_falls_back_after_invalid_html(tmp_path, monkeypatch):
    monkeypatch.setattr(weekly, "ROOT", tmp_path)
    monkeypatch.setenv("ORACLES_ELIXIR_2026_URL", "https://first.invalid/oe.csv")
    responses = iter([b"<html>quota exceeded</html>", _csv_bytes()])
    monkeypatch.setattr(weekly.urllib.request, "urlopen",
                        lambda *_args, **_kwargs: _Response(next(responses)))
    assert weekly.download_csv(2026)
    target = tmp_path / "data" / "raw" / "2026_oe.csv"
    assert weekly._valid_oracles_csv(target)


def test_failed_download_preserves_valid_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(weekly, "ROOT", tmp_path)
    target = tmp_path / "data" / "raw" / "2026_oe.csv"
    target.parent.mkdir(parents=True)
    original = _csv_bytes()
    target.write_bytes(original)
    monkeypatch.setattr(weekly.urllib.request, "urlopen",
                        lambda *_args, **_kwargs: _Response(b"quota exceeded"))
    assert not weekly.download_csv(2026)
    assert target.read_bytes() == original


def test_older_official_fallback_cannot_replace_newer_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(weekly, "ROOT", tmp_path)
    target = tmp_path / "data" / "raw" / "2026_oe.csv"
    target.parent.mkdir(parents=True)
    current = _csv_bytes(date="2026-07-20")
    target.write_bytes(current)
    monkeypatch.setattr(weekly.urllib.request, "urlopen",
                        lambda *_args, **_kwargs: _Response(_csv_bytes(date="2026-06-02")))
    assert not weekly.download_csv(2026)
    assert target.read_bytes() == current
