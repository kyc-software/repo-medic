"""Leakage-aware chronological training and runtime model adapter."""

from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import cast

import joblib
import mlflow
import numpy as np
from sklearn.calibration import CalibratedClassifierCV
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.metrics import (
    f1_score,
    mean_absolute_error,
    median_absolute_error,
    recall_score,
)
from sklearn.pipeline import Pipeline

from repomedic.adapters.github import IssueRecord
from repomedic.domain.models import IssueSubmission, IssueType, PredictionBundle


@dataclass(frozen=True)
class ModelArtifact:
    classifier: CalibratedClassifierCV
    regressor: Pipeline
    classifier_version: str
    regressor_version: str


def issue_text(record: IssueRecord) -> str:
    return f"{record.title}\n\n{record.body}"


def chronological_split(records: tuple[IssueRecord, ...]) -> tuple[slice, slice, slice]:
    if len(records) < 20:
        raise ValueError("at least 20 issues are required for chronological evaluation")
    train_end = int(len(records) * 0.7)
    validation_end = int(len(records) * 0.85)
    return slice(0, train_end), slice(train_end, validation_end), slice(validation_end, None)


def train_models(
    records: tuple[IssueRecord, ...], artifact_path: Path, tracking_uri: str
) -> dict[str, float]:
    train_slice, _, _ = chronological_split(records)
    texts = [issue_text(record) for record in records]
    labels = [record.issue_type.value for record in records]
    classifier_base = Pipeline(
        [
            ("tfidf", TfidfVectorizer(ngram_range=(1, 2), min_df=2, max_features=40_000)),
            (
                "classifier",
                LogisticRegression(class_weight="balanced", max_iter=1_000, random_state=42),
            ),
        ]
    )
    classifier = CalibratedClassifierCV(classifier_base, method="sigmoid", cv=3)
    classifier.fit(texts[train_slice], labels[train_slice])

    closed_indices = [
        index for index, record in enumerate(records) if record.close_days is not None
    ]
    closed_train = [index for index in closed_indices if index < (train_slice.stop or 0)]
    if not closed_train:
        raise ValueError("closed issues are required in both train and test periods")
    regressor = Pipeline(
        [
            ("tfidf", TfidfVectorizer(ngram_range=(1, 2), min_df=2, max_features=40_000)),
            ("regressor", Ridge(alpha=10.0)),
        ]
    )
    regressor.fit(
        [texts[index] for index in closed_train],
        [cast(float, records[index].close_days) for index in closed_train],
    )
    artifact = ModelArtifact(
        classifier=classifier,
        regressor=regressor,
        classifier_version="tfidf-calibrated-logreg-v1",
        regressor_version="tfidf-ridge-v1",
    )
    metrics = evaluate_artifact(records, artifact)
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(artifact, artifact_path)
    mlflow.set_tracking_uri(tracking_uri)
    mlflow.set_experiment("repomedic-predictive-models")
    with mlflow.start_run():
        mlflow.log_params({"split": "chronological-70-15-15", "records": len(records)})
        mlflow.log_metrics(metrics)
        mlflow.log_artifact(str(artifact_path))
    return metrics


def evaluate_models(records: tuple[IssueRecord, ...], artifact_path: Path) -> dict[str, float]:
    return evaluate_artifact(records, cast(ModelArtifact, joblib.load(artifact_path)))


def evaluate_artifact(
    records: tuple[IssueRecord, ...], artifact: ModelArtifact
) -> dict[str, float]:
    train_slice, _, test_slice = chronological_split(records)
    texts = [issue_text(record) for record in records]
    labels = [record.issue_type.value for record in records]
    started = perf_counter()
    predicted = artifact.classifier.predict(texts[test_slice])
    probabilities = artifact.classifier.predict_proba(texts[test_slice])
    inference_ms = (perf_counter() - started) * 1_000 / len(texts[test_slice])
    classes = [str(value) for value in artifact.classifier.classes_]
    recalls = recall_score(labels[test_slice], predicted, labels=classes, average=None)
    majority_label = max(set(labels[train_slice]), key=labels[train_slice].count)
    closed_indices = [
        index for index, record in enumerate(records) if record.close_days is not None
    ]
    closed_train = [index for index in closed_indices if index < (train_slice.stop or 0)]
    closed_test = [index for index in closed_indices if index >= (test_slice.start or 0)]
    if not closed_train or not closed_test:
        raise ValueError("closed issues are required in both train and test periods")
    close_predictions = np.maximum(
        artifact.regressor.predict([texts[index] for index in closed_test]), 0
    )
    close_actual = [cast(float, records[index].close_days) for index in closed_test]
    metrics = {
        "macro_f1": float(f1_score(labels[test_slice], predicted, average="macro")),
        "macro_recall": float(recall_score(labels[test_slice], predicted, average="macro")),
        "expected_calibration_error": expected_calibration_error(
            labels[test_slice], probabilities, classes
        ),
        "inference_ms_per_issue": inference_ms,
        "close_mae_days": float(mean_absolute_error(close_actual, close_predictions)),
        "close_median_ae_days": float(median_absolute_error(close_actual, close_predictions)),
        "classifier_majority_macro_f1": float(
            f1_score(
                labels[test_slice],
                [majority_label] * len(labels[test_slice]),
                average="macro",
            )
        ),
        "regressor_median_baseline_mae": float(
            mean_absolute_error(
                close_actual,
                [float(np.median([records[index].close_days for index in closed_train]))]
                * len(close_actual),
            )
        ),
    }
    metrics.update(
        {f"recall_{label}": float(value) for label, value in zip(classes, recalls, strict=True)}
    )
    return metrics


def expected_calibration_error(
    actual: list[str], probabilities: np.ndarray, classes: list[str], bins: int = 10
) -> float:
    confidences = probabilities.max(axis=1)
    predicted = np.asarray(classes)[probabilities.argmax(axis=1)]
    correctness = predicted == np.asarray(actual)
    error = 0.0
    for lower in np.linspace(0, 1, bins, endpoint=False):
        upper = lower + 1 / bins
        members = (confidences > lower) & (confidences <= upper)
        if members.any():
            error += float(members.mean()) * abs(
                float(correctness[members].mean()) - float(confidences[members].mean())
            )
    return error


class SklearnPredictor:
    def __init__(self, artifact_path: Path) -> None:
        self._artifact = cast(ModelArtifact, joblib.load(artifact_path))

    async def predict(self, submission: IssueSubmission) -> PredictionBundle:
        text = f"{submission.title}\n\n{submission.body}"
        probabilities = self._artifact.classifier.predict_proba([text])[0]
        classes = self._artifact.classifier.classes_
        winning_index = int(np.argmax(probabilities))
        close_days = max(float(self._artifact.regressor.predict([text])[0]), 0)
        return PredictionBundle(
            issue_type=IssueType(str(classes[winning_index])),
            calibrated_confidence=float(probabilities[winning_index]),
            predicted_close_days=close_days,
            classifier_version=self._artifact.classifier_version,
            regressor_version=self._artifact.regressor_version,
        )
