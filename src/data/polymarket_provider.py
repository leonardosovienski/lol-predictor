"""Fonte pública point-in-time de preços de mercado para LoL.

Polymarket não é bookmaker: seus preços são probabilidades negociadas em um
mercado de previsão. A fonte serve exclusivamente ao shadow econômico da Fase
1b. Descoberta (Gamma) e order books (CLOB) são endpoints públicos read-only;
nenhum caminho de ordem/trading existe neste módulo.
"""
from __future__ import annotations

import json
import math
import hashlib
import ipaddress
import subprocess
import sys
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from urllib.parse import urlencode
from urllib.parse import urlparse

import httpx

from ..config import ROOT as _ROOT  # noqa: F401  (ativa vendor no sys.path)
from predictor_core.data.contracts import DataUnavailableError

GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"

# `pythonw.exe` — o executavel de TODA tarefa agendada deste ecossistema — nao
# tem console. Um processo de CONSOLE lancado a partir dele (aqui, o `curl` do
# fallback DoH) ganha um console PROPRIO E VISIVEL: uma janela preta abrindo na
# tela do dono. Como o B-0 (NXDOMAIN de polymarket.com nesta rede) forca este
# fallback em TODA coleta, e a tarefa roda de 30 em 30 minutos, era uma janela
# a cada meia hora, indefinidamente.
#
# CREATE_NO_WINDOW impede a criacao do console sem esconder nada: o stdout ja e
# capturado por `capture_output=True`, entao nenhuma saida se perde. Vale 0 fora
# do Windows, onde o conceito nao existe.
_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


def _key(value: str) -> str:
    return unicodedata.normalize("NFC", value).strip().casefold()


def _array(value: Any, field: str) -> list[str]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise DataUnavailableError(f"Polymarket {field} inválido") from exc
    if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
        raise DataUnavailableError(f"Polymarket {field} inválido")
    return value


def _timestamp(value: Any) -> datetime:
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        # CLOB normalmente entrega epoch em milissegundos.
        seconds = float(value) / 1000 if float(value) > 10_000_000_000 else float(value)
        return datetime.fromtimestamp(seconds, timezone.utc)
    if isinstance(value, str):
        raw = value.strip()
        if raw.isdigit():
            return _timestamp(int(raw))
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError as exc:
            raise DataUnavailableError("timestamp inválido no order book") from exc
        if parsed.tzinfo is not None:
            return parsed.astimezone(timezone.utc)
    raise DataUnavailableError("order book sem timestamp UTC válido")


class PolymarketProvider:
    """Cliente read-only com transporte injetável para testes determinísticos."""

    def __init__(self, timeout: float = 20.0,
                 get_json: Callable[[str], Any] | None = None):
        self.timeout = timeout
        self._get_json = get_json or self._http_get_json
        self._dns_cache: dict[str, str] = {}

    def _http_get_json(self, url: str) -> Any:
        try:
            response = httpx.get(url, timeout=self.timeout,
                                 headers={"User-Agent": "lol-predictor-shadow/1.0"})
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError) as exc:
            # Alguns hosts Windows recebem NXDOMAIN do roteador mesmo quando
            # DNS públicos resolvem. Fallback read-only: DoH por IP + curl
            # --resolve preserva TLS/SNI sem mudar a configuração do sistema.
            try:
                return self._curl_via_doh(url)
            except (OSError, ValueError, subprocess.SubprocessError) as fallback:
                raise DataUnavailableError(
                    f"Polymarket indisponível: {exc}; fallback DoH: {fallback}"
                ) from fallback

    # Ordem de tentativa do DoH. Em 2026-07-26 o resolvedor desta rede passou a
    # devolver NXDOMAIN para polymarket.com E o IP 1.1.1.1 ficou inalcançável —
    # o fallback criado em 20/07 parou junto. Sondagem: 1.1.1.1 sem resposta,
    # mas `cloudflare-dns.com` responde 200. O IP é bloqueado; o hostname não.
    # Manter mais de um endpoint evita que a queda de um mate a coleta inteira.
    DOH_ENDPOINTS = ("https://cloudflare-dns.com/dns-query",
                     "https://dns.google/resolve",
                     "https://1.1.1.1/dns-query")

    def _resolve_via_doh(self, hostname: str) -> str:
        """Primeiro endpoint DoH que devolver um A público vence. Sem nenhum,
        falha fechado — nunca chuta endereço."""
        erros = []
        for endpoint in self.DOH_ENDPOINTS:
            try:
                dns = httpx.get(
                    endpoint, params={"name": hostname, "type": "A"},
                    headers={"accept": "application/dns-json"}, timeout=self.timeout)
                dns.raise_for_status()
                for row in (dns.json().get("Answer") or []):
                    if row.get("type") != 1:
                        continue
                    address = ipaddress.ip_address(row.get("data", ""))
                    if not address.is_global:
                        raise ValueError("DoH retornou endereço não público")
                    return str(address)
                erros.append(f"{endpoint}: sem registro A")
            except (httpx.HTTPError, ValueError) as exc:
                erros.append(f"{endpoint}: {type(exc).__name__}")
        raise ValueError("nenhum endpoint DoH resolveu (" + "; ".join(erros) + ")")

    def _curl_via_doh(self, url: str) -> Any:
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname not in {
                "gamma-api.polymarket.com", "clob.polymarket.com"}:
            raise ValueError("host não permitido no fallback DoH")
        address_text = self._dns_cache.get(parsed.hostname)
        if address_text is None:
            address_text = self._resolve_via_doh(parsed.hostname)
            self._dns_cache[parsed.hostname] = address_text
        result = subprocess.run(
            ["curl", "--fail", "--silent", "--show-error", "--max-time",
             str(max(1, int(self.timeout))), "--resolve",
             f"{parsed.hostname}:443:{address_text}", url],
            capture_output=True, text=True, encoding="utf-8", check=True,
            creationflags=_NO_WINDOW)
        return json.loads(result.stdout)

    def health_check(self) -> bool:
        try:
            payload = self._get_json(f"{GAMMA}/sports")
            return isinstance(payload, list) and bool(payload)
        except DataUnavailableError:
            return False

    def list_upcoming_matches(self, horizon_hours: int = 72,
                              now: datetime | None = None) -> list[dict[str, Any]]:
        """Descobre moneylines LoL futuras; sem resolver identidade aqui."""
        observed = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        limit = observed + timedelta(hours=horizon_hours)
        payload = self._get_json(
            f"{GAMMA}/events?tag_id=65&active=true&closed=false&limit=500")
        if not isinstance(payload, list):
            raise DataUnavailableError("lista de eventos Polymarket inválida")
        found = []
        for event in payload:
            raw = event.get("startTime")
            try:
                scheduled = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            except (TypeError, ValueError):
                continue
            if scheduled.tzinfo is None:
                continue
            scheduled = scheduled.astimezone(timezone.utc)
            if not observed < scheduled <= limit:
                continue
            moneylines = [m for m in event.get("markets") or []
                          if m.get("sportsMarketType") == "moneyline"]
            if len(moneylines) != 1:
                continue
            outcomes = _array(moneylines[0].get("outcomes"), "outcomes")
            if len(outcomes) == 2:
                series = event.get("series") if isinstance(event.get("series"), dict) else {}
                competition_id = series.get("id") or event.get("seriesId")
                competition_name = series.get("title") or series.get("name")
                found.append({"team_a": outcomes[0], "team_b": outcomes[1],
                              "scheduled_at": scheduled.isoformat(timespec="seconds"),
                              "event_id": str(event.get("id")),
                              "competition_id": str(competition_id) if competition_id else None,
                              "competition_name": competition_name,
                              "region": event.get("region"), "tournament": event.get("tournament"),
                              "split": event.get("split"), "patch": event.get("patch")})
        return sorted(found, key=lambda row: (row["scheduled_at"], row["event_id"]))

    def list_closed_match_events(self, max_events: int = 500) -> list[dict[str, Any]]:
        """Lista eventos LoL encerrados com moneyline, sem seleção por resultado."""
        found = []
        for offset in range(0, max_events, 100):
            payload = self._get_json(
                f"{GAMMA}/events?tag_id=65&closed=true&limit=100&offset={offset}"
                "&order=startTime&ascending=false")
            if not isinstance(payload, list):
                raise DataUnavailableError("lista histórica Polymarket inválida")
            if not payload:
                break
            for event in payload:
                moneylines = [m for m in event.get("markets") or []
                              if m.get("sportsMarketType") == "moneyline"]
                if len(moneylines) == 1 and event.get("startTime"):
                    found.append({**event, "moneyline": moneylines[0]})
            if len(payload) < 100:
                break
        return found

    def price_before(self, token_id: str, cutoff: datetime,
                     max_age_hours: int = 48) -> tuple[datetime, float]:
        """Último preço publicado até cutoff, dentro da janela declarada."""
        if cutoff.tzinfo is None or cutoff.utcoffset() is None:
            raise ValueError("cutoff deve conter timezone")
        cutoff = cutoff.astimezone(timezone.utc)
        start = cutoff - timedelta(hours=max_age_hours)
        query = urlencode({"market": token_id,
                           "startTs": int(start.timestamp()),
                           "endTs": int(cutoff.timestamp()), "fidelity": 1})
        payload = self._get_json(f"{CLOB}/prices-history?{query}")
        history = payload.get("history") if isinstance(payload, dict) else None
        if not isinstance(history, list):
            raise DataUnavailableError("histórico de preço inválido")
        valid = []
        for row in history:
            try:
                at = datetime.fromtimestamp(float(row["t"]), timezone.utc)
                price = float(row["p"])
            except (KeyError, TypeError, ValueError, OSError):
                continue
            if start <= at <= cutoff and math.isfinite(price) and 0 < price < 1:
                valid.append((at, price))
        if not valid:
            raise DataUnavailableError("sem preço histórico elegível antes do cutoff")
        return max(valid, key=lambda item: item[0])

    @staticmethod
    def _midpoint(book: dict[str, Any]) -> tuple[float, float]:
        try:
            bids = [float(row["price"]) for row in book["bids"]]
            asks = [float(row["price"]) for row in book["asks"]]
        except (KeyError, TypeError, ValueError) as exc:
            raise DataUnavailableError("order book malformado") from exc
        if not bids or not asks:
            raise DataUnavailableError("order book sem ambos os lados")
        bid, ask = max(bids), min(asks)
        if not (0 < bid <= ask < 1):
            raise DataUnavailableError(f"order book inválido: bid={bid}, ask={ask}")
        return (bid + ask) / 2, ask - bid

    def fetch_match(self, team_a: str, team_b: str,
                    observed_at: datetime | None = None,
                    event_id: str | None = None) -> dict[str, Any]:
        if observed_at is not None and (
                observed_at.tzinfo is None or observed_at.utcoffset() is None):
            raise ValueError("observed_at deve conter timezone")
        if event_id is not None:
            event = self._get_json(f"{GAMMA}/events/{event_id}")
            if not isinstance(event, dict):
                raise DataUnavailableError("evento Polymarket inválido")
            events = [event]
        else:
            query = urlencode({"q": f"LoL: {team_a} vs {team_b}",
                               "events_status": "active", "limit_per_type": 20,
                               "keep_closed_markets": 0})
            payload = self._get_json(f"{GAMMA}/public-search?{query}")
            if not isinstance(payload, dict) or not isinstance(payload.get("events"), list):
                raise DataUnavailableError("resposta de busca Polymarket inválida")
            events = payload["events"]

        target = {_key(team_a), _key(team_b)}
        candidates: list[tuple[dict[str, Any], dict[str, Any], list[str], list[str]]] = []
        for event in events:
            for market in event.get("markets") or []:
                if market.get("sportsMarketType") != "moneyline":
                    continue
                outcomes = _array(market.get("outcomes"), "outcomes")
                tokens = _array(market.get("clobTokenIds"), "clobTokenIds")
                if len(outcomes) == len(tokens) == 2 and {_key(x) for x in outcomes} == target:
                    candidates.append((event, market, outcomes, tokens))
        if len(candidates) != 1:
            raise DataUnavailableError(
                f"esperado 1 moneyline exato para {team_a} vs {team_b}; "
                f"encontrados {len(candidates)}")

        event, market, outcomes, tokens = candidates[0]
        format_match = re.search(r"\(BO([135])\)", market.get("question") or "",
                                 flags=re.IGNORECASE)
        if not format_match:
            raise DataUnavailableError("moneyline sem formato BO1/BO3/BO5")
        match_format = f"bo{format_match.group(1)}"
        books = [self._get_json(f"{CLOB}/book?{urlencode({'token_id': token})}")
                 for token in tokens]
        # O instante de observação real é posterior à resposta. Em testes e
        # replays, observed_at explícito congela o relógio.
        observed = (observed_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
        mids_spreads = [self._midpoint(book) for book in books]
        published = max(_timestamp(book.get("timestamp")) for book in books)
        if published > observed:
            raise DataUnavailableError("order book publicado depois de observed_at")
        scheduled_raw = event.get("startTime") or event.get("endDate")
        try:
            scheduled = datetime.fromisoformat(
                str(scheduled_raw).replace("Z", "+00:00"))
        except (TypeError, ValueError) as exc:
            raise DataUnavailableError("evento sem horário ISO-8601 válido") from exc
        if scheduled.tzinfo is None:
            raise DataUnavailableError("evento sem horário timezone-aware")
        scheduled = scheduled.astimezone(timezone.utc)
        if observed >= scheduled:
            raise DataUnavailableError("coleta não é PRE_EVENT")

        raw = {outcome: midpoint for outcome, (midpoint, _spread)
               in zip(outcomes, mids_spreads)}
        total = sum(raw.values())
        if not math.isfinite(total) or total <= 0:
            raise DataUnavailableError("preços de mercado inválidos")
        probs = {name: price / total for name, price in raw.items()}
        name_a = next(name for name in outcomes if _key(name) == _key(team_a))
        name_b = next(name for name in outcomes if _key(name) == _key(team_b))
        quote_id = hashlib.sha256(
            f"polymarket-clob|{market.get('id')}|{published.isoformat()}".encode()
        ).hexdigest()
        return {
            "schema_version": "lol-market-quote/1.0",
            "quote_id": quote_id,
            "source": "polymarket-clob",
            "source_kind": "prediction_market",
            "market_id": str(market.get("id")),
            "condition_id": market.get("conditionId"),
            "event_id": str(event.get("id")),
            "team_a": team_a, "team_b": team_b,
            "format": match_format,
            "scheduled_at": scheduled.isoformat(timespec="seconds"),
            "observed_at": observed.isoformat(timespec="seconds"),
            "published_at": published.isoformat(timespec="seconds"),
            "probability_a": round(probs[name_a], 8),
            "probability_b": round(probs[name_b], 8),
            "decimal_a": round(1 / probs[name_a], 6),
            "decimal_b": round(1 / probs[name_b], 6),
            "max_spread": round(max(spread for _mid, spread in mids_spreads), 8),
            "liquidity": float(market.get("liquidity") or event.get("liquidity") or 0),
            "read_only": True,
        }
