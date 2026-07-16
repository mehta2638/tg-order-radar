from pathlib import Path

from app.classification.ml import (
    MlFallback,
    MlPrediction,
    clear_model_cache,
    load_cached_artifact,
    predict_with_ml,
)
from app.classification.training import load_dataset, save_artifact, train_model
from app.core.config import Settings
from app.processing.normalization import normalize_text


def test_ml_confidently_detects_typical_order(tmp_path: Path) -> None:
    artifact_path = train_temp_artifact(tmp_path)

    result = predict_with_ml(
        normalize_text("Нужен лендинг для курса, бюджет 80к, сделать за 10 дней, связь @client"),
        ml_settings(artifact_path),
    )

    assert isinstance(result, MlPrediction)
    assert result.label == "order"
    assert result.confidence >= 0.7


def test_ml_service_ad_does_not_become_order(tmp_path: Path) -> None:
    artifact_path = train_temp_artifact(tmp_path)

    result = predict_with_ml(
        normalize_text("Делаю сайты и лендинги недорого, портфолио в профиле, пишите"),
        ml_settings(artifact_path),
    )

    assert isinstance(result, MlPrediction)
    assert result.label == "service_ad"


def test_low_confidence_uses_rules_fallback(tmp_path: Path) -> None:
    artifact_path = train_temp_artifact(tmp_path)

    result = predict_with_ml(
        normalize_text("Нужен лендинг, бюджет 100к"),
        ml_settings(artifact_path, min_confidence=0.999),
    )

    assert isinstance(result, MlFallback)
    assert result.reason == "low_confidence"


def test_missing_artifact_uses_rules_fallback(tmp_path: Path) -> None:
    result = predict_with_ml(
        normalize_text("Нужен сайт"),
        ml_settings(tmp_path / "missing.joblib"),
    )

    assert isinstance(result, MlFallback)
    assert result.reason == "artifact_unavailable"


def test_corrupted_artifact_does_not_break_prediction(tmp_path: Path) -> None:
    artifact_path = tmp_path / "broken.joblib"
    artifact_path.write_text("not a joblib artifact", encoding="utf-8")

    result = predict_with_ml(normalize_text("Нужен сайт"), ml_settings(artifact_path))

    assert isinstance(result, MlFallback)
    assert result.reason == "artifact_unavailable"


def test_model_loading_is_cached(tmp_path: Path) -> None:
    artifact_path = train_temp_artifact(tmp_path)
    settings = ml_settings(artifact_path)
    clear_model_cache()

    predict_with_ml(normalize_text("Нужен лендинг"), settings)
    predict_with_ml(normalize_text("Делаю сайты недорого"), settings)
    cache_info = load_cached_artifact.cache_info()

    assert cache_info.misses == 1
    assert cache_info.hits == 1


def train_temp_artifact(tmp_path: Path) -> Path:
    clear_model_cache()
    artifact = train_model(load_dataset(), model_version="test-ml-v1")
    artifact_path = tmp_path / "classifier.joblib"
    save_artifact(artifact, artifact_path)
    return artifact_path


def ml_settings(artifact_path: Path, *, min_confidence: float = 0.7) -> Settings:
    return Settings(
        ml_classification_enabled=True,
        ml_model_artifact_path=str(artifact_path),
        ml_min_confidence=min_confidence,
    )
