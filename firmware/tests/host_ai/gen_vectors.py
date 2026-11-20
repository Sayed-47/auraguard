"""Generate cross-validation vectors for the host-compiled AI sketch.

Run from the repository root:

    python firmware/tests/host_ai/gen_vectors.py

Writes motion_vectors.csv and cry_vectors.csv next to this script. The host
harness feeds the raw values through the C feature+inference port and compares
probabilities against the Python reference within tolerance.
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from server.ai import simulate as S
from server.ai.features import audio_window_features, motion_window_features
from server.ai.models import load_model
from server.ai.train import DEFAULT_WEIGHTS

HERE = Path(__file__).resolve().parent


def main() -> None:
    motion = load_model(DEFAULT_WEIGHTS / "motion.json")
    cry = load_model(DEFAULT_WEIGHTS / "cry.json")

    rng = random.Random(2026)
    rows = []
    for label, count in ((0, 4), (1, 4), (2, 4)):
        for _ in range(count):
            window = S.simulate_motion_window(label, rng)
            feats = motion_window_features(window)
            probs = motion.predict_proba(feats)
            values = []
            for (ax, ay, az, gx, gy, gz) in window:
                svm = (ax * ax + ay * ay + az * az) ** 0.5
                gmag = (gx * gx + gy * gy + gz * gz) ** 0.5
                values += [ax, ay, az, svm, gmag]
            rows.append([label, *probs, *values])
    with (HERE / "motion_vectors.csv").open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(",".join(f"{v:.6f}" for v in row) + "\n")

    rows = []
    for label, count in ((0, 6), (1, 6)):
        for _ in range(count):
            bursts = S.simulate_audio_window(label, rng)
            quantized = [[int(round(min(4095, max(0, v)))) for v in burst] for burst in bursts]
            feats = audio_window_features(quantized)
            prob = cry.predict_proba(feats)[1]
            flat = [v for burst in quantized for v in burst]
            rows.append([label, prob, *flat])
    with (HERE / "cry_vectors.csv").open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(",".join(f"{v:.6f}" if isinstance(v, float) and not float(v).is_integer() else str(int(v)) for v in row) + "\n")

    print(f"wrote {HERE / 'motion_vectors.csv'} and {HERE / 'cry_vectors.csv'}")


if __name__ == "__main__":
    main()
