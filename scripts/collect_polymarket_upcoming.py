"""Coleta automática das moneylines LoL conhecidas nas próximas 72 horas."""
from __future__ import annotations

import argparse
import json
import sys
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "vendor"))

from predictor_core.data.contracts import DataUnavailableError  # noqa: E402
from src.config import resolve_team  # noqa: E402
from src.data.polymarket_provider import PolymarketProvider  # noqa: E402
from scripts.collect_polymarket_shadow import append_once, attach_model_snapshot  # noqa: E402
from src.h4_gate import H4Error, assert_h4_open, build_signal  # noqa: E402

# `pythonw.exe` (executavel de toda tarefa agendada) nao tem console: um
# processo de console filho ganharia janela VISIVEL na tela do dono.
# Saida ja e capturada, entao a flag nao esconde nada.
_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

TRIAL_ID = "h4-lol-market-shadow-prospectivo-v2"


def _commit() -> str:
    result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                            capture_output=True, text=True, check=False,
                            creationflags=_NO_WINDOW)
    if result.returncode != 0 or len(result.stdout.strip()) != 40:
        raise H4Error("Git commit indisponível; provenance H4 bloqueada")
    return result.stdout.strip()


def resolve_market_team(display: str) -> str:
    aliases_path = ROOT / "data" / "polymarket_aliases.json"
    aliases = json.loads(aliases_path.read_text(encoding="utf-8"))["aliases"]
    target = aliases.get(display, display)
    return resolve_team(target)["name"]


def collect(output: Path, horizon_hours: int = 72,
            archive: Path | None = None) -> dict:
    assert_h4_open(ROOT / "data" / "h4_v2_closure.json")
    provider = PolymarketProvider()
    archive = archive or ROOT / "data" / "shadow" / "market_observations.jsonl"
    discovered = provider.list_upcoming_matches(horizon_hours=horizon_hours)
    appended = duplicates = skipped_identity = unavailable = archived = 0
    errors = []
    for match in discovered:
        try:
            team_a = resolve_market_team(match["team_a"])
            team_b = resolve_market_team(match["team_b"])
        except ValueError as exc:
            skipped_identity += 1
            errors.append({"event_id": match["event_id"], "kind": "identity",
                           "error": str(exc)})
            continue
        try:
            quote = provider.fetch_match(
                match["team_a"], match["team_b"], event_id=match["event_id"])
            quote = {**quote,
                     "source_team_a": match["team_a"],
                     "source_team_b": match["team_b"],
                     "team_a": team_a, "team_b": team_b}
            quote = attach_model_snapshot(quote)
            # ARQUIVA A OBSERVACAO BRUTA ANTES DE JULGAR ELEGIBILIDADE.
            #
            # Achado em 2026-07-28: o `build_signal` abaixo levanta H4Error
            # quando falta competicao (B-12), o except captura, e a gravacao
            # nunca acontecia — a cotacao era buscada e JOGADA FORA. Resultado:
            # `market_quotes.jsonl` congelado desde 22/07 enquanto a tarefa
            # rodava de 30 em 30 minutos com exit 0. Seis dias de cotacoes reais
            # do Polymarket perdidas, irrecuperaveis.
            #
            # Observar e julgar sao coisas diferentes. Este arquivo NAO alimenta
            # gate, contador nem criterio: e registro de auditoria, no sentido
            # do BLOQUEIOS_GO §1 ("responde 'por que' depois"). Se o B-12 for
            # decidido em agosto, existira historico para reprocessar; sem isto,
            # nao existiria.
            if append_once(archive, quote):
                archived += 1
            signal = build_signal(quote, trial_id=TRIAL_ID, code_commit=_commit(),
                                  competition_id=match.get("competition_id") or "",
                                  competition_name=match.get("competition_name") or "",
                                  region=match.get("region"), tournament=match.get("tournament"),
                                  split=match.get("split"), patch=match.get("patch"))
            if append_once(output, {**signal, "quote_id": signal["signal_id"]}):
                appended += 1
            else:
                duplicates += 1
        except (DataUnavailableError, H4Error) as exc:
            unavailable += 1
            errors.append({"event_id": match["event_id"], "kind": "market",
                           "error": str(exc)})
    return {"discovered": len(discovered), "appended": appended,
            "archived": archived,
            "duplicates": duplicates, "skipped_identity": skipped_identity,
            "unavailable": unavailable, "errors": errors}


LOG = ROOT / "logs" / "operations" / "collect_polymarket_upcoming.log"


def _log(mensagem: str) -> None:
    """Persiste o resumo. A tarefa agendada roda sob `pythonw.exe` desde
    2026-07-26 (para não abrir console na tela do operador) e pythonw DESCARTA
    stdout — sem este arquivo, cada execução ficaria sem registro do que
    coletou. Falha ao logar nunca derruba a coleta."""
    try:
        from datetime import datetime, timezone
        LOG.parent.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with LOG.open("a", encoding="utf-8") as fh:
            fh.write(f"{stamp} {mensagem}\n")
    except OSError:
        pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Collect upcoming LoL shadow quotes")
    parser.add_argument("--horizon-hours", type=int, default=72)
    parser.add_argument("--output", type=Path,
                        default=ROOT / "data" / "shadow" / "h4_signals.jsonl")
    args = parser.parse_args(argv)
    if not 1 <= args.horizon_hours <= 168:
        print("horizon-hours deve estar entre 1 e 168", file=sys.stderr)
        return 2
    try:
        report = collect(args.output, args.horizon_hours)
    except (DataUnavailableError, OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        _log(f"FALHA {type(exc).__name__}: {exc}")
        return 2
    # o log guarda o resumo enxuto; a lista completa de erros fica no stdout
    resumo = {k: v for k, v in report.items() if k != "errors"}
    resumo["errors"] = len(report.get("errors") or [])
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    _log(json.dumps(resumo, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
