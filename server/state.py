"""Validated telemetry, persistence, and command confirmation for AuraGuard.

This module is intentionally independent of FastAPI and the serial driver so that
link-loss and alarm behavior can be tested without any connected hardware.
"""

from __future__ import annotations

from collections import OrderedDict
from datetime import datetime, timedelta, timezone
import json
import math
import re
from pathlib import Path
import sqlite3
import time
from typing import Any
from uuid import uuid4


STALE_SECONDS = 3.0
OFFLINE_SECONDS = 5.0
COMMAND_TIMEOUT_SECONDS = 5.0
MAX_LINE_BYTES = 4096
MAX_HISTORY_ROWS = 86400
MAX_EVENT_ROWS = 2000
STATES = {"normal", "cry", "fall", "offline"}
FALL_STAGES = {"monitoring", "impact", "orientation", "stillness", "confirmed"}
ACTIONS = {"arm", "disarm", "acknowledge"}
PROTOCOLS = {"uno-room-v1", "baby-ble-v5", "json-v1"}
RECEIVER_STALE_SECONDS = 5.0
RECEIVER_BABY_TIMEOUT_SECONDS = 6.0
ROOM_STATUS = re.compile(r"status \| armed=([01]) baby=(waiting|LOST|linked) lastMsg=([0-9]{1,7})s ago mic=(remote|[0-9]{1,4}) cry=([01])")
ROOM_READY = "Room unit ready. Cry detection comes from the baby unit (CRY messages)."
ROOM_LINES = {
    ROOM_READY, "Baby unit LINKED (first message received)", "Link restored",
    "!!! FALL ALERT from baby unit !!!", "CRY reported by baby unit", "cry ended",
    "!!! LINK LOST - no signal from baby unit !!!", "ACKNOWLEDGED (sent ACK to baby unit)",
    "ARMED", "DISARMED",
}
CRY_BURST_GAP_SECONDS = 3.0


class UnsupportedControlError(RuntimeError):
    """The selected device protocol has no verified hardware-control contract."""


class Clock:
    def monotonic(self) -> float:
        return time.monotonic()

    def now(self) -> datetime:
        return datetime.now(timezone.utc)


def iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def bounded_number(value: Any, key: str, lower: float, upper: float) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{key} must be numeric or null")
    if not math.isfinite(value) or not lower <= value <= upper:
        raise ValueError(f"{key} is outside its supported range")
    return float(value)


def validate_packet(packet: Any) -> dict[str, Any]:
    if not isinstance(packet, dict):
        raise ValueError("packet must be a JSON object")
    packet_type = packet.get("type", "telemetry")
    if packet_type not in {"telemetry", "command_ack"}:
        raise ValueError("unknown packet type")
    result: dict[str, Any] = {"type": packet_type}
    for key in ("ax", "ay", "az"):
        if key in packet:
            result[key] = bounded_number(packet[key], key, -64, 64)
    for key in ("gx", "gy", "gz"):
        if key in packet:
            result[key] = bounded_number(packet[key], key, -4000, 4000)
    for key in ("sound_level", "battery_pct"):
        if key in packet:
            result[key] = bounded_number(packet[key], key, 0, 100)
    for key in ("seq", "uptime_ms", "wearable_age_ms"):
        if key in packet:
            raw = packet[key]
            if raw is not None and (isinstance(raw, bool) or not isinstance(raw, int)):
                raise ValueError(f"{key} must be an integer or null")
            value = bounded_number(raw, key, 0, 2**53 - 1)
            result[key] = None if value is None else int(value)
    if "muted_ms" in packet:
        value = bounded_number(packet["muted_ms"], "muted_ms", 0, 15000)
        result["muted_ms"] = None if value is None else int(value)
    for key in ("armed", "bt_connected"):
        if key in packet:
            if packet[key] is not None and not isinstance(packet[key], bool):
                raise ValueError(f"{key} must be a boolean or null")
            result[key] = packet[key]
    if "state" in packet:
        raw_state = packet["state"]
        if not isinstance(raw_state, str):
            raise ValueError("state must be a string")
        value = {"ok": "normal", "crying": "cry", "lost": "offline"}.get(raw_state.lower(), raw_state.lower())
        if value not in STATES:
            raise ValueError("invalid state")
        result["state"] = value
    if "fall_stage" in packet:
        value = packet["fall_stage"]
        if not isinstance(value, str) or value not in FALL_STAGES:
            raise ValueError("invalid fall_stage")
        result["fall_stage"] = value
    if packet_type == "telemetry":
        if not any(key in result for key in ("state", "ax", "sound_level", "bt_connected")):
            raise ValueError("telemetry has no supported readings")
    else:
        identifier = packet.get("id", packet.get("request_id"))
        if not isinstance(identifier, str) or not 1 <= len(identifier) <= 64:
            raise ValueError("command acknowledgment needs a bounded id")
        if not all(ch.isascii() and (ch.isalnum() or ch in "-_") for ch in identifier):
            raise ValueError("invalid command id")
        if not isinstance(packet.get("ok"), bool):
            raise ValueError("command acknowledgment needs boolean ok")
        result.update(id=identifier, ok=packet["ok"])
    return result


class Store:
    """One connection, accessed only on the server's event-loop thread."""

    def __init__(self, path: str | Path):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path))
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                acceleration REAL,
                sound_level REAL
            );
            CREATE TABLE IF NOT EXISTS events (
                id TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                severity TEXT NOT NULL,
                title TEXT NOT NULL,
                detail TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                acknowledged INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS history_time ON history(timestamp);
            CREATE INDEX IF NOT EXISTS event_time ON events(timestamp);
            """
        )
        self.db.commit()
        self._writes = 0

    def add_history(self, timestamp: str, acceleration: float | None, sound: float | None) -> None:
        self.db.execute(
            "INSERT INTO history(timestamp, acceleration, sound_level) VALUES (?, ?, ?)",
            (timestamp, acceleration, sound),
        )
        self._writes += 1
        if self._writes % 300 == 0:
            self.db.execute(
                "DELETE FROM history WHERE id < COALESCE((SELECT id FROM history ORDER BY id DESC LIMIT 1 OFFSET ?), 0)",
                (MAX_HISTORY_ROWS - 1,),
            )
        self.db.commit()

    def history(self, limit: int = 120) -> list[dict[str, Any]]:
        rows = self.db.execute(
            "SELECT timestamp, acceleration, sound_level FROM history ORDER BY id DESC LIMIT ?",
            (max(1, min(limit, MAX_HISTORY_ROWS)),),
        ).fetchall()
        return [dict(row) for row in reversed(rows)]

    def add_event(self, event: dict[str, Any]) -> None:
        self.db.execute(
            "INSERT INTO events(id,type,severity,title,detail,timestamp,acknowledged) VALUES (?,?,?,?,?,?,?)",
            tuple(event[key] for key in ("id", "type", "severity", "title", "detail", "timestamp", "acknowledged")),
        )
        self.db.execute(
            "DELETE FROM events WHERE rowid NOT IN (SELECT rowid FROM events ORDER BY rowid DESC LIMIT ?)",
            (MAX_EVENT_ROWS,),
        )
        self.db.commit()

    def events(self, limit: int = 100) -> list[dict[str, Any]]:
        rows = self.db.execute("SELECT * FROM events ORDER BY rowid DESC LIMIT ?", (max(1, min(limit, MAX_EVENT_ROWS)),)).fetchall()
        result = [dict(row) for row in rows]
        for event in result:
            event["acknowledged"] = bool(event["acknowledged"])
        return result

    def acknowledge(self) -> None:
        self.db.execute("UPDATE events SET acknowledged=1 WHERE acknowledged=0")
        self.db.commit()

    def close(self) -> None:
        self.db.close()


class Monitor:
    def __init__(self, store: Store, mode: str = "live", port: str | None = None, clock: Clock | None = None, protocol: str = "json-v1"):
        if mode != "live":
            raise ValueError("only live device monitoring is supported")
        if protocol not in PROTOCOLS:
            raise ValueError("unsupported device protocol")
        self.protocol = protocol
        self.store = store
        self.mode = mode
        self.port = port
        self.clock = clock or Clock()
        self.serial_connected = False
        self.last_base_mono: float | None = None
        self.last_base_at: datetime | None = None
        self.last_wearable_at: datetime | None = None
        self.last_packet: dict[str, Any] = {}
        self.reported_bt: bool | None = None
        self.reported_wearable_age_ms: int | None = None
        self.armed: bool | None = None
        self.muted_until: datetime | None = None
        self._last_history_mono = float("-inf")
        self._last_link_status = "waiting"
        self._last_alarm_state: str | None = None
        self.pending: dict[str, dict[str, Any]] = {}
        self.control_results: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self.invalid_packets = 0
        self.last_error: str | None = None
        self.message_counts = {"OK": 0, "FALL": 0, "CRY": 0}
        self.last_token: str | None = None
        self.last_heartbeat_at: datetime | None = None
        self.last_fall_at: datetime | None = None
        self.last_cry_at: datetime | None = None
        self._last_cry_mono: float | None = None
        self.session_started_at = self.clock.now()
        self.receiver_last_status_at: datetime | None = None
        self.receiver_last_status_mono: float | None = None
        self.receiver_last_line: str | None = None
        self.receiver_fall_active: bool | None = None
        self.receiver_cry_active: bool | None = None
        self.receiver_link_lost: bool | None = None
        self.receiver_mute_known = False
        self.receiver_counts = {"fall_reports": 0, "cry_episodes": 0, "acknowledgments": 0}
        self._receiver_invalidated = False
        self._receiver_baby_report: str | None = None
        self._receiver_baby_anchor_mono: float | None = None
        self._receiver_baby_age_ms: int | None = None
        self._receiver_timer_reset_mono: float | None = None

    @property
    def event_only(self) -> bool:
        return self.protocol != "json-v1"

    @property
    def receiver_mode(self) -> bool:
        return self.protocol == "uno-room-v1"

    @property
    def hardware_controls(self) -> bool:
        return not self.event_only

    def event(self, kind: str, severity: str, title: str, detail: str) -> None:
        self.store.add_event({
            "id": "evt-" + uuid4().hex,
            "type": kind,
            "severity": severity,
            "title": title,
            "detail": detail,
            "timestamp": iso(self.clock.now()),
            "acknowledged": False,
        })

    def set_serial(self, connected: bool, error: str | None = None) -> None:
        changed = connected != self.serial_connected
        self.serial_connected = connected
        if error is not None:
            self.last_error = error[:240]
        if changed:
            self.event(
                "connection", "info" if connected else "warning",
                "Base station connected" if connected else "Base station disconnected",
                ("Serial transport is open; waiting for forwarded wearable messages." if self.event_only else "Serial transport is open; waiting for wearable telemetry.") if connected else "The server is reconnecting to the configured serial port.",
            )
        if not connected and self.receiver_mode:
            self._invalidate_receiver()
        if not connected:
            for command_id in list(self.pending):
                self.finish_command(command_id, "failed", "Serial connection closed before hardware confirmation.")
        self.tick()

    def ingest_line(self, line: bytes | str) -> bool:
        try:
            if len(line) > MAX_LINE_BYTES:
                raise ValueError("serial packet exceeds 4096 bytes")
            if isinstance(line, bytes):
                line = line.decode("utf-8", errors="strict")
            if self.receiver_mode:
                if line.endswith("\r\n"):
                    line = line[:-2]
                elif line.endswith("\n"):
                    line = line[:-1]
                return self._ingest_room_line(line)
            if self.event_only:
                # Accept exactly one framed token. Never treat debug text, ACK,
                # whitespace, or a legacy JSON packet as wearable liveness.
                if line.endswith("\r\n"):
                    line = line[:-2]
                elif line.endswith("\n"):
                    line = line[:-1]
                if line not in self.message_counts:
                    raise ValueError("baby-ble-v5 accepts only OK, FALL, or CRY")
                return self._ingest_event_token(line)
            packet = json.loads(line)
            return self.ingest(packet)
        except (ValueError, TypeError, UnicodeError, OverflowError) as exc:
            self.invalid_packets += 1
            self.last_error = f"Ignored invalid serial packet: {exc}"[:240]
            return False

    def receiver_fresh(self) -> bool:
        return self.serial_connected and self.last_base_mono is not None and self.clock.monotonic() - self.last_base_mono < RECEIVER_STALE_SECONDS

    def receiver_status(self) -> str:
        if self.last_base_mono is None:
            return "waiting"
        if not self.serial_connected:
            return "offline"
        return "connected" if self.receiver_fresh() else "stale"

    def _invalidate_receiver(self) -> None:
        self.armed = None
        self.receiver_fall_active = None
        self.receiver_cry_active = None
        self.receiver_link_lost = None
        self.muted_until = None
        self.receiver_mute_known = False
        self.receiver_last_status_mono = None
        self._receiver_baby_report = None
        self._receiver_baby_anchor_mono = None
        self._receiver_baby_age_ms = None
        self._receiver_timer_reset_mono = None
        self.last_wearable_at = None
        self._receiver_invalidated = True

    def _room_baby_message(self, now_mono: float, now: datetime) -> None:
        # FALL and the receiver's CRY-start log establish an actual accepted
        # baby token. ACK / ARM / arbitrary receiver activity never do this.
        self._receiver_baby_report = "linked"
        self._receiver_baby_anchor_mono = now_mono
        self._receiver_baby_age_ms = 0
        self._receiver_timer_reset_mono = None
        self.last_wearable_at = now
        self.receiver_link_lost = False

    def _room_infer_armed(self) -> None:
        # These logs are emitted only inside armed-only firmware branches.
        # If the last observed state was disarmed, an ARM transition was missed;
        # its reset may have cleared a fall and other intervening events may be
        # missing, so omitted state must become unknown rather than stay latched.
        if self.armed is False:
            self.receiver_fall_active = None
            self.muted_until = None
            self.receiver_mute_known = False
            self._receiver_timer_reset_mono = self.clock.monotonic()
            self._receiver_baby_anchor_mono = None
            self._receiver_baby_age_ms = None
            self.last_wearable_at = None
        self.armed = True

    def _ingest_room_line(self, line: str) -> bool:
        status_match = ROOM_STATUS.fullmatch(line)
        mic_ready = re.fullmatch(r"Room unit ready\. Mic baseline = ([0-9]{1,4})", line)
        unknown = re.fullmatch(r"unknown msg: ([ -~]{1,23})", line)
        if status_match:
            armed, baby, age_text, mic, cry = status_match.groups()
            age = int(age_text)
            if age > 4294967 or (mic != "remote" and int(mic) > 1023):
                raise ValueError("receiver status contains out-of-range fields")
        elif mic_ready:
            if int(mic_ready.group(1)) > 1023:
                raise ValueError("receiver microphone baseline is out of range")
        elif not unknown and line not in ROOM_LINES:
            raise ValueError("unrecognized uno-room-v1 serial line")

        self.tick()
        now_mono = self.clock.monotonic()
        now = self.clock.now()
        if unknown:
            # The Uno itself resets lastBabyMsg before rejecting this payload.
            # Do not let that timer reset, nor this log, establish fresh baby or
            # receiver state. The next genuine token / credible status can.
            self._receiver_timer_reset_mono = now_mono
            self._receiver_baby_anchor_mono = None
            self._receiver_baby_age_ms = None
            self.last_wearable_at = None
            self.receiver_last_line = line
            self.event("system", "warning", "Unknown baby message", "The receiver ignored an unrecognized Bluetooth message.")
            self.last_error = "Receiver reported an unrecognized Bluetooth message."
            return True

        self.last_base_mono = now_mono
        self.last_base_at = now
        self.receiver_last_line = line
        self._receiver_invalidated = False
        self.last_error = None

        if line == ROOM_READY or mic_ready:
            self._invalidate_receiver()
            self._receiver_invalidated = False
            self.armed = True
            self.receiver_fall_active = self.receiver_cry_active = self.receiver_link_lost = False
            self.receiver_mute_known = True
            self.receiver_last_status_at = None
            self.receiver_last_status_mono = None
            self._receiver_baby_report = "waiting"
            self._receiver_timer_reset_mono = now_mono
            self.event("system", "info", "Room unit started", "Physical alarms are armed; waiting for baby-unit messages.")
        elif status_match:
            reported_armed = armed == "1"
            # A changed arm bit means an unobserved button transition may have
            # reset flags. Status omits fall/mute, so their current values are
            # unknown when that transition was missed.
            if self.armed is not None and self.armed != reported_armed:
                self.receiver_fall_active = None
                self.muted_until = None
                self.receiver_mute_known = False
                self._receiver_timer_reset_mono = now_mono
                self._receiver_baby_anchor_mono = None
                self._receiver_baby_age_ms = None
                self.last_wearable_at = None
            if baby == "waiting" and self._receiver_baby_report not in {None, "waiting"}:
                self.receiver_fall_active = None
                self.muted_until = None
                self.receiver_mute_known = False
            self.armed = reported_armed
            self.receiver_cry_active = cry == "1"
            self.receiver_link_lost = baby == "LOST"
            self.receiver_last_status_at = now
            self.receiver_last_status_mono = now_mono
            self._receiver_baby_report = baby
            # lastMsg is floored seconds. After ARM or unknown-message timer
            # reset, require its *earliest* possible timestamp to be newer than
            # that reset before accepting it as new baby activity.
            credible_age = self._receiver_timer_reset_mono is None or now_mono - (age + 1) > self._receiver_timer_reset_mono
            if baby != "waiting" and credible_age:
                self._receiver_baby_anchor_mono = now_mono
                self._receiver_baby_age_ms = age * 1000
                self.last_wearable_at = now - timedelta(seconds=age)
                self._receiver_timer_reset_mono = None
            elif baby == "waiting":
                self._receiver_baby_anchor_mono = None
                self._receiver_baby_age_ms = None
                self.last_wearable_at = None
        elif line == "!!! FALL ALERT from baby unit !!!":
            self._room_baby_message(now_mono, now)
            self.receiver_fall_active = True
            self.receiver_counts["fall_reports"] += 1
            self.last_fall_at = now
            self.event("fall", "critical", "Fall alert", "The room unit received FALL from the baby unit.")
        elif line == "CRY reported by baby unit":
            self._room_infer_armed()
            self._room_baby_message(now_mono, now)
            self.receiver_cry_active = True
            self.receiver_counts["cry_episodes"] += 1
            self.last_cry_at = now
            self.event("cry", "warning", "Sound alert", "The room unit activated its baby-unit sound alert.")
        elif line == "cry ended":
            self._room_infer_armed()
            self.receiver_cry_active = False
            self.event("cry", "info", "Sound alert ended", "The room unit cleared its sound alert after its CRY-message timeout.")
        elif line == "!!! LINK LOST - no signal from baby unit !!!":
            self._room_infer_armed()
            self.receiver_link_lost = True
            self._receiver_baby_report = "LOST"
            self.event("connection", "warning", "Room unit reports link lost", "No baby message reached the armed receiver for more than 6 seconds.")
        elif line == "ACKNOWLEDGED (sent ACK to baby unit)":
            self.receiver_fall_active = False
            self.receiver_mute_known = True
            self.muted_until = now + timedelta(seconds=15)
            self.receiver_counts["acknowledgments"] += 1
            self.event("system", "info", "Alarm acknowledged", "Physical ACK cleared the fall flag and muted the room buzzer for 15 seconds.")
        elif line in {"ARMED", "DISARMED"}:
            self.armed = line == "ARMED"
            self.receiver_fall_active = self.receiver_cry_active = self.receiver_link_lost = False
            # checkButtons resets lastBabyMsg without receiving a radio packet.
            self._receiver_timer_reset_mono = now_mono
            self._receiver_baby_anchor_mono = None
            self._receiver_baby_age_ms = None
            self.last_wearable_at = None
            if self._receiver_baby_report == "LOST":
                self._receiver_baby_report = "linked"
            self.event("system", "info", "Monitoring armed" if self.armed else "Monitoring disarmed", "The physical ARM button changed the room unit's alarm state.")
        else:  # First-linked / restored notices can also precede unknown input.
            self._receiver_baby_report = "linked"
            self.receiver_link_lost = False
            self.event("connection", "info", "Room link notice", "The room unit reported a Bluetooth connection change; awaiting current status.")
        self.tick()
        return True

    def _ingest_event_token(self, token: str) -> bool:
        self.tick()
        now_mono = self.clock.monotonic()
        now = self.clock.now()
        self.last_base_mono = now_mono
        self.last_base_at = self.last_wearable_at = now
        self.reported_bt = True
        self.reported_wearable_age_ms = 0
        self.last_token = token
        self.message_counts[token] += 1
        if token == "OK":
            self.last_heartbeat_at = now
        elif token == "FALL":
            self.last_fall_at = now
            self.event(
                "fall", "critical", "Possible fall reported",
                "FALL received from the baby unit. The token does not distinguish detection, sensor-loss fallback, or the BOOT-button demonstration. Check on the baby.",
            )
        else:
            self.last_cry_at = now
            if self._last_cry_mono is None or now_mono - self._last_cry_mono >= CRY_BURST_GAP_SECONDS:
                self.event(
                    "cry", "warning", "Sound alert reported",
                    "CRY reception burst started. Reports less than 3 seconds apart are grouped; this is not a confirmed separate incident. No numeric sound level or explicit clear message is supplied.",
                )
            self._last_cry_mono = now_mono
        # OK is only a heartbeat: it never clears or acknowledges FALL / CRY.
        # Sensor health and alarm state cannot be inferred from this protocol.
        self.last_error = None
        self.tick()
        return True

    def ingest(self, packet: dict[str, Any]) -> bool:
        if self.event_only:
            raise ValueError("baby-ble-v5 requires exact newline-delimited event tokens")
        packet = validate_packet(packet)
        self.tick()  # Expire commands before accepting an acknowledgment or new telemetry.
        if packet["type"] == "command_ack":
            self.receive_ack(packet)
            return True
        now_mono = self.clock.monotonic()
        now = self.clock.now()
        self.last_base_mono = now_mono
        self.last_base_at = now
        self.last_packet.update(packet)
        if "bt_connected" in packet:
            self.reported_bt = packet["bt_connected"]
        if "wearable_age_ms" in packet:
            self.reported_wearable_age_ms = packet["wearable_age_ms"]
        elif packet.get("bt_connected") is True:
            # Direct wearable serial integrations may not have a separate base clock.
            self.reported_wearable_age_ms = 0
        if self.reported_bt and self.reported_wearable_age_ms is not None:
            self.last_wearable_at = now - timedelta(milliseconds=self.reported_wearable_age_ms)
        if "armed" in packet:
            self.armed = packet["armed"]
        if "muted_ms" in packet and packet["muted_ms"] is not None:
            self.muted_until = now + timedelta(milliseconds=packet["muted_ms"]) if packet["muted_ms"] else None
        self._confirm_from_telemetry(packet)
        state = packet.get("state")
        if state is not None and state != self._last_alarm_state:
            if state == "fall":
                self.event("fall", "critical", "Fall detected", "The wearable reported a confirmed fall. Check the baby and the base station.")
            elif state == "cry":
                self.event("cry", "warning", "Sustained sound detected", "The base station reported sound above its configured threshold for 1.5 seconds.")
            elif state == "offline" and packet.get("bt_connected") is True:
                self.event("system", "warning", "Motion sensor unavailable", "The Bluetooth link is present, but the wearable is not reporting usable motion data.")
            self._last_alarm_state = state
        if now_mono - self._last_history_mono >= 1.0:
            acceleration = self.acceleration()
            if self.link_status() != "connected":
                acceleration = None
            self.store.add_history(iso(now), acceleration, self.last_packet.get("sound_level"))
            self._last_history_mono = now_mono
        self.last_error = None
        self.tick()
        return True

    def acceleration(self) -> float | None:
        values = [self.last_packet.get(key) for key in ("ax", "ay", "az")]
        if any(value is None for value in values):
            return None
        return math.sqrt(sum(value * value for value in values))

    def wearable_age_ms(self) -> int | None:
        if self.receiver_mode:
            if self._receiver_baby_anchor_mono is None or self._receiver_baby_age_ms is None:
                return None
            return self._receiver_baby_age_ms + max(0, int((self.clock.monotonic() - self._receiver_baby_anchor_mono) * 1000))
        if self.last_base_mono is None or self.reported_wearable_age_ms is None:
            return None
        return self.reported_wearable_age_ms + max(0, int((self.clock.monotonic() - self.last_base_mono) * 1000))

    def link_status(self) -> str:
        if self.receiver_mode:
            room_status = self.receiver_status()
            if room_status != "connected":
                return room_status
            age = self.wearable_age_ms()
            if self._receiver_baby_report == "waiting" or self._receiver_baby_report is None:
                return "waiting"
            if self._receiver_baby_report == "LOST":
                return "offline"
            if age is None:
                return "waiting"
            return "connected" if age < RECEIVER_BABY_TIMEOUT_SECONDS * 1000 else "offline"
        if not self.serial_connected:
            return "waiting" if self.last_base_mono is None else "offline"
        if self.last_base_mono is None:
            return "waiting"
        base_age = self.clock.monotonic() - self.last_base_mono
        wearable_age = self.wearable_age_ms()
        if self.reported_bt is not True or wearable_age is None:
            return "offline"
        age = max(base_age, wearable_age / 1000)
        if age >= OFFLINE_SECONDS:
            return "offline"
        if age >= STALE_SECONDS:
            return "stale"
        return "connected"

    def tick(self) -> None:
        now = self.clock.monotonic()
        if self.receiver_mode and not self.receiver_fresh() and not self._receiver_invalidated:
            self._invalidate_receiver()
        for command_id, command in list(self.pending.items()):
            if now >= command["deadline_mono"]:
                self.finish_command(command_id, "timeout", "No matching hardware confirmation arrived within 5 seconds.")
        status = self.link_status()
        if status != self._last_link_status:
            if status == "connected":
                self.event(
                    "connection", "info", "Wearable messages received" if self.event_only else "Wearable connected",
                    "The room unit reports recent baby activity." if self.receiver_mode else "Fresh baby-unit tokens are arriving through the serial gateway. This confirms message reception, not sensor health." if self.event_only else "Fresh telemetry is arriving through Bluetooth Classic.",
                )
            elif status == "stale":
                self.event("connection", "warning", "Wearable data is stale", "The receiver USB stream is stale. Current state is unavailable." if self.receiver_mode else "No valid wearable message for at least 3 seconds. Current device status is unavailable until messages resume." if self.event_only else "No fresh wearable heartbeat for at least 3 seconds. Readings are unavailable until the link recovers.")
            elif status == "offline":
                self.event("connection", "warning", "Wearable connection unavailable" if self.event_only else "Wearable disconnected", "The receiver link is unavailable or its reported baby activity is at least 6 seconds old." if self.receiver_mode else "The serial link closed or no valid wearable message arrived within 5 seconds. The gateway cannot identify which part of the connection failed." if self.event_only else "Bluetooth is unavailable or the wearable heartbeat exceeded 5 seconds.")
            self._last_link_status = status

    def prepare_command(self, action: str) -> dict[str, Any]:
        if not self.hardware_controls:
            raise UnsupportedControlError(f"Hardware controls are unavailable for {self.protocol}. Use the receiver's physical buttons.")
        if action not in ACTIONS:
            raise ValueError("unsupported control action")
        if not self.serial_connected or self.last_base_mono is None or self.clock.monotonic() - self.last_base_mono >= OFFLINE_SECONDS:
            raise ConnectionError("A responsive base station is required to send a command.")
        if self.pending:
            raise RuntimeError("A hardware command is already awaiting confirmation.")
        command_id = "cmd-" + uuid4().hex
        command = {
            "id": command_id,
            "action": action,
            "status": "pending",
            "requested_at": iso(self.clock.now()),
            "deadline_mono": self.clock.monotonic() + COMMAND_TIMEOUT_SECONDS,
        }
        self.pending[command_id] = command
        wire: dict[str, Any] = {"type": "command", "id": command_id, "action": action}
        if action == "acknowledge":
            wire["seconds"] = 15
        return wire

    def receive_ack(self, packet: dict[str, Any]) -> None:
        command = self.pending.get(packet["id"])
        if not command:
            return  # Unsolicited or late acknowledgments never change device state.
        if not packet["ok"]:
            self.finish_command(packet["id"], "rejected", "The base station rejected this command.")
            return
        action = command["action"]
        confirmed = (
            (action == "arm" and packet.get("armed") is True)
            or (action == "disarm" and packet.get("armed") is False)
            or (action == "acknowledge" and (packet.get("muted_ms") or 0) > 0)
        )
        if not confirmed:
            return
        if packet.get("armed") is not None:
            self.armed = packet["armed"]
        if packet.get("muted_ms") is not None:
            self.muted_until = self.clock.now() + timedelta(milliseconds=packet["muted_ms"]) if packet["muted_ms"] else None
        self.finish_command(packet["id"], "confirmed", "The base station confirmed the requested state.")

    def _confirm_from_telemetry(self, packet: dict[str, Any]) -> None:
        for command_id, command in list(self.pending.items()):
            action = command["action"]
            matches = (
                (action == "arm" and packet.get("armed") is True)
                or (action == "disarm" and packet.get("armed") is False)
                or (action == "acknowledge" and (packet.get("muted_ms") or 0) > 0)
            )
            if matches:
                self.finish_command(command_id, "confirmed", "Fresh base-station telemetry confirms the requested state.")

    def finish_command(self, command_id: str, status: str, detail: str) -> None:
        command = self.pending.pop(command_id, None)
        if command is None:
            return
        action = command["action"]
        result = {key: value for key, value in command.items() if key != "deadline_mono"}
        result.update(status=status, detail=detail, completed_at=iso(self.clock.now()))
        self.control_results[command_id] = result
        while len(self.control_results) > 100:
            self.control_results.popitem(last=False)
        if status == "confirmed":
            if action == "acknowledge":
                self.store.acknowledge()
            title = {"arm": "Monitoring armed", "disarm": "Monitoring disarmed", "acknowledge": "Alarm silenced for 15 seconds"}[action]
            self.event("system", "info", title, detail)
        else:
            self.event("system", "warning", "Command not confirmed", detail)

    def command_result(self, command_id: str) -> dict[str, Any] | None:
        command = self.pending.get(command_id) or self.control_results.get(command_id)
        if command is None:
            return None
        return {key: value for key, value in command.items() if key != "deadline_mono"}

    def snapshot(self) -> dict[str, Any]:
        self.tick()
        status = self.link_status()
        fresh = status == "connected"
        now = self.clock.now()
        base_fresh = self.serial_connected and self.last_base_mono is not None and self.clock.monotonic() - self.last_base_mono < STALE_SECONDS
        acceleration = self.acceleration() if fresh else None
        motion = "unknown"
        if acceleration is not None:
            movement = abs(acceleration - 1.0)
            gyro = max(abs(self.last_packet.get(key) or 0) for key in ("gx", "gy", "gz"))
            motion = "active" if movement > 0.3 or gyro > 35 else "gentle" if movement > 0.08 or gyro > 5 else "still"
        muted_until = iso(self.muted_until) if self.muted_until and self.muted_until > now else None
        return {
            "type": "snapshot",
            "timestamp": iso(now),
            "mode": self.mode,
            "protocol": self.protocol,
            "session_started_at": iso(self.session_started_at),
            "receiver": {
                "fresh": self.receiver_fresh(),
                "status": self.receiver_status(),
                "status_fresh": self.serial_connected and self.receiver_last_status_mono is not None and self.clock.monotonic() - self.receiver_last_status_mono < RECEIVER_STALE_SECONDS,
                "armed": self.armed if self.receiver_fresh() else None,
                "fall_active": self.receiver_fall_active if self.receiver_fresh() else None,
                "cry_active": self.receiver_cry_active if self.receiver_fresh() else None,
                "link_lost": self.receiver_link_lost if self.receiver_fresh() else None,
                "muted_until": muted_until if self.receiver_fresh() else None,
                "mute_known": self.receiver_mute_known if self.receiver_fresh() else False,
                "last_status_at": iso(self.receiver_last_status_at) if self.receiver_last_status_at else None,
                "last_line": self.receiver_last_line,
                "counters": dict(self.receiver_counts),
                "session_started_at": iso(self.session_started_at),
            } if self.receiver_mode else None,
            "capabilities": {"numeric_telemetry": not self.event_only, "hardware_controls": self.hardware_controls},
            "messages": {
                "last_token": self.last_token,
                "last_received_at": iso(self.last_wearable_at) if self.last_wearable_at else None,
                "last_heartbeat_at": iso(self.last_heartbeat_at) if self.last_heartbeat_at else None,
                "last_fall_at": iso(self.last_fall_at) if self.last_fall_at else None,
                "last_cry_at": iso(self.last_cry_at) if self.last_cry_at else None,
                "counts": dict(self.message_counts),
            } if self.protocol == "baby-ble-v5" else None,
            "connection": {
                "server": True,
                "serial": self.serial_connected,
                "bluetooth": fresh,
                "status": status,
                "last_seen": iso(self.last_wearable_at) if self.last_wearable_at else None,
                "base_last_seen": iso(self.last_base_at) if self.last_base_at else None,
                "wearable_age_ms": self.wearable_age_ms(),
                "wearable_age_estimated": self.receiver_mode,
                "transport": "BLE · GATT FFE0 / FFE1" if self.event_only else "Bluetooth Classic · SPP",
                "port": self.port,
            },
            "device": {"id": "AG-01", "name": "Nursery wearable", "battery_pct": self.last_packet.get("battery_pct") if fresh else None},
            "telemetry": {
                "accel": {axis: self.last_packet.get("a" + axis) if fresh else None for axis in "xyz"},
                "gyro": {axis: self.last_packet.get("g" + axis) if fresh else None for axis in "xyz"},
                "sound_level": self.last_packet.get("sound_level") if base_fresh else None,
                "motion": motion,
                "fall_stage": "unknown" if self.event_only else self.last_packet.get("fall_stage", "monitoring") if fresh else "monitoring",
                "state": ("unknown" if self.event_only else self.last_packet.get("state", "normal")) if fresh else "offline",
                "armed": self.armed if (self.receiver_fresh() if self.receiver_mode else base_fresh) else None,
                "muted_until": muted_until,
            },
            "history": [] if self.event_only else self.store.history(120),
            "events": self.store.events(100),
            "pending_controls": [self.command_result(key) for key in self.pending],
            "last_control": next(reversed(self.control_results.values()), None) if self.control_results else None,
            "diagnostics": {"invalid_packets": self.invalid_packets, "last_error": self.last_error},
        }
