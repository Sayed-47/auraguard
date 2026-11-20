"""Tests for the AuraGuard AI pipeline (server/ai + generated firmware weights).

The classifiers train on small simulator datasets inside setUpModule so the
suite stays fast; accuracy is then asserted on a *different* simulator seed.
The physics is the same but the noise, phases, and parameter draws are fresh.
"""

from __future__ import annotations

import math
import random
import re
import unittest
from pathlib import Path

from server.ai import features as F
from server.ai import simulate as S
from server.ai.fusion import AlertState, FusionInput, fuse, priority
from server.ai.models import SoftmaxRegression, export_c_header, load_model
from server.ai.proximity import ProximityTracker, Zone
from server.ai.train import train_cry, train_motion

ROOT = Path(__file__).resolve().parents[1]
WEIGHTS_DIR = ROOT / "server" / "ai" / "weights"
HEADER = ROOT / "firmware" / "esp32_baby_unit_ai" / "ai_weights.h"

MOTION = None
CRY = None


def setUpModule():
    global MOTION, CRY
    MOTION, _ = train_motion(80, seed=11)
    CRY, _ = train_cry(80, seed=11)


class FeatureContractTests(unittest.TestCase):
    def test_motion_feature_count_and_length_guard(self):
        window = S.simulate_motion_window(0, random.Random(1))
        feats = F.motion_window_features(window)
        self.assertEqual(len(feats), len(F.MOTION_FEATURE_NAMES))
        with self.assertRaises(ValueError):
            F.motion_window_features(window[:-1])

    def test_audio_feature_count_and_length_guard(self):
        bursts = S.simulate_audio_window(1, random.Random(1))
        self.assertEqual(len(bursts), F.AUDIO_BURSTS)
        self.assertTrue(all(len(b) == F.AUDIO_BURST_SAMPLES for b in bursts))
        feats = F.audio_window_features(bursts)
        self.assertEqual(len(feats), len(F.AUDIO_FEATURE_NAMES))
        with self.assertRaises(ValueError):
            F.audio_window_features(bursts[:-1])

    def test_goertzel_finds_sine_in_expected_band(self):
        n = F.AUDIO_BURST_SAMPLES
        low_tone = [400.0 * math.sin(2 * math.pi * 350.0 * i / F.AUDIO_SAMPLE_RATE) for i in range(n)]
        stats = F.audio_burst_features([v + F.AUDIO_ADC_CENTER for v in low_tone])
        self.assertGreater(stats["low_share"], 0.8)
        hum_tone = [400.0 * math.sin(2 * math.pi * 120.0 * i / F.AUDIO_SAMPLE_RATE) for i in range(n)]
        stats = F.audio_burst_features([v + F.AUDIO_ADC_CENTER for v in hum_tone])
        self.assertGreater(stats["sub_share"], 0.8)

    def test_motion_features_capture_fall_signature(self):
        fall = F.motion_window_features(S.simulate_motion_window(2, random.Random(2)))
        idx = {name: i for i, name in enumerate(F.MOTION_FEATURE_NAMES)}
        self.assertGreater(fall[idx["freefall_frac"]], 0.0)
        self.assertLess(fall[idx["svm_min"]], F.FREEFALL_G)
        self.assertGreater(fall[idx["tilt_deg"]], 25.0)
        still = F.motion_window_features(S.simulate_motion_window(0, random.Random(3)))
        self.assertEqual(still[idx["freefall_frac"]], 0.0)
        self.assertLess(still[idx["post_std"]], 0.1)


class MotionClassifierTests(unittest.TestCase):
    def test_accuracy_on_fresh_seed(self):
        samples, labels = S.simulate_motion_dataset(60, seed=1234)
        self.assertGreaterEqual(MOTION.accuracy(samples, labels), 0.95)

    def test_running_is_not_reported_as_fall(self):
        # The headline requirement: doura douri (play/running) must not become FALL.
        samples, labels = S.simulate_motion_dataset(60, seed=4321)
        matrix = MOTION.confusion(samples, labels)
        active_as_fall = matrix[1][2] / max(1, sum(matrix[1]))
        self.assertLessEqual(active_as_fall, 0.02)

    def test_falls_are_not_missed(self):
        samples, labels = S.simulate_motion_dataset(60, seed=999)
        matrix = MOTION.confusion(samples, labels)
        fall_recall = matrix[2][2] / max(1, sum(matrix[2]))
        self.assertGreaterEqual(fall_recall, 0.95)


class CryClassifierTests(unittest.TestCase):
    def test_accuracy_on_fresh_seed(self):
        samples, labels = S.simulate_audio_dataset(60, seed=1234)
        self.assertGreaterEqual(CRY.accuracy(samples, labels), 0.90)

    def test_cry_recall_on_fresh_seed(self):
        samples, labels = S.simulate_audio_dataset(60, seed=777)
        matrix = CRY.confusion(samples, labels)
        recall = matrix[1][1] / max(1, sum(matrix[1]))
        self.assertGreaterEqual(recall, 0.85)


class ProximityTests(unittest.TestCase):
    def test_zone_progression_and_wander_timer(self):
        tracker = ProximityTracker()
        t = 0.0
        for _ in range(10):
            t += 0.5
            snap = tracker.update(-55.0, t)
        self.assertEqual(snap["zone"], "near")
        self.assertFalse(snap["wander"])
        for _ in range(40):  # 20 s solidly far
            t += 0.5
            snap = tracker.update(-80.0, t)
        self.assertEqual(snap["zone"], "far")
        self.assertTrue(snap["wander"])

    def test_hysteresis_prevents_flapping(self):
        tracker = ProximityTracker()
        t = 0.0
        for _ in range(10):
            t += 0.5
            tracker.update(-55.0, t)
        zones = set()
        for _ in range(20):  # wiggle inside the hysteresis band
            t += 0.5
            snap = tracker.update(-59.0, t)
            zones.add(snap["zone"])
        self.assertEqual(zones, {"near"})

    def test_lost_link_and_trend(self):
        tracker = ProximityTracker()
        for i, (t, rssi) in enumerate(S.simulate_rssi_walk(5, seconds=40)):
            tracker.update(rssi, t)
            if i == 20:
                break
        snap = tracker.update(None, 21.0)
        self.assertEqual(snap["zone"], "lost")

    def test_leaving_trend_detected(self):
        tracker = ProximityTracker()
        t = 0.0
        snap = {}
        for i in range(16):
            t += 0.5
            snap = tracker.update(-50.0 - i * 1.5, t)
        self.assertEqual(snap["trend"], "leaving")


class FusionTests(unittest.TestCase):
    def base_input(self, **overrides):
        values = dict(
            motion_class=0, motion_probs=(0.9, 0.05, 0.05),
            fall_candidate=False, stillness_ok=False, cry_prob=0.1,
            wander=False, sensor_fault=False, link_up=True,
        )
        values.update(overrides)
        return FusionInput(**values)

    def test_ai_confirmed_fall_alerts(self):
        result = fuse(self.base_input(fall_candidate=True, motion_class=2, motion_probs=(0.05, 0.1, 0.85)))
        self.assertTrue(result.send_fall)
        self.assertEqual(result.state, AlertState.FALL)

    def test_running_vetoes_fall_candidate(self):
        result = fuse(self.base_input(fall_candidate=True, motion_class=1, motion_probs=(0.1, 0.8, 0.1)))
        self.assertFalse(result.send_fall)
        self.assertTrue(result.fall_vetoed)

    def test_uncertain_window_falls_back_to_stillness_gate(self):
        result = fuse(self.base_input(fall_candidate=True, stillness_ok=True, motion_probs=(0.4, 0.3, 0.3)))
        self.assertTrue(result.send_fall)
        result = fuse(self.base_input(fall_candidate=True, stillness_ok=False, motion_probs=(0.4, 0.3, 0.3)))
        self.assertFalse(result.send_fall)

    def test_priority_order(self):
        result = fuse(self.base_input(fall_candidate=True, motion_class=2,
                                      motion_probs=(0.05, 0.1, 0.85), cry_prob=0.9, wander=True))
        self.assertEqual(result.state, AlertState.FALL)
        self.assertGreater(priority(AlertState.FALL), priority(AlertState.WANDER))
        self.assertGreater(priority(AlertState.WANDER), priority(AlertState.CRY))
        result = fuse(self.base_input(cry_prob=0.9, wander=True))
        self.assertEqual(result.state, AlertState.WANDER)
        result = fuse(self.base_input(cry_prob=0.9))
        self.assertEqual(result.state, AlertState.CRY)

    def test_sensor_fault_outranks_cry(self):
        result = fuse(self.base_input(cry_prob=0.9, sensor_fault=True))
        self.assertEqual(result.state, AlertState.SENSOR_FAULT)


class ModelArtifactTests(unittest.TestCase):
    def test_shipped_weights_load_and_match_feature_contract(self):
        motion = load_model(WEIGHTS_DIR / "motion.json")
        cry = load_model(WEIGHTS_DIR / "cry.json")
        self.assertEqual(motion.feature_names, F.MOTION_FEATURE_NAMES)
        self.assertEqual(cry.feature_names, F.AUDIO_FEATURE_NAMES)
        sample_motion, _ = S.simulate_motion_dataset(5, seed=5)
        sample_cry, _ = S.simulate_audio_dataset(5, seed=5)
        self.assertGreaterEqual(motion.accuracy(*S.simulate_motion_dataset(20, seed=55)), 0.9)
        self.assertGreaterEqual(cry.accuracy(*S.simulate_audio_dataset(20, seed=56)), 0.8)
        self.assertEqual(len(motion.predict_proba(sample_motion[0])), 3)
        self.assertEqual(len(cry.predict_proba(sample_cry[0])), 2)

    def test_model_json_roundtrip(self):
        model, _ = train_motion(20, seed=3)
        payload = model.to_dict()
        clone = SoftmaxRegression.from_dict(payload)
        sample = S.simulate_motion_dataset(5, seed=21)[0][0]
        self.assertEqual(model.predict(sample), clone.predict(sample))

    def test_generated_header_matches_python_contract(self):
        text = HEADER.read_text(encoding="utf-8")
        self.assertIn(f"#define AI_MOTION_N_FEATURES {len(F.MOTION_FEATURE_NAMES)}", text)
        self.assertIn(f"#define AI_CRY_N_FEATURES {len(F.AUDIO_FEATURE_NAMES)}", text)
        self.assertIn("#define AI_MOTION_N_CLASSES 3", text)
        self.assertIn("#define AI_CRY_N_CLASSES 2", text)
        for name in ("AI_MOTION_MEAN", "AI_MOTION_SCALE", "AI_MOTION_W", "AI_MOTION_B",
                     "AI_CRY_MEAN", "AI_CRY_SCALE", "AI_CRY_W", "AI_CRY_B"):
            self.assertIn(name, text)
        values = [float(v) for v in re.findall(r"(-?\d+\.?\d*(?:e[+-]?\d+)?)f", text)]
        self.assertTrue(all(math.isfinite(v) for v in values))
        motion = load_model(WEIGHTS_DIR / "motion.json")
        cry = load_model(WEIGHTS_DIR / "cry.json")
        self.assertEqual(text, export_c_header(motion, cry))


if __name__ == "__main__":
    unittest.main()
