import argparse
import json
import sys
from pathlib import Path

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
    sub.add_parser("health")
    check = sub.add_parser("validate-env")
    check.add_argument("path", type=Path, nargs="?", default=Path(".env.example"))
    args = parser.parse_args(argv)
    try:
        plugin = LolPredictorPlugin(Settings())
        if args.command == "predict":
            output = plugin.predict(PredictionRequest(args.team_a, args.team_b, args.format))
        elif args.command == "health":
            output = plugin.health()
        else:
            validate_env_example(args.path)
            output = {"valid": True}
        print(json.dumps(output, ensure_ascii=False, sort_keys=True))
        return 0
    except Exception as exc:
        print(json.dumps({"status": "FAILED", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


def scheduler_main(argv: list[str] | None = None) -> int:
    from predictor_ops.cli import main as ops_main

    return ops_main(argv)
