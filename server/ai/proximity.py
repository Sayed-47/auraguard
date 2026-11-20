"""Bluetooth proximity estimation from connection RSSI.

The ESP32 baby unit is the BLE central, so it can poll ``BLEClient::getRssi()``
for the link back to the room module. A slow EMA tames fading dips, hysteresis
stops zone flapping, and a sustained-FAR timer drives the WANDER alert that
warns before the link (and the receiver's 6 s link-loss alarm) drops entirely.

Zones are tuned for a room-scale BLE link at default TX power; adjust
``NEAR_ENTER_DBM``/``FAR_ENTER_DBM`` for the actual module and room.
"""

from __future__ import annotations

import enum
import math

NEAR_ENTER_DBM = -58.0
FAR_ENTER_DBM = -70.0
HYSTERESIS_DB = 3.0
EMA_TAU_SECONDS = 2.5
WANDER_AFTER_SECONDS = 8.0
TREND_WINDOW_SECONDS = 6.0
LEAVING_SLOPE_DBM_S = -1.0


class Zone(enum.Enum):
    NEAR = "near"
    EDGE = "edge"
    FAR = "far"
    LOST = "lost"  # no RSSI available (link down)


class ProximityTracker:
    def __init__(self) -> None:
        self.ema: float | None = None
        self.zone = Zone.LOST
        self.far_seconds = 0.0
        self._history: list[tuple[float, float]] = []  # (t, ema) for the trend slope

    def update(self, rssi_dbm: float | None, t_seconds: float) -> dict:
        """Feed one RSSI poll. Returns the current proximity snapshot."""
        if rssi_dbm is None:
            self.zone = Zone.LOST
            self.far_seconds = 0.0
            self._history.clear()
            return self.snapshot()
        if self.ema is None:
            self.ema = rssi_dbm
            dt = EMA_TAU_SECONDS
        else:
            dt = max(1e-3, t_seconds - (self._history[-1][0] if self._history else t_seconds))
        alpha = 1.0 - math.exp(-dt / EMA_TAU_SECONDS)
        self.ema += alpha * (rssi_dbm - self.ema)
        self._history.append((t_seconds, self.ema))
        while self._history and t_seconds - self._history[0][0] > TREND_WINDOW_SECONDS:
            self._history.pop(0)

        previous = self.zone
        if self.zone is Zone.LOST:
            self.zone = self._zone_for(self.ema)
        elif self.zone is Zone.NEAR and self.ema < NEAR_ENTER_DBM - HYSTERESIS_DB:
            self.zone = self._zone_for(self.ema)
        elif self.zone is Zone.EDGE and not (FAR_ENTER_DBM - HYSTERESIS_DB < self.ema < NEAR_ENTER_DBM + HYSTERESIS_DB):
            self.zone = self._zone_for(self.ema)
        elif self.zone is Zone.FAR and self.ema > FAR_ENTER_DBM + HYSTERESIS_DB:
            self.zone = self._zone_for(self.ema)

        if self.zone is Zone.FAR:
            self.far_seconds = self.far_seconds + dt if previous is Zone.FAR else dt
        else:
            self.far_seconds = 0.0
        return self.snapshot()

    @staticmethod
    def _zone_for(ema: float) -> Zone:
        if ema >= NEAR_ENTER_DBM:
            return Zone.NEAR
        if ema >= FAR_ENTER_DBM:
            return Zone.EDGE
        return Zone.FAR

    def trend_dbm_per_s(self) -> float | None:
        """Least-squares slope of the EMA over the trend window, if enough data."""
        if len(self._history) < 4:
            return None
        t0 = self._history[0][0]
        points = [(t - t0, v) for t, v in self._history]
        span = points[-1][0]
        if span < 3.0:
            return None
        mean_t = sum(p[0] for p in points) / len(points)
        mean_v = sum(p[1] for p in points) / len(points)
        num = sum((t - mean_t) * (v - mean_v) for t, v in points)
        den = sum((t - mean_t) ** 2 for t, v in points)
        return num / den if den else 0.0

    def wandering(self) -> bool:
        return self.zone is Zone.FAR and self.far_seconds >= WANDER_AFTER_SECONDS

    def snapshot(self) -> dict:
        slope = self.trend_dbm_per_s()
        return {
            "rssi_ema": self.ema,
            "zone": self.zone.value,
            "far_seconds": round(self.far_seconds, 3),
            "wander": self.wandering(),
            "trend": None if slope is None else ("leaving" if slope < LEAVING_SLOPE_DBM_S else "approaching" if slope > -LEAVING_SLOPE_DBM_S else "steady"),
        }
