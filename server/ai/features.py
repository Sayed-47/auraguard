"""Feature extraction shared by the Python trainer and the ESP32 AI sketch.

Every function in this module has a line-for-line C counterpart in
``firmware/esp32_baby_unit_ai/esp32_baby_unit_ai.ino``. Keep the math,
constants, and feature order identical on both sides; ``server/test_ai.py``
guards the contract.

Motion window: 100 samples at 50 Hz (2 s) of MPU6050 acceleration (g) and
gyroscope (deg/s). Audio observation: 8 bursts of 128 ADC samples at 2 kHz,
spread 200 ms apart (1.6 s total), from the analog sound sensor centered near
2048 counts. The firmware only captures bursts while the room is loud, so
audio analysis never starves motion sampling for long.
"""

from __future__ import annotations

import math
from typing import Sequence

MOTION_SAMPLE_RATE = 50
MOTION_WINDOW_SAMPLES = 100
MOTION_POST_SAMPLES = 20
MOTION_TILT_EDGE = 25
FREEFALL_G = 0.5

AUDIO_SAMPLE_RATE = 2000
AUDIO_BURSTS = 8
AUDIO_BURST_SAMPLES = 128
AUDIO_BURST_SPACING_MS = 200
AUDIO_ADC_CENTER = 2048.0
AUDIO_ADC_FULL_SCALE = 4095.0

# Goertzel band edges as DFT bins of a 128-point window at 2 kHz (15.625 Hz/bin).
BAND_SUB_BINS = (5, 16)    # 78-250 Hz: fan/appliance hum
BAND_LOW_BINS = (17, 34)   # 266-531 Hz: baby-cry fundamental band
BAND_MID_BINS = (35, 63)   # 547-984 Hz: cry harmonics / voiced fricatives
GOERTZEL_MIN_BIN = BAND_SUB_BINS[0]
GOERTZEL_MAX_BIN = BAND_MID_BINS[1]

MOTION_FEATURE_NAMES = [
    "svm_mean", "svm_std", "svm_max", "svm_min", "freefall_frac",
    "jerk_rms", "gyro_mean", "gyro_max", "post_std", "tilt_deg", "svm_zcr",
]
AUDIO_FEATURE_NAMES = [
    "rms_mean", "p2p_max", "zcr_mean", "sub_share", "low_share",
    "mid_share", "env_mod", "env_range", "duty",
]

_EPS = 1e-9


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values)


def _std(values: Sequence[float], mean: float | None = None) -> float:
    mu = _mean(values) if mean is None else mean
    return math.sqrt(sum((v - mu) ** 2 for v in values) / len(values))


def goertzel_power(samples: Sequence[float], bin_index: int) -> float:
    """Normalized Goertzel power at ``bin_index`` for a real signal.

    The result is divided by (N/2)^2 so a pure sine of amplitude A yields
    about A^2 regardless of the window length. Summed over all bins this
    approximates 2 * rms^2 (Parseval), which the band-share features rely on.
    This exact normalization is used by the firmware.
    """
    n = len(samples)
    omega = 2.0 * math.pi * bin_index / n
    coeff = 2.0 * math.cos(omega)
    s0 = s1 = s2 = 0.0
    for value in samples:
        s0 = value + coeff * s1 - s2
        s2 = s1
        s1 = s0
    power = s1 * s1 + s2 * s2 - coeff * s1 * s2
    half = n / 2.0
    return power / (half * half)


def motion_window_features(window: Sequence[Sequence[float]]) -> list[float]:
    """Extract the 11 motion features from a 2 s MPU6050 window.

    ``window`` is a sequence of ``(ax, ay, az, gx, gy, gz)`` tuples with
    acceleration in g and gyro in deg/s, exactly ``MOTION_WINDOW_SAMPLES``
    long. Raises ``ValueError`` on the wrong length.
    """
    if len(window) != MOTION_WINDOW_SAMPLES:
        raise ValueError(f"motion window must hold {MOTION_WINDOW_SAMPLES} samples")
    svm = [math.sqrt(s[0] * s[0] + s[1] * s[1] + s[2] * s[2]) for s in window]
    gmag = [math.sqrt(s[3] * s[3] + s[4] * s[4] + s[5] * s[5]) for s in window]

    svm_mean = _mean(svm)
    svm_std = _std(svm, svm_mean)
    svm_max = max(svm)
    svm_min = min(svm)
    freefall_frac = sum(1 for v in svm if v < FREEFALL_G) / len(svm)

    jerk = [(svm[i] - svm[i - 1]) * MOTION_SAMPLE_RATE for i in range(1, len(svm))]
    jerk_rms = math.sqrt(_mean([j * j for j in jerk]))

    gyro_mean = _mean(gmag)
    gyro_max = max(gmag)

    post = svm[-MOTION_POST_SAMPLES:]
    post_std = _std(post)

    first = window[:MOTION_TILT_EDGE]
    last = window[-MOTION_TILT_EDGE:]
    first_mean = [_mean([s[axis] for s in first]) for axis in range(3)]
    last_mean = [_mean([s[axis] for s in last]) for axis in range(3)]
    dot = sum(a * b for a, b in zip(first_mean, last_mean))
    norm = math.sqrt(sum(a * a for a in first_mean)) * math.sqrt(sum(b * b for b in last_mean))
    tilt_deg = math.degrees(math.acos(max(-1.0, min(1.0, dot / (norm + _EPS)))))

    crossings = 0
    for i in range(1, len(svm)):
        if (svm[i] - svm_mean) * (svm[i - 1] - svm_mean) < 0:
            crossings += 1
    svm_zcr = crossings / (len(svm) - 1)

    return [
        svm_mean, svm_std, svm_max, svm_min, freefall_frac,
        jerk_rms, gyro_mean, gyro_max, post_std, tilt_deg, svm_zcr,
    ]


def audio_burst_features(burst: Sequence[float]) -> dict[str, float]:
    """Per-burst statistics for one 128-sample ADC burst (raw counts)."""
    if len(burst) != AUDIO_BURST_SAMPLES:
        raise ValueError(f"audio burst must hold {AUDIO_BURST_SAMPLES} samples")
    centered = [v - AUDIO_ADC_CENTER for v in burst]
    rms = math.sqrt(_mean([v * v for v in centered]))
    p2p = max(burst) - min(burst)
    crossings = 0
    for i in range(1, len(centered)):
        if centered[i] * centered[i - 1] < 0:
            crossings += 1
    zcr = crossings / (len(centered) - 1)
    sub = sum(goertzel_power(centered, k) for k in range(BAND_SUB_BINS[0], BAND_SUB_BINS[1] + 1))
    low = sum(goertzel_power(centered, k) for k in range(BAND_LOW_BINS[0], BAND_LOW_BINS[1] + 1))
    mid = sum(goertzel_power(centered, k) for k in range(BAND_MID_BINS[0], BAND_MID_BINS[1] + 1))
    total = 2.0 * rms * rms + _EPS
    return {
        "rms": rms, "p2p": p2p, "zcr": zcr,
        "sub_share": sub / total, "low_share": low / total, "mid_share": mid / total,
    }


def audio_window_features(bursts: Sequence[Sequence[float]]) -> list[float]:
    """Aggregate ``AUDIO_BURSTS`` bursts into the 9 cry-classifier features."""
    if len(bursts) != AUDIO_BURSTS:
        raise ValueError(f"audio window must hold {AUDIO_BURSTS} bursts")
    stats = [audio_burst_features(b) for b in bursts]
    rms_values = [s["rms"] for s in stats]
    rms_mean = _mean(rms_values)
    rms_max = max(rms_values)
    p2p_max = max(s["p2p"] for s in stats) / AUDIO_ADC_FULL_SCALE
    zcr_mean = _mean([s["zcr"] for s in stats])
    sub_share = _mean([s["sub_share"] for s in stats])
    low_share = _mean([s["low_share"] for s in stats])
    mid_share = _mean([s["mid_share"] for s in stats])
    env_mod = _std(rms_values, rms_mean) / (rms_mean + _EPS)
    env_range = (rms_max - min(rms_values)) / (rms_max + _EPS)
    duty = sum(1 for v in rms_values if v > 0.5 * rms_max) / len(rms_values)
    return [rms_mean, p2p_max, zcr_mean, sub_share, low_share, mid_share, env_mod, env_range, duty]
