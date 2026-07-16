from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.classification.training import CLASSIFICATION_LABELS, load_artifact
from app.core.config import Settings


@dataclass(frozen=True)
class MlPrediction:
    label: str
    confidence: float
    model_version: str
    explanation: dict[str, Any]


@dataclass(frozen=True)
class MlFallback:
    reason: str
    details: dict[str, Any]


MlResult = MlPrediction | MlFallback


def predict_with_ml(normalized_text: str, settings: Settings) -> MlResult:
    if not settings.ml_classification_enabled:
        return MlFallback(reason="ml_disabled", details={})
    try:
        artifact = load_cached_artifact(
            settings.ml_model_artifact_path,
            settings.ml_model_version,
        )
        model = artifact["model"]
        probabilities = model.predict_proba([normalized_text])[0]
        class_labels = list(model.classes_)
        best_index = int(probabilities.argmax())
        label = str(class_labels[best_index])
        confidence = float(probabilities[best_index])
        model_version = str(artifact["model_version"])
    except Exception as exc:
        return MlFallback(
            reason="artifact_unavailable",
            details={"error_type": type(exc).__name__, "message": str(exc)},
        )

    if label not in CLASSIFICATION_LABELS:
        return MlFallback(reason="unknown_class", details={"label": label})
    if confidence < settings.ml_min_confidence:
        return MlFallback(
            reason="low_confidence",
            details={
                "label": label,
                "confidence": round(confidence, 4),
                "min_confidence": settings.ml_min_confidence,
            },
        )
    return MlPrediction(
        label=label,
        confidence=round(confidence, 4),
        model_version=model_version,
        explanation={
            "model_version": model_version,
            "feature_schema_version": artifact["feature_schema_version"],
            "top_terms": top_contributing_terms(model, normalized_text, label),
        },
    )


@lru_cache(maxsize=8)
def load_cached_artifact(path: str, expected_version: str | None) -> dict[str, Any]:
    artifact = load_artifact(Path(path))
    if expected_version and artifact.get("model_version") != expected_version:
        raise ValueError(
            "Configured ML_MODEL_VERSION does not match artifact model_version: "
            f"{expected_version} != {artifact.get('model_version')}"
        )
    return artifact


def clear_model_cache() -> None:
    load_cached_artifact.cache_clear()


def top_contributing_terms(
    model: Any, normalized_text: str, label: str, limit: int = 5
) -> list[str]:
    features = model.named_steps["features"]
    classifier = model.named_steps["classifier"]
    feature_names = list(features.get_feature_names_out())
    vector = features.transform([normalized_text])
    class_index = list(classifier.classes_).index(label)
    coefficients = classifier.coef_[class_index]
    contributions = vector.multiply(coefficients).tocoo()
    ranked = sorted(
        zip(contributions.col, contributions.data, strict=True),
        key=lambda item: float(item[1]),
        reverse=True,
    )
    terms: list[str] = []
    for column, value in ranked:
        if value <= 0:
            continue
        term = strip_feature_prefix(str(feature_names[int(column)]))
        if is_safe_term(term) and term not in terms:
            terms.append(term)
        if len(terms) >= limit:
            break
    return terms


def strip_feature_prefix(term: str) -> str:
    return term.split("__", 1)[1] if "__" in term else term


def is_safe_term(term: str) -> bool:
    if len(term) > 32:
        return False
    lowered = term.casefold()
    if "@" in lowered or "http" in lowered or "t.me" in lowered:
        return False
    return re.search(r"\d{4,}", lowered) is None
