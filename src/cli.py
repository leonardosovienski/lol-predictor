import argparse
import json
import sys
from pathlib import Path

from .draft_coverage import publish_audit
from .operations import (
    ContractError,
    OperationalError,
    backtest,
    collect_holdout,
    collect_shadow,
    health,
    ingest,
    publish_freeze,
    publish_snapshot,
    settle,
    structured_log,
)
from .plugin import LolPredictorPlugin
from .services import PredictionRequest
from .settings import Settings, validate_env_example


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="lol-predictor")
    sub = parser.add_subparsers(dest="command", required=True)
    predict = sub.add_parser("predict")
    predict.add_argument("team_a")
    predict.add_argument("team_b")
    predict.add_argument("--format", default="bo3", choices=("bo1", "bo3", "bo5"))
    ingest_parser = sub.add_parser("ingest")
    ingest_parser.add_argument(
        "--source", default="oracles", choices=("oracles", "oracles_elixir", "pandascore", "riot")
    )
    ingest_parser.add_argument("--url")
    sub.add_parser("publish-snapshot")
    sub.add_parser("publish-freeze")
    backtest_parser = sub.add_parser("backtest")
    backtest_parser.add_argument("--snapshot", type=Path)
    settle_parser = sub.add_parser("settle")
    settle_parser.add_argument("--results", type=Path, required=True)
    settle_parser.add_argument("--signals", type=Path)
    shadow = sub.add_parser("collect-shadow")
    shadow.add_argument("--horizon-hours", type=int, default=72)
    shadow.add_argument("--output", type=Path)
    holdout = sub.add_parser("collect-holdout")
    holdout.add_argument("--horizon-hours", type=int, default=168)
    coverage = sub.add_parser("audit-draft-coverage")
    coverage.add_argument("--horizon-hours", type=int, default=168)
    coverage.add_argument("--output", type=Path)
    health_parser = sub.add_parser("health")
    health_parser.add_argument("--connectivity", action="store_true", default=None)
    check = sub.add_parser("validate-env")
    check.add_argument("path", type=Path, nargs="?", default=Path(".env.example"))
    args = parser.parse_args(argv)
    try:
        plugin = LolPredictorPlugin(Settings())
        if args.command == "predict":
            output = plugin.predict(PredictionRequest(args.team_a, args.team_b, args.format))
        elif args.command == "ingest":
            output = ingest(plugin.settings, args.source, args.url)
        elif args.command == "publish-snapshot":
            output = publish_snapshot(plugin.settings)
        elif args.command == "publish-freeze":
            output = publish_freeze(plugin.settings)
        elif args.command == "backtest":
            output = backtest(plugin.settings, args.snapshot)
        elif args.command == "settle":
            output = settle(plugin.settings, args.results, args.signals)
        elif args.command == "collect-shadow":
            output = collect_shadow(plugin.settings, args.horizon_hours, args.output)
        elif args.command == "collect-holdout":
            output = collect_holdout(plugin.settings, args.horizon_hours)
        elif args.command == "audit-draft-coverage":
            target = args.output or plugin.settings.data_root / "reports" / "draft_coverage_latest.json"
            output = publish_audit(
                target,
                horizon_hours=args.horizon_hours,
                aliases_path=plugin.settings.data_root / "polymarket_aliases.json",
                registry_path=plugin.settings.data_root / "canonical_teams.json",
            )
        elif args.command == "health":
            output = health(plugin.settings, connectivity=args.connectivity)
        else:
            validate_env_example(args.path)
            output = {"valid": True}
        structured_log("command_completed", command=args.command, status=output.get("status", "SUCCEEDED"))
        print(json.dumps(output, ensure_ascii=False, sort_keys=True))
        return 0
    except (ContractError, ValueError, json.JSONDecodeError) as exc:
        structured_log("command_failed", command=args.command, kind="validation", error=str(exc))
        print(json.dumps({"status": "FAILED", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    except (OperationalError, OSError) as exc:
        structured_log("command_failed", command=args.command, kind="operational", error=str(exc))
        print(json.dumps({"status": "FAILED", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    except Exception as exc:
        structured_log("command_failed", command=args.command, kind="unexpected", error=type(exc).__name__)
        print(json.dumps({"status": "FAILED", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


def scheduler_main(argv: list[str] | None = None) -> int:
    from predictor_ops.cli import main as ops_main

    return ops_main(argv)
