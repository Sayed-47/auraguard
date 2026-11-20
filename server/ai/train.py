"""Train the AuraGuard baby-unit classifiers and export firmware weights.

Usage (from the repository root):

    python -m server.ai.train --n 600 --seed 7

Writes ``server/ai/weights/motion.json`` and ``server/ai/weights/cry.json``
and regenerates ``firmware/esp32_baby_unit_ai/ai_weights.h``. Training data
comes from :mod:`server.ai.simulate`; replace those generators' output with
real nursery captures when they exist, keeping the same feature functions.
"""

from __future__ import annotations

import argparse
import random
from pathlib import Path

from server.ai.features import AUDIO_FEATURE_NAMES, MOTION_FEATURE_NAMES
from server.ai.models import SoftmaxRegression, export_c_header, save_model
from server.ai.simulate import CRY_CLASSES, MOTION_CLASSES, simulate_audio_dataset, simulate_motion_dataset

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_WEIGHTS = ROOT / "server" / "ai" / "weights"
DEFAULT_HEADER = ROOT / "firmware" / "esp32_baby_unit_ai" / "ai_weights.h"


def _split(samples: list, labels: list[int], seed: int, share: float = 0.8):
    order = list(range(len(samples)))
    random.Random(seed).shuffle(order)
    cut = int(len(order) * share)
    train_idx, test_idx = order[:cut], order[cut:]
    return (
        [samples[i] for i in train_idx], [labels[i] for i in train_idx],
        [samples[i] for i in test_idx], [labels[i] for i in test_idx],
    )


def train_motion(n_per_class: int, seed: int) -> tuple[SoftmaxRegression, dict]:
    samples, labels = simulate_motion_dataset(n_per_class, seed)
    x_tr, y_tr, x_te, y_te = _split(samples, labels, seed)
    model = SoftmaxRegression(len(MOTION_FEATURE_NAMES), len(MOTION_CLASSES), MOTION_CLASSES, MOTION_FEATURE_NAMES)
    model.fit(x_tr, y_tr, epochs=900, lr=0.5, seed=seed)
    metrics = {"train_accuracy": model.accuracy(x_tr, y_tr), "test_accuracy": model.accuracy(x_te, y_te), "confusion": model.confusion(x_te, y_te)}
    return model, metrics


def train_cry(n_per_class: int, seed: int) -> tuple[SoftmaxRegression, dict]:
    samples, labels = simulate_audio_dataset(n_per_class, seed + 1)
    x_tr, y_tr, x_te, y_te = _split(samples, labels, seed)
    model = SoftmaxRegression(len(AUDIO_FEATURE_NAMES), len(CRY_CLASSES), CRY_CLASSES, AUDIO_FEATURE_NAMES)
    model.fit(x_tr, y_tr, epochs=1200, lr=0.5, seed=seed)
    metrics = {"train_accuracy": model.accuracy(x_tr, y_tr), "test_accuracy": model.accuracy(x_te, y_te), "confusion": model.confusion(x_te, y_te)}
    return model, metrics


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n", type=int, default=600, help="simulator windows per class")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--weights-dir", type=Path, default=DEFAULT_WEIGHTS)
    parser.add_argument("--header", type=Path, default=DEFAULT_HEADER)
    args = parser.parse_args()

    motion, motion_metrics = train_motion(args.n, args.seed)
    cry, cry_metrics = train_cry(args.n, args.seed)

    save_model(motion, args.weights_dir / "motion.json")
    save_model(cry, args.weights_dir / "cry.json")
    args.header.parent.mkdir(parents=True, exist_ok=True)
    args.header.write_text(export_c_header(motion, cry), encoding="utf-8")

    print(f"motion: train={motion_metrics['train_accuracy']:.3f} test={motion_metrics['test_accuracy']:.3f} classes={MOTION_CLASSES}")
    for row in motion_metrics["confusion"]:
        print(f"  {row}")
    print(f"cry:    train={cry_metrics['train_accuracy']:.3f} test={cry_metrics['test_accuracy']:.3f} classes={CRY_CLASSES}")
    for row in cry_metrics["confusion"]:
        print(f"  {row}")
    print(f"wrote {args.weights_dir / 'motion.json'}, {args.weights_dir / 'cry.json'}, {args.header}")


if __name__ == "__main__":
    main()
