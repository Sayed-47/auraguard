"""A tiny softmax classifier that trains in Python and runs on the ESP32.

Pure standard library: training is full-batch gradient descent on standardized
features, which is more than enough for the 8-11 feature windows used here.
The exported C header carries the scaler and weight matrices; the firmware
performs the same standardize -> dot -> softmax -> argmax steps.
"""

from __future__ import annotations

import json
import math
import random
from pathlib import Path
from typing import Sequence

MODEL_VERSION = 1


class SoftmaxRegression:
    def __init__(self, n_features: int, n_classes: int, class_names: Sequence[str], feature_names: Sequence[str]):
        if n_classes != len(class_names):
            raise ValueError("class name count mismatch")
        if n_features != len(feature_names):
            raise ValueError("feature name count mismatch")
        self.n_features = n_features
        self.n_classes = n_classes
        self.class_names = list(class_names)
        self.feature_names = list(feature_names)
        self.mean = [0.0] * n_features
        self.scale = [1.0] * n_features
        self.weights = [[0.0] * n_features for _ in range(n_classes)]
        self.bias = [0.0] * n_classes

    # ----- inference (mirrored in C) -----
    def predict_proba(self, features: Sequence[float]) -> list[float]:
        if len(features) != self.n_features:
            raise ValueError("feature vector length mismatch")
        logits = []
        for c in range(self.n_classes):
            total = self.bias[c]
            for f in range(self.n_features):
                scaled = (features[f] - self.mean[f]) / self.scale[f]
                total += self.weights[c][f] * scaled
            logits.append(total)
        top = max(logits)
        exps = [math.exp(v - top) for v in logits]
        norm = sum(exps)
        return [v / norm for v in exps]

    def predict(self, features: Sequence[float]) -> int:
        probs = self.predict_proba(features)
        return max(range(self.n_classes), key=lambda c: probs[c])

    # ----- training -----
    def fit(
        self,
        samples: Sequence[Sequence[float]],
        labels: Sequence[int],
        epochs: int = 1500,
        lr: float = 0.5,
        l2: float = 1e-4,
        seed: int = 0,
    ) -> list[float]:
        if len(samples) != len(labels) or not samples:
            raise ValueError("samples/labels length mismatch")
        n = len(samples)
        for f in range(self.n_features):
            column = [row[f] for row in samples]
            mu = sum(column) / n
            var = sum((v - mu) ** 2 for v in column) / n
            self.mean[f] = mu
            self.scale[f] = math.sqrt(var) or 1.0
        rng = random.Random(seed)
        self.weights = [[rng.uniform(-0.01, 0.01) for _ in range(self.n_features)] for _ in range(self.n_classes)]
        self.bias = [0.0] * self.n_classes
        scaled = [[(row[f] - self.mean[f]) / self.scale[f] for f in range(self.n_features)] for row in samples]
        history = []
        for _ in range(epochs):
            grad_w = [[0.0] * self.n_features for _ in range(self.n_classes)]
            grad_b = [0.0] * self.n_classes
            loss = 0.0
            for row, label in zip(scaled, labels):
                logits = [self.bias[c] + sum(self.weights[c][f] * row[f] for f in range(self.n_features)) for c in range(self.n_classes)]
                top = max(logits)
                exps = [math.exp(v - top) for v in logits]
                norm = sum(exps)
                probs = [v / norm for v in exps]
                loss -= math.log(max(probs[label], 1e-12))
                for c in range(self.n_classes):
                    delta = probs[c] - (1.0 if c == label else 0.0)
                    grad_b[c] += delta
                    for f in range(self.n_features):
                        grad_w[c][f] += delta * row[f]
            for c in range(self.n_classes):
                self.bias[c] -= lr * grad_b[c] / n
                for f in range(self.n_features):
                    grad = grad_w[c][f] / n + l2 * self.weights[c][f]
                    self.weights[c][f] -= lr * grad
            history.append(loss / n)
        return history

    def accuracy(self, samples: Sequence[Sequence[float]], labels: Sequence[int]) -> float:
        correct = sum(1 for row, label in zip(samples, labels) if self.predict(row) == label)
        return correct / max(1, len(labels))

    def confusion(self, samples: Sequence[Sequence[float]], labels: Sequence[int]) -> list[list[int]]:
        matrix = [[0] * self.n_classes for _ in range(self.n_classes)]
        for row, label in zip(samples, labels):
            matrix[label][self.predict(row)] += 1
        return matrix

    # ----- serialization -----
    def to_dict(self) -> dict:
        return {
            "version": MODEL_VERSION,
            "kind": "softmax_regression",
            "n_features": self.n_features,
            "n_classes": self.n_classes,
            "class_names": self.class_names,
            "feature_names": self.feature_names,
            "scaler": {"mean": self.mean, "scale": self.scale},
            "weights": self.weights,
            "bias": self.bias,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SoftmaxRegression":
        if data.get("version") != MODEL_VERSION or data.get("kind") != "softmax_regression":
            raise ValueError("unsupported model payload")
        model = cls(data["n_features"], data["n_classes"], data["class_names"], data["feature_names"])
        model.mean = [float(v) for v in data["scaler"]["mean"]]
        model.scale = [float(v) for v in data["scaler"]["scale"]]
        model.weights = [[float(v) for v in row] for row in data["weights"]]
        model.bias = [float(v) for v in data["bias"]]
        return model


def save_model(model: SoftmaxRegression, path: str | Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(model.to_dict(), indent=2) + "\n", encoding="utf-8")


def load_model(path: str | Path) -> SoftmaxRegression:
    return SoftmaxRegression.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


def _fmt(values: Sequence[float]) -> str:
    return ", ".join(f"{v:.8g}f" for v in values)


def export_c_header(motion: SoftmaxRegression, cry: SoftmaxRegression) -> str:
    """Render both models as a C header for the ESP32 AI sketch."""
    if motion.n_features != len(motion.feature_names) or cry.n_features != len(cry.feature_names):
        raise ValueError("model shape mismatch")
    lines = [
        "/* Generated by `python -m server.ai.train`. Do not edit by hand.",
        "   Weights are trained on simulator data; retrain with real captures when available. */",
        "#pragma once",
        "",
        f"#define AI_MOTION_N_FEATURES {motion.n_features}",
        f"#define AI_MOTION_N_CLASSES {motion.n_classes}",
        f"static const float AI_MOTION_MEAN[AI_MOTION_N_FEATURES] = {{{_fmt(motion.mean)}}};",
        f"static const float AI_MOTION_SCALE[AI_MOTION_N_FEATURES] = {{{_fmt(motion.scale)}}};",
        "static const float AI_MOTION_W[AI_MOTION_N_CLASSES][AI_MOTION_N_FEATURES] = {",
    ]
    for row in motion.weights:
        lines.append(f"  {{{_fmt(row)}}},")
    lines += [
        "};",
        f"static const float AI_MOTION_B[AI_MOTION_N_CLASSES] = {{{_fmt(motion.bias)}}};",
        "",
        f"#define AI_CRY_N_FEATURES {cry.n_features}",
        f"#define AI_CRY_N_CLASSES {cry.n_classes}",
        f"static const float AI_CRY_MEAN[AI_CRY_N_FEATURES] = {{{_fmt(cry.mean)}}};",
        f"static const float AI_CRY_SCALE[AI_CRY_N_FEATURES] = {{{_fmt(cry.scale)}}};",
        "static const float AI_CRY_W[AI_CRY_N_CLASSES][AI_CRY_N_FEATURES] = {",
    ]
    for row in cry.weights:
        lines.append(f"  {{{_fmt(row)}}},")
    lines += [
        "};",
        f"static const float AI_CRY_B[AI_CRY_N_CLASSES] = {{{_fmt(cry.bias)}}};",
        "",
    ]
    return "\n".join(lines)
