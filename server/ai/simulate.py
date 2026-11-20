"""Synthetic labeled sensor data for training and testing the classifiers.

The generators encode the physics the firmware actually sees: gravity on a
random axis, free-fall magnitude collapse, impact spikes, rhythmic play
motion, cry harmonics around 300-500 Hz with slow amplitude modulation, and
common household impostors (knocks, TV hiss, appliance hum, steady tones).

Real nursery captures should replace or augment these windows when available;
the trainer accepts any data shaped like these generators' output. Seeded for
reproducible test runs.
"""

from __future__ import annotations

import math
import random
from typing import Sequence

from server.ai.features import (
    AUDIO_ADC_CENTER,
    AUDIO_BURST_SAMPLES,
    AUDIO_BURSTS,
    AUDIO_BURST_SPACING_MS,
    AUDIO_SAMPLE_RATE,
    MOTION_SAMPLE_RATE,
    MOTION_WINDOW_SAMPLES,
)

MOTION_CLASSES = ["normal", "active", "fall"]
CRY_CLASSES = ["other", "cry"]


def _unit_vector(rng: random.Random) -> tuple[float, float, float]:
    z = rng.uniform(-1.0, 1.0)
    phi = rng.uniform(0.0, 2.0 * math.pi)
    r = math.sqrt(max(0.0, 1.0 - z * z))
    return (r * math.cos(phi), r * math.sin(phi), z)


def _rotate_towards(u: Sequence[float], rng: random.Random, degrees: float) -> tuple[float, float, float]:
    """Return a unit vector at roughly ``degrees`` from ``u``."""
    v = _unit_vector(rng)
    dot = sum(a * b for a, b in zip(u, v))
    perp = [v[i] - dot * u[i] for i in range(3)]
    norm = math.sqrt(sum(p * p for p in perp)) or 1.0
    perp = [p / norm for p in perp]
    theta = math.radians(degrees)
    out = [u[i] * math.cos(theta) + perp[i] * math.sin(theta) for i in range(3)]
    length = math.sqrt(sum(c * c for c in out)) or 1.0
    return (out[0] / length, out[1] / length, out[2] / length)


def simulate_motion_window(label: int, rng: random.Random) -> list[tuple[float, float, float, float, float, float]]:
    """One 2 s, 50 Hz window of (ax, ay, az, gx, gy, gz); accel in g, gyro in deg/s."""
    n = MOTION_WINDOW_SAMPLES
    fs = MOTION_SAMPLE_RATE
    gravity = _unit_vector(rng)
    window: list[tuple[float, float, float, float, float, float]] = []

    if label == 0:  # normal: lying/sitting, small noise, optional brief wiggle
        noise_a = rng.uniform(0.01, 0.05)
        noise_g = rng.uniform(0.5, 3.0)
        wiggle_at = rng.randrange(n) if rng.random() < 0.35 else -1
        wiggle_len = rng.randrange(5, 15)
        wiggle_amp = rng.uniform(0.1, 0.35)
        for i in range(n):
            amp = wiggle_amp if 0 <= i - wiggle_at < wiggle_len else 0.0
            bump = _unit_vector(rng)
            ax = gravity[0] + rng.gauss(0, noise_a) + amp * bump[0]
            ay = gravity[1] + rng.gauss(0, noise_a) + amp * bump[1]
            az = gravity[2] + rng.gauss(0, noise_a) + amp * bump[2]
            window.append((ax, ay, az, rng.gauss(0, noise_g), rng.gauss(0, noise_g), rng.gauss(0, noise_g)))

    elif label == 1:  # active: crawling, playing, running around
        freq = rng.uniform(1.5, 3.5)
        amp = rng.uniform(0.25, 0.8)
        phase = rng.uniform(0.0, 2.0 * math.pi)
        direction = _unit_vector(rng)
        gyro_amp = rng.uniform(40.0, 220.0)
        gyro_phase = [rng.uniform(0.0, 2.0 * math.pi) for _ in range(3)]
        noise_a = rng.uniform(0.04, 0.09)
        spike_at = rng.randrange(n) if rng.random() < 0.10 else -1
        for i in range(n):
            t = i / fs
            swing = amp * math.sin(2.0 * math.pi * freq * t + phase)
            spike = rng.uniform(1.4, 2.2) if i == spike_at else 0.0
            bump = _unit_vector(rng)
            ax = gravity[0] + direction[0] * swing + rng.gauss(0, noise_a) + spike * bump[0]
            ay = gravity[1] + direction[1] * swing + rng.gauss(0, noise_a) + spike * bump[1]
            az = gravity[2] + direction[2] * swing + rng.gauss(0, noise_a) + spike * bump[2]
            gx = gyro_amp * math.sin(2.0 * math.pi * freq * t + gyro_phase[0]) + rng.gauss(0, 6.0)
            gy = gyro_amp * math.sin(2.0 * math.pi * freq * t + gyro_phase[1]) + rng.gauss(0, 6.0)
            gz = gyro_amp * math.sin(2.0 * math.pi * freq * t + gyro_phase[2]) + rng.gauss(0, 6.0)
            window.append((ax, ay, az, gx, gy, gz))

    elif label == 2:  # fall: free-fall collapse, impact spike, then stillness in a new orientation
        start = rng.randrange(25, 50)         # free-fall begins here; the ring always holds >=0.5 s of pre-fall data
        free_len = rng.randrange(8, 23)       # 160-460 ms of weightlessness
        impact_len = rng.randrange(1, 4)
        impact_g = rng.uniform(2.5, 6.0)
        new_gravity = _rotate_towards(gravity, rng, rng.uniform(40.0, 95.0))
        gyro_spin = rng.uniform(150.0, 480.0)
        spin_axis = _unit_vector(rng)
        for i in range(n):
            if i < start:                      # pre-fall: small movement
                noise = rng.uniform(0.02, 0.06)
                ax = gravity[0] + rng.gauss(0, noise)
                ay = gravity[1] + rng.gauss(0, noise)
                az = gravity[2] + rng.gauss(0, noise)
                gyro = (rng.gauss(0, 4.0), rng.gauss(0, 4.0), rng.gauss(0, 4.0))
            elif i < start + free_len:         # free-fall: near-zero magnitude
                ax = rng.gauss(0, 0.12)
                ay = rng.gauss(0, 0.12)
                az = rng.gauss(0, 0.12)
                gyro = (rng.gauss(0, 40.0), rng.gauss(0, 40.0), rng.gauss(0, 40.0))
            elif i < start + free_len + impact_len:  # impact spike
                bump = _unit_vector(rng)
                ax = new_gravity[0] + bump[0] * impact_g + rng.gauss(0, 0.15)
                ay = new_gravity[1] + bump[1] * impact_g + rng.gauss(0, 0.15)
                az = new_gravity[2] + bump[2] * impact_g + rng.gauss(0, 0.15)
                gyro = (spin_axis[0] * gyro_spin, spin_axis[1] * gyro_spin, spin_axis[2] * gyro_spin)
            else:                              # post-impact stillness, new orientation
                still = rng.uniform(0.005, 0.03)
                ax = new_gravity[0] + rng.gauss(0, still)
                ay = new_gravity[1] + rng.gauss(0, still)
                az = new_gravity[2] + rng.gauss(0, still)
                gyro = (rng.gauss(0, 1.5), rng.gauss(0, 1.5), rng.gauss(0, 1.5))
            window.append((ax, ay, az, gyro[0], gyro[1], gyro[2]))
    else:
        raise ValueError("unknown motion label")
    return window


def _adc_clip(value: float) -> float:
    return min(4095.0, max(0.0, AUDIO_ADC_CENTER + value))


AUDIO_WINDOW_SECONDS = AUDIO_BURSTS * AUDIO_BURST_SPACING_MS / 1000.0


def _fill_bursts(sample: list[float], offset: float, rng: random.Random) -> list[list[float]]:
    """Split the synthesis into the 8 firmware bursts (128 samples, 200 ms apart)."""
    bursts = []
    hop = AUDIO_SAMPLE_RATE * AUDIO_BURST_SPACING_MS // 1000
    for b in range(AUDIO_BURSTS):
        start = b * hop
        bursts.append([_adc_clip(v + offset) for v in sample[start:start + AUDIO_BURST_SAMPLES]])
    return bursts


def simulate_audio_window(label: int, rng: random.Random) -> list[list[float]]:
    """One 1.6 s audio observation as 8 bursts of 128 raw ADC counts."""
    n = int(AUDIO_SAMPLE_RATE * AUDIO_WINDOW_SECONDS)
    noise_floor = rng.uniform(8.0, 30.0)
    offset = rng.uniform(-40.0, 40.0)
    sample = [0.0] * n

    if label == 1:  # baby cry: harmonic stack, slow rhythmic AM, slight vibrato
        f0 = rng.uniform(300.0, 520.0)
        am_rate = rng.uniform(1.0, 2.2)
        vib_rate = rng.uniform(5.0, 7.0)
        vib_depth = rng.uniform(8.0, 18.0)
        amp = rng.uniform(350.0, 1200.0)
        harmonics = [(1, 1.0), (2, rng.uniform(0.3, 0.5)), (3, rng.uniform(0.1, 0.25))]
        am_phase = rng.uniform(0.0, 2.0 * math.pi)
        for i in range(n):
            t = i / AUDIO_SAMPLE_RATE
            envelope = 0.3 + 0.7 * max(0.0, math.sin(2.0 * math.pi * am_rate * t + am_phase)) ** 2
            freq = f0 + vib_depth * math.sin(2.0 * math.pi * vib_rate * t)
            value = 0.0
            for h, gain in harmonics:
                value += gain * math.sin(2.0 * math.pi * freq * h * t)
            sample[i] = amp * envelope * value + rng.gauss(0.0, noise_floor)

    else:  # household impostors
        kind = rng.randrange(4)
        if kind == 0:    # broadband hiss (TV, running water)
            amp = rng.uniform(250.0, 800.0)
            alpha = rng.uniform(0.05, 0.4)
            last = 0.0
            for i in range(n):
                white = rng.gauss(0.0, 1.0)
                last = last + alpha * (white - last)
                sample[i] = amp * last + rng.gauss(0.0, noise_floor)
        elif kind == 1:  # knocks/claps: sparse fast decays
            decay = rng.uniform(0.006, 0.02)
            amp = rng.uniform(500.0, 1500.0)
            hits = sorted(rng.sample(range(n), rng.randrange(1, 3)))
            for i in range(n):
                env = sum(math.exp(-(i - h) / (decay * AUDIO_SAMPLE_RATE)) for h in hits if i >= h)
                sample[i] = amp * env * rng.gauss(0.0, 1.0) + rng.gauss(0.0, noise_floor)
        elif kind == 2:  # steady appliance tone, no cry-like modulation
            freq = rng.uniform(120.0, 800.0)
            amp = rng.uniform(250.0, 900.0)
            for i in range(n):
                t = i / AUDIO_SAMPLE_RATE
                sample[i] = amp * math.sin(2.0 * math.pi * freq * t) + rng.gauss(0.0, noise_floor)
        else:            # fan hum: low fundamental plus broadband
            freq = rng.uniform(80.0, 160.0)
            amp = rng.uniform(200.0, 600.0)
            for i in range(n):
                t = i / AUDIO_SAMPLE_RATE
                sample[i] = amp * math.sin(2.0 * math.pi * freq * t) + rng.gauss(0.0, amp * 0.35)

    return _fill_bursts(sample, offset, rng)


def simulate_motion_dataset(n_per_class: int, seed: int) -> tuple[list, list[int]]:
    rng = random.Random(seed)
    samples, labels = [], []
    from server.ai.features import motion_window_features
    for label in range(len(MOTION_CLASSES)):
        for _ in range(n_per_class):
            samples.append(motion_window_features(simulate_motion_window(label, rng)))
            labels.append(label)
    return samples, labels


def simulate_audio_dataset(n_per_class: int, seed: int) -> tuple[list, list[int]]:
    rng = random.Random(seed)
    samples, labels = [], []
    from server.ai.features import audio_window_features
    for label in range(len(CRY_CLASSES)):
        for _ in range(n_per_class):
            samples.append(audio_window_features(simulate_audio_window(label, rng)))
            labels.append(label)
    return samples, labels


def simulate_rssi_walk(seed: int, seconds: int = 60) -> list[tuple[float, float]]:
    """(t_seconds, rssi_dbm) walk: near -> far -> back, with fading noise."""
    rng = random.Random(seed)
    path = []
    for step in range(seconds * 2):
        t = step / 2.0
        base = -52.0 - 22.0 * math.sin(2.0 * math.pi * t / seconds)
        path.append((t, base + rng.gauss(0.0, 2.5)))
    return path
