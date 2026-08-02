from pathlib import Path
from typing import Annotated

from pydantic import Field, HttpUrl
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LOL_", env_file=".env", env_file_encoding="utf-8", extra="forbid")
    data_root: Path = Path("data")
    project_root: Path = Path(".")
    config_path: Path = Path("config.yaml")
    max_snapshot_staleness_hours: Annotated[int, Field(gt=0)] = 192
    oracle_primary_url: HttpUrl = HttpUrl(
        "https://oracles-elixir-data.s3.us-west-2.amazonaws.com/2026_LoL_esports_match_data_from_OraclesElixir.csv"
    )
    oracle_fallback_url: HttpUrl | None = None
    polymarket_gamma_url: HttpUrl = HttpUrl("https://gamma-api.polymarket.com")
    polymarket_clob_url: HttpUrl = HttpUrl("https://clob.polymarket.com")
    pandascore_api_key: str | None = None
    log_level: str = "INFO"
    otel_exporter_otlp_endpoint: str | None = None


def validate_env_example(path: Path) -> None:
    keys = {
        line.split("=", 1)[0]
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    }
    expected = {f"LOL_{name.upper()}" for name in Settings.model_fields}
    if unknown := keys - expected:
        raise ValueError(f"unknown .env.example keys: {sorted(unknown)}")
