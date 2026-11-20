"""On-device AI pipeline for the AuraGuard baby unit.

Pure-standard-library reference implementation of the classifiers that run on
the ESP32 baby unit. The same feature math is compiled into
``firmware/esp32_baby_unit_ai`` from the generated ``ai_weights.h`` header, so a
model trained and verified here behaves identically on the hardware.

Pipeline: simulate or collect windows -> extract features -> train
:mod:`server.ai.models` -> export JSON weights and a C header -> flash the AI
sketch. See ``docs/AI.md``.
"""

from server.ai.features import (
    AUDIO_BURSTS,
    AUDIO_BURST_SAMPLES,
    AUDIO_FEATURE_NAMES,
    AUDIO_SAMPLE_RATE,
    BAND_LOW_BINS,
    BAND_MID_BINS,
    BAND_SUB_BINS,
    MOTION_FEATURE_NAMES,
    MOTION_SAMPLE_RATE,
    MOTION_WINDOW_SAMPLES,
    audio_burst_features,
    audio_window_features,
    motion_window_features,
)
from server.ai.models import SoftmaxRegression, load_model, save_model
from server.ai.proximity import ProximityTracker, Zone
from server.ai.fusion import FusionInput, FusionResult, fuse

__all__ = [
    "AUDIO_BURSTS",
    "AUDIO_BURST_SAMPLES",
    "AUDIO_FEATURE_NAMES",
    "AUDIO_SAMPLE_RATE",
    "BAND_LOW_BINS",
    "BAND_MID_BINS",
    "BAND_SUB_BINS",
    "FusionInput",
    "FusionResult",
    "MOTION_FEATURE_NAMES",
    "MOTION_SAMPLE_RATE",
    "MOTION_WINDOW_SAMPLES",
    "ProximityTracker",
    "SoftmaxRegression",
    "Zone",
    "audio_burst_features",
    "audio_window_features",
    "fuse",
    "load_model",
    "motion_window_features",
    "save_model",
]
