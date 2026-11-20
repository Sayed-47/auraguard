"""Sensor fusion: combine the classifiers and proximity into one alert state.

This is the reference implementation of the decision rules compiled into the
AI sketch. Priorities: FALL (critical) > SENSOR_FAULT > WANDER > CRY >
ACTIVITY > OK. The fall rule is safety-first: an AI-vetoed trigger (the window
looks like running/playing) is suppressed, an AI-confirmed trigger alerts
immediately, and an uncertain window falls back to the proven
impact-then-stillness gate so a classifier misfire can never silence a real
fall pattern.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass

FALL_PROB_ALERT = 0.55
ACTIVE_PROB_VETO = 0.60
CRY_PROB_ALERT = 0.65


class AlertState(enum.Enum):
    OK = "ok"
    ACTIVITY = "activity"      # baby is up and playing/running: informational
    CRY = "cry"
    WANDER = "wander"
    SENSOR_FAULT = "sensor_fault"
    FALL = "fall"


_PRIORITY = [AlertState.OK, AlertState.ACTIVITY, AlertState.CRY, AlertState.WANDER, AlertState.SENSOR_FAULT, AlertState.FALL]


@dataclass
class FusionInput:
    motion_class: int            # 0 normal, 1 active, 2 fall
    motion_probs: tuple[float, float, float]
    fall_candidate: bool         # the temporal detector saw impact/free-fall
    stillness_ok: bool           # post-impact stillness gate result
    cry_prob: float
    wander: bool                 # proximity tracker sustained-FAR flag
    sensor_fault: bool           # motion sensor unusable right now
    link_up: bool


@dataclass
class FusionResult:
    state: AlertState
    send_fall: bool              # firmware should transmit FALL now
    fall_vetoed: bool            # AI rejected the candidate as play/running
    confidence: float
    reason: str


def fuse(inp: FusionInput) -> FusionResult:
    probs = inp.motion_probs
    send_fall = False
    vetoed = False
    reason = "no fall candidate"

    if inp.fall_candidate:
        if probs[2] >= FALL_PROB_ALERT:
            send_fall = True
            reason = f"AI confirmed fall (p={probs[2]:.2f})"
        elif probs[1] >= ACTIVE_PROB_VETO:
            vetoed = True
            reason = f"AI veto: motion looks like play/running (p={probs[1]:.2f})"
        elif inp.stillness_ok:
            send_fall = True
            reason = "classifier uncertain; impact-then-stillness gate confirmed"
        else:
            reason = "classifier uncertain and stillness gate failed"

    if send_fall:
        return FusionResult(AlertState.FALL, True, vetoed, probs[2], reason)
    if inp.sensor_fault:
        return FusionResult(AlertState.SENSOR_FAULT, False, vetoed, 1.0, "motion sensor unusable")
    if inp.wander:
        return FusionResult(AlertState.WANDER, False, vetoed, 1.0, "baby sustained at Bluetooth range limit")
    if inp.cry_prob >= CRY_PROB_ALERT:
        return FusionResult(AlertState.CRY, False, vetoed, inp.cry_prob, f"cry classifier p={inp.cry_prob:.2f}")
    if inp.link_up and inp.motion_class == 1 and probs[1] >= ACTIVE_PROB_VETO:
        return FusionResult(AlertState.ACTIVITY, False, vetoed, probs[1], "baby active (play/running)")
    return FusionResult(AlertState.OK, False, vetoed, 1.0 - max(probs[1], probs[2]), reason)


def priority(state: AlertState) -> int:
    return _PRIORITY.index(state)
