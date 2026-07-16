from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from joblib import dump, load
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    confusion_matrix,
)
from sklearn.pipeline import FeatureUnion, Pipeline

from app.classification.rules import (
    ClassificationInput,
    EntityFact,
    classify_rules,
)
from app.core.config import Settings
from app.processing.keywords import KeywordRule, compile_keyword_rules
from app.processing.pipeline import PrefilterResult, process_text

CLASSIFICATION_LABELS: tuple[str, ...] = (
    "order",
    "vacancy",
    "service_ad",
    "resume",
    "partnership",
    "spam",
    "discussion",
    "irrelevant",
)
ARTIFACT_SCHEMA_VERSION = "classification-artifact-v1"
FEATURE_SCHEMA_VERSION = "tfidf-word12-char35-v1"
DEFAULT_DATASET_PATH = Path("tests/fixtures/rules_regression_dataset.json")

POSITIVE_RULES = compile_keyword_rules(
    [
        KeywordRule(None, "нужен сайт", "ru", 5, "explicit_need"),
        KeywordRule(None, "нужен лендинг", "ru", 5, "landing_page"),
        KeywordRule(None, "нужно", "ru", 4, "explicit_need"),
        KeywordRule(None, "ищу разработчика", "ru", 4, "explicit_need"),
        KeywordRule(None, "ищу веб-разработчика", "ru", 4, "explicit_need"),
        KeywordRule(None, "требуется интернет-магазин", "ru", 5, "ecommerce"),
        KeywordRule(None, "доработать", "ru", 4, "revision"),
        KeywordRule(None, r"кто\s+может\s+доработать", "ru", 4, "revision", True),
    ]
)
NEGATIVE_RULES = compile_keyword_rules(
    [
        KeywordRule(None, "делаю сайты", "ru", 5, "negative"),
        KeywordRule(None, "сайты недорого", "ru", 5, "negative"),
        KeywordRule(None, "моё портфолио", "ru", 4, "negative"),
        KeywordRule(None, "портфолио в профиле", "ru", 4, "negative"),
        KeywordRule(None, "выполню", "ru", 4, "negative"),
        KeywordRule(None, "оказываю услуги", "ru", 4, "negative"),
        KeywordRule(None, "ищу работу", "ru", 5, "negative"),
        KeywordRule(None, "резюме", "ru", 5, "negative"),
        KeywordRule(None, "опыт работы", "ru", 3, "negative"),
        KeywordRule(None, "создаю интернет-магазины", "ru", 4, "negative"),
        KeywordRule(None, "разработаю лендинг", "ru", 4, "negative"),
    ]
)


@dataclass(frozen=True)
class LabeledExample:
    text: str
    label: str
    normalized_text: str
    text_hash: str


@dataclass(frozen=True)
class DatasetSplit:
    train: list[LabeledExample]
    holdout: list[LabeledExample]


def load_dataset(path: Path = DEFAULT_DATASET_PATH) -> list[LabeledExample]:
    raw_examples = json.loads(path.read_text(encoding="utf-8"))
    examples: list[LabeledExample] = []
    for item in raw_examples:
        text = str(item["text"])
        label = str(item["label"])
        if label not in CLASSIFICATION_LABELS:
            raise ValueError(f"Unknown label in dataset: {label}")
        processed = process_text(
            text,
            positive_rules=POSITIVE_RULES,
            negative_rules=NEGATIVE_RULES,
        )
        text_hash = hashlib.sha256(processed.normalized_text.encode("utf-8")).hexdigest()
        examples.append(
            LabeledExample(
                text=text,
                label=label,
                normalized_text=processed.normalized_text,
                text_hash=text_hash,
            )
        )
    return examples


def dataset_checksum(examples: list[LabeledExample]) -> str:
    payload = [
        {"text_hash": example.text_hash, "label": example.label}
        for example in sorted(examples, key=lambda item: (item.text_hash, item.label))
    ]
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def split_dataset(
    examples: list[LabeledExample],
    *,
    holdout_ratio: float = 0.3,
) -> DatasetSplit:
    groups_by_label: dict[str, dict[str, list[LabeledExample]]] = {}
    for example in examples:
        groups_by_label.setdefault(example.label, {}).setdefault(example.text_hash, []).append(
            example
        )

    train: list[LabeledExample] = []
    holdout: list[LabeledExample] = []
    for label in CLASSIFICATION_LABELS:
        groups = groups_by_label.get(label, {})
        ordered_groups = [groups[key] for key in sorted(groups)]
        if not ordered_groups:
            continue
        holdout_groups_count = max(1, round(len(ordered_groups) * holdout_ratio))
        if holdout_groups_count >= len(ordered_groups):
            holdout_groups_count = max(0, len(ordered_groups) - 1)
        for index, group in enumerate(ordered_groups):
            target = holdout if index < holdout_groups_count else train
            target.extend(group)
    return DatasetSplit(train=sorted(train, key=sort_key), holdout=sorted(holdout, key=sort_key))


def train_model(
    examples: list[LabeledExample],
    *,
    model_version: str,
    holdout_ratio: float = 0.3,
) -> dict[str, Any]:
    split = split_dataset(examples, holdout_ratio=holdout_ratio)
    pipeline = build_pipeline()
    pipeline.fit(
        [example.normalized_text for example in split.train],
        [example.label for example in split.train],
    )
    metrics = evaluate_predictions(
        expected=[example.label for example in split.holdout],
        predicted=list(pipeline.predict([example.normalized_text for example in split.holdout])),
    )
    return {
        "schema_version": ARTIFACT_SCHEMA_VERSION,
        "model_version": model_version,
        "trained_at": datetime.now(UTC).isoformat(),
        "classes": list(CLASSIFICATION_LABELS),
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "dataset_checksum": dataset_checksum(examples),
        "metrics": metrics,
        "train_size": len(split.train),
        "holdout_size": len(split.holdout),
        "model": pipeline,
    }


def save_artifact(artifact: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    dump(artifact, path)


def load_artifact(path: Path) -> dict[str, Any]:
    artifact = load(path)
    if not isinstance(artifact, dict):
        raise ValueError("Model artifact is not a dictionary.")
    if artifact.get("schema_version") != ARTIFACT_SCHEMA_VERSION:
        raise ValueError("Unsupported model artifact schema version.")
    if artifact.get("feature_schema_version") != FEATURE_SCHEMA_VERSION:
        raise ValueError("Unsupported feature schema version.")
    classes = artifact.get("classes")
    if not isinstance(classes, list) or not set(classes).issubset(CLASSIFICATION_LABELS):
        raise ValueError("Model artifact contains unknown classes.")
    if "model" not in artifact:
        raise ValueError("Model artifact has no model.")
    return artifact


def evaluate_artifact(path: Path, examples: list[LabeledExample]) -> dict[str, Any]:
    artifact = load_artifact(path)
    split = split_dataset(examples)
    model = artifact["model"]
    predicted = list(model.predict([example.normalized_text for example in split.holdout]))
    return evaluate_predictions(
        expected=[example.label for example in split.holdout],
        predicted=predicted,
    ) | {
        "model_version": artifact["model_version"],
        "dataset_checksum": dataset_checksum(examples),
        "train_size": len(split.train),
        "holdout_size": len(split.holdout),
    }


def rules_baseline(examples: list[LabeledExample]) -> dict[str, Any]:
    split = split_dataset(examples)
    predictions: list[str] = [
        classify_rules(input_from_text(example.text), settings=Settings()).label
        for example in split.holdout
    ]
    return evaluate_predictions(
        expected=[example.label for example in split.holdout],
        predicted=predictions,
    ) | {
        "dataset_checksum": dataset_checksum(examples),
        "train_size": len(split.train),
        "holdout_size": len(split.holdout),
    }


def build_pipeline() -> Pipeline:
    features = FeatureUnion(
        [
            (
                "word",
                TfidfVectorizer(
                    analyzer="word",
                    ngram_range=(1, 2),
                    min_df=1,
                    sublinear_tf=True,
                ),
            ),
            (
                "char",
                TfidfVectorizer(
                    analyzer="char_wb",
                    ngram_range=(3, 5),
                    min_df=1,
                    sublinear_tf=True,
                ),
            ),
        ]
    )
    return Pipeline(
        [
            ("features", features),
            (
                "classifier",
                LogisticRegression(
                    C=10.0,
                    class_weight="balanced",
                    max_iter=1000,
                    random_state=42,
                ),
            ),
        ]
    )


def evaluate_predictions(
    *,
    expected: list[str],
    predicted: list[str],
) -> dict[str, Any]:
    report = classification_report(
        expected,
        predicted,
        labels=list(CLASSIFICATION_LABELS),
        output_dict=True,
        zero_division=0,
    )
    matrix = confusion_matrix(expected, predicted, labels=list(CLASSIFICATION_LABELS))
    return {
        "accuracy": float(accuracy_score(expected, predicted)),
        "macro_precision": float(report["macro avg"]["precision"]),
        "macro_recall": float(report["macro avg"]["recall"]),
        "macro_f1": float(report["macro avg"]["f1-score"]),
        "weighted_precision": float(report["weighted avg"]["precision"]),
        "weighted_recall": float(report["weighted avg"]["recall"]),
        "weighted_f1": float(report["weighted avg"]["f1-score"]),
        "per_class": {
            label: {
                "precision": float(report[label]["precision"]),
                "recall": float(report[label]["recall"]),
                "f1": float(report[label]["f1-score"]),
                "support": int(report[label]["support"]),
            }
            for label in CLASSIFICATION_LABELS
        },
        "confusion_matrix": {
            "labels": list(CLASSIFICATION_LABELS),
            "matrix": matrix.tolist(),
        },
    }


def input_from_text(text: str) -> ClassificationInput:
    processed = process_text(
        text,
        positive_rules=POSITIVE_RULES,
        negative_rules=NEGATIVE_RULES,
    )
    return input_from_prefilter(processed)


def input_from_prefilter(result: PrefilterResult) -> ClassificationInput:
    facts = [*keyword_facts(result), *entity_facts(result)]
    return ClassificationInput(
        normalized_text=result.normalized_text,
        published_at=datetime.now(UTC),
        passed_prefilter=result.passed_prefilter,
        keyword_hits=[fact for fact in facts if fact.type == "keyword_hit"],
        negative_hits=[fact for fact in facts if fact.type == "negative_keyword_hit"],
        project_types=[fact for fact in facts if fact.type == "project_type"],
        budgets=[fact for fact in facts if fact.type == "budget"],
        deadlines=[fact for fact in facts if fact.type == "deadline"],
        contacts=[fact for fact in facts if fact.type == "contact"],
    )


def keyword_facts(result: PrefilterResult) -> list[EntityFact]:
    return [
        *[
            EntityFact(
                type="keyword_hit",
                value_text=hit.matched_text,
                value_norm={"phrase": hit.phrase, "category": hit.category},
            )
            for hit in result.keyword_hits
        ],
        *[
            EntityFact(
                type="negative_keyword_hit",
                value_text=hit.matched_text,
                value_norm={"phrase": hit.phrase, "category": hit.category},
            )
            for hit in result.negative_hits
        ],
    ]


def entity_facts(result: PrefilterResult) -> list[EntityFact]:
    return [
        EntityFact(
            type=entity.type,
            value_text=entity.value_text,
            value_norm=entity.value_norm,
        )
        for entity in result.extracted_entities
    ]


def sort_key(example: LabeledExample) -> tuple[str, str, str]:
    return (example.label, example.text_hash, example.text)
