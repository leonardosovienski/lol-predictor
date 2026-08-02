"""PandaScore LoL secondary source for opt-in coverage audits only."""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from predictor_core.data.contracts import DataUnavailableError

from ..config import ROOT as _ROOT  # noqa: F401  (activate vendored core)

BASE = "https://api.pandascore.co"


class PandaScoreProvider:
    def __init__(
        self,
        *,
        token: str | None = None,
        timeout: float = 30.0,
        get_json: Callable[[str, dict[str, str]], Any] | None = None,
    ):
        self.token = token or os.environ.get("PANDASCORE_TOKEN")
        self.timeout = timeout
        self._get_json = get_json or self._http_get_json

    def _headers(self):
        if not self.token:
            raise DataUnavailableError("PANDASCORE_TOKEN ausente")
        return {"Authorization": f"Bearer {self.token}", "User-Agent": "lol-predictor-source-audit/1.0"}

    def _http_get_json(self, url, headers):
        try:
            request = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read())
        except (OSError, ValueError) as exc:
            raise DataUnavailableError(f"PandaScore indisponível: {exc}") from exc

    def list_upcoming(self, *, observed_at: datetime | None = None, per_page: int = 100) -> list[dict[str, Any]]:
        observed = observed_at or datetime.now(UTC)
        if observed.tzinfo is None or observed.utcoffset() is None:
            raise ValueError("observed_at deve conter timezone")
        query = urllib.parse.urlencode({"per_page": per_page})
        payload = self._get_json(f"{BASE}/lol/matches/upcoming?{query}", self._headers())
        if not isinstance(payload, list):
            raise DataUnavailableError("PandaScore retornou partidas LoL inválidas")
        rows = []
        for match in payload:
            opponents = match.get("opponents") or []
            if len(opponents) != 2:
                continue
            try:
                scheduled = datetime.fromisoformat(str(match["scheduled_at"]).replace("Z", "+00:00"))
                names = [item["opponent"]["name"] for item in opponents]
                if scheduled.tzinfo is None or not all(names):
                    raise ValueError
            except (KeyError, TypeError, ValueError):
                continue
            rows.append(
                {
                    "source": "pandascore",
                    "source_event_id": str(match["id"]),
                    "scheduled_at": scheduled.astimezone(UTC).isoformat(timespec="seconds"),
                    "observed_at": observed.astimezone(UTC).isoformat(timespec="seconds"),
                    "team_a": names[0],
                    "team_b": names[1],
                    "format": match.get("number_of_games"),
                    "shadow_only": True,
                }
            )
        return sorted(rows, key=lambda row: (row["scheduled_at"], row["source_event_id"]))

    def iter_past(self, *, from_date: str, to_date: str, per_page: int = 100, max_pages: int | None = None):
        page = 1
        while max_pages is None or page <= max_pages:
            query = urllib.parse.urlencode(
                {"per_page": per_page, "page": page, "range[begin_at]": f"{from_date}T00:00:00Z,{to_date}T23:59:59Z"}
            )
            payload = self._get_json(f"{BASE}/lol/matches/past?{query}", self._headers())
            if not isinstance(payload, list):
                raise DataUnavailableError("PandaScore retornou histórico LoL inválido")
            yield from _normalize_past(payload)
            if len(payload) < per_page:
                break
            page += 1


def _normalize_past(payload):
    for match in payload:
        opponents = match.get("opponents") or []
        results = match.get("results") or []
        if len(opponents) != 2 or match.get("status") != "finished":
            continue
        teams = [x.get("opponent") or {} for x in opponents]
        scores = {x.get("team_id"): x.get("score") for x in results}
        try:
            started = datetime.fromisoformat(str(match["begin_at"]).replace("Z", "+00:00"))
            ids = [int(x["id"]) for x in teams]
            names = [x["name"] for x in teams]
            values = [int(scores[x]) for x in ids]
            if started.tzinfo is None or values[0] == values[1]:
                raise ValueError
        except (KeyError, TypeError, ValueError):
            continue
        yield {
            "source": "pandascore",
            "source_event_id": str(match["id"]),
            "started_at": started.astimezone(UTC).isoformat(timespec="seconds"),
            "team_a_id": ids[0],
            "team_b_id": ids[1],
            "team_a": names[0],
            "team_b": names[1],
            "score_a": values[0],
            "score_b": values[1],
            "winner": "a" if values[0] > values[1] else "b",
            "format": match.get("number_of_games"),
            "league": (match.get("league") or {}).get("name"),
            "serie": (match.get("serie") or {}).get("full_name"),
            "unit": "series",
            "shadow_only": True,
        }
