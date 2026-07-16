from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from app.classification.ml import predict_with_ml
from app.classification.training import (
    DEFAULT_DATASET_PATH,
    evaluate_artifact,
    load_dataset,
    rules_baseline,
    save_artifact,
    train_model,
)
from app.core.config import Settings
from app.processing.normalization import normalize_text


def main() -> None:
    parser = argparse.ArgumentParser(description="Train and evaluate the TF-IDF ML classifier.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    baseline_parser = subparsers.add_parser("baseline", help="Evaluate rules-only baseline.")
    add_dataset_arg(baseline_parser)

    train_parser = subparsers.add_parser("train", help="Train and save an ML artifact.")
    add_dataset_arg(train_parser)
    train_parser.add_argument("--artifact", required=True, type=Path)
    train_parser.add_argument("--model-version", required=True)

    evaluate_parser = subparsers.add_parser("evaluate", help="Evaluate an ML artifact on holdout.")
    add_dataset_arg(evaluate_parser)
    evaluate_parser.add_argument("--artifact", required=True, type=Path)

    predict_parser = subparsers.add_parser(
        "predict", help="Run one prediction through ML/fallback."
    )
    predict_parser.add_argument("--artifact", required=True, type=Path)
    predict_parser.add_argument("--text", required=True)
    predict_parser.add_argument("--min-confidence", type=float, default=0.7)
    predict_parser.add_argument("--enabled", action=argparse.BooleanOptionalAction, default=True)

    args = parser.parse_args()
    if args.command == "baseline":
        emit(rules_baseline(load_dataset(args.dataset)))
    elif args.command == "train":
        examples = load_dataset(args.dataset)
        artifact = train_model(examples, model_version=args.model_version)
        save_artifact(artifact, args.artifact)
        emit(strip_model(artifact))
    elif args.command == "evaluate":
        emit(evaluate_artifact(args.artifact, load_dataset(args.dataset)))
    elif args.command == "predict":
        settings = Settings(
            ml_classification_enabled=args.enabled,
            ml_model_artifact_path=str(args.artifact),
            ml_min_confidence=args.min_confidence,
        )
        result = predict_with_ml(normalize_text(args.text), settings)
        emit(result.__dict__)


def add_dataset_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--dataset", default=DEFAULT_DATASET_PATH, type=Path)


def strip_model(artifact: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in artifact.items() if key != "model"}


def emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
