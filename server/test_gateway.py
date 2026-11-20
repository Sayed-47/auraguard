"""Run: python -m unittest discover -s server -p 'test_*.py' -v"""

from datetime import datetime, timedelta, timezone
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from state import Clock, MAX_LINE_BYTES, Monitor, Store, validate_packet


class FakeClock(Clock):
    def __init__(self):
        self.seconds = 0.0
        self.epoch = datetime(2026, 1, 1, tzinfo=timezone.utc)

    def monotonic(self):
        return self.seconds

    def now(self):
        return self.epoch + timedelta(seconds=self.seconds)

    def advance(self, seconds):
        self.seconds += seconds


def telemetry(**changes):
    packet = {
        "seq": 1, "uptime_ms": 1000,
        "ax": 0.0, "ay": 0.0, "az": 1.0,
        "gx": 0.0, "gy": 0.0, "gz": 0.0,
        "sound_level": 28.0, "state": "normal", "fall_stage": "monitoring",
        "armed": True, "muted_ms": 0, "bt_connected": True,
        "wearable_age_ms": 40, "battery_pct": None,
    }
    packet.update(changes)
    return packet


class MonitorTests(unittest.TestCase):
    def setUp(self):
        self.store = Store(":memory:")
        self.clock = FakeClock()
        self.monitor = Monitor(self.store, port="COM5", clock=self.clock)

    def tearDown(self):
        self.store.close()

    def ready(self, **changes):
        self.monitor.set_serial(True)
        self.monitor.ingest(telemetry(**changes))

    def test_initial_state_contains_no_fake_hardware_readings(self):
        result = self.monitor.snapshot()
        self.assertEqual(result["mode"], "live")
        self.assertFalse(result["connection"]["bluetooth"])
        self.assertFalse(result["connection"]["serial"])
        self.assertIsNone(result["telemetry"]["accel"]["x"])
        self.assertIsNone(result["telemetry"]["armed"])
        self.assertIsNone(result["device"]["battery_pct"])
        self.assertEqual(result["history"], [])

    def test_normalization_and_unknown_battery(self):
        self.ready(ax=0.3, ay=0.4, az=0.0)
        result = self.monitor.snapshot()
        self.assertTrue(result["connection"]["bluetooth"])
        self.assertEqual(result["connection"]["wearable_age_ms"], 40)
        self.assertAlmostEqual(result["history"][-1]["acceleration"], 0.5)
        self.assertEqual(result["telemetry"]["sound_level"], 28)
        self.assertIsNone(result["device"]["battery_pct"])

    def test_usb_activity_does_not_hide_lost_bluetooth(self):
        self.ready()
        self.clock.advance(5.5)
        self.monitor.ingest(telemetry(seq=2, wearable_age_ms=5540, sound_level=42))
        result = self.monitor.snapshot()
        self.assertTrue(result["connection"]["serial"])
        self.assertFalse(result["connection"]["bluetooth"])
        self.assertEqual(result["connection"]["status"], "offline")
        self.assertIsNone(result["telemetry"]["accel"]["z"])
        self.assertEqual(result["telemetry"]["sound_level"], 42)
        self.assertEqual(result["telemetry"]["state"], "offline")

    def test_stale_status_hides_old_measurements_before_offline(self):
        self.ready()
        self.clock.advance(3.1)
        result = self.monitor.snapshot()
        self.assertEqual(result["connection"]["status"], "stale")
        self.assertFalse(result["connection"]["bluetooth"])
        self.assertEqual(result["telemetry"]["motion"], "unknown")
        self.assertIsNone(result["telemetry"]["sound_level"])
        self.clock.advance(2)
        self.assertEqual(self.monitor.snapshot()["connection"]["status"], "offline")

    def test_sensor_failure_preserves_transport_and_offline_state(self):
        self.ready(ax=None, ay=None, az=None, gx=None, gy=None, gz=None, state="offline")
        result = self.monitor.snapshot()
        self.assertTrue(result["connection"]["bluetooth"])
        self.assertEqual(result["telemetry"]["state"], "offline")
        self.assertEqual(result["telemetry"]["motion"], "unknown")

    def test_invalid_numeric_and_enum_values_are_rejected(self):
        self.ready()
        before = self.monitor.snapshot()["telemetry"]
        for change in ({"sound_level": float("nan")}, {"ax": True}, {"state": "SAFE"}, {"battery_pct": 101}, {"armed": "true"}):
            with self.subTest(change=change):
                self.assertFalse(self.monitor.ingest_line(json.dumps(telemetry(**change))))
        self.assertEqual(self.monitor.invalid_packets, 5)
        self.assertEqual(self.monitor.snapshot()["telemetry"], before)
        self.assertFalse(self.monitor.ingest_line(b"x" * (MAX_LINE_BYTES + 1)))

    def test_fall_events_are_recorded_once_per_transition(self):
        self.ready(state="fall", fall_stage="confirmed")
        self.monitor.ingest(telemetry(seq=2, state="fall", fall_stage="confirmed"))
        self.monitor.ingest(telemetry(seq=3, state="normal"))
        self.monitor.ingest(telemetry(seq=4, state="fall", fall_stage="confirmed"))
        falls = [event for event in self.store.events() if event["type"] == "fall"]
        self.assertEqual(len(falls), 2)
        self.assertTrue(all(event["severity"] == "critical" for event in falls))

    def test_command_does_not_change_hardware_state_before_confirmation(self):
        self.ready()
        command = self.monitor.prepare_command("disarm")
        self.assertTrue(self.monitor.snapshot()["telemetry"]["armed"])
        self.assertEqual(self.monitor.command_result(command["id"])["status"], "pending")
        self.monitor.ingest({"type": "command_ack", "id": command["id"], "ok": True, "armed": False, "muted_ms": 0})
        self.assertFalse(self.monitor.snapshot()["telemetry"]["armed"])
        self.assertEqual(self.monitor.command_result(command["id"])["status"], "confirmed")

    def test_unrelated_and_incomplete_ack_cannot_mutate_device_state(self):
        self.ready()
        command = self.monitor.prepare_command("disarm")
        self.monitor.ingest({"type": "command_ack", "id": "unknown", "ok": True, "armed": False})
        self.monitor.ingest({"type": "command_ack", "id": command["id"], "ok": True})
        self.assertTrue(self.monitor.armed)
        self.assertIn(command["id"], self.monitor.pending)

    def test_new_telemetry_can_confirm_command(self):
        self.ready()
        command = self.monitor.prepare_command("disarm")
        self.clock.advance(0.5)
        self.monitor.ingest(telemetry(seq=2, armed=False))
        self.assertFalse(self.monitor.armed)
        self.assertEqual(self.monitor.command_result(command["id"])["status"], "confirmed")

    def test_command_timeout_does_not_assume_success(self):
        self.ready()
        command = self.monitor.prepare_command("disarm")
        self.clock.advance(5.1)
        self.monitor.tick()
        self.assertTrue(self.monitor.armed)
        self.assertEqual(self.monitor.command_result(command["id"])["status"], "timeout")
        self.monitor.ingest({"type": "command_ack", "id": command["id"], "ok": True, "armed": False})
        self.assertTrue(self.monitor.armed)

    def test_disconnect_fails_pending_control(self):
        self.ready()
        command = self.monitor.prepare_command("disarm")
        self.monitor.set_serial(False)
        self.assertEqual(self.monitor.command_result(command["id"])["status"], "failed")
        self.assertTrue(self.monitor.armed)

    def test_reject_parallel_control_and_offline_control(self):
        with self.assertRaises(ConnectionError):
            self.monitor.prepare_command("arm")
        self.ready()
        self.monitor.prepare_command("disarm")
        with self.assertRaises(RuntimeError):
            self.monitor.prepare_command("acknowledge")

    def test_silencing_acknowledges_events_without_clearing_fall(self):
        self.ready(state="fall", fall_stage="confirmed")
        command = self.monitor.prepare_command("acknowledge")
        self.monitor.ingest({"type": "command_ack", "id": command["id"], "ok": True, "armed": True, "muted_ms": 15000})
        result = self.monitor.snapshot()
        self.assertEqual(result["telemetry"]["state"], "fall")
        self.assertIsNotNone(result["telemetry"]["muted_until"])
        self.assertTrue(next(event for event in result["events"] if event["type"] == "fall")["acknowledged"])
        self.clock.advance(15.1)
        self.assertIsNone(self.monitor.snapshot()["telemetry"]["muted_until"])

    def test_history_is_limited_to_one_received_sample_per_second(self):
        self.ready()
        for sequence in range(2, 102):
            self.clock.advance(0.005)
            self.monitor.ingest(telemetry(seq=sequence))
        self.assertEqual(len(self.store.history()), 1)
        self.clock.advance(1)
        self.monitor.ingest(telemetry(seq=103))
        self.assertEqual(len(self.store.history()), 2)


class BabyBleV5Tests(unittest.TestCase):
    def setUp(self):
        self.store = Store(":memory:")
        self.clock = FakeClock()
        self.monitor = Monitor(self.store, port="COM5", clock=self.clock, protocol="baby-ble-v5")
        self.monitor.set_serial(True)

    def tearDown(self):
        self.store.close()

    def test_tokens_produce_reception_information_without_fake_measurements(self):
        self.assertTrue(self.monitor.ingest_line(b"OK\r\n"))
        self.clock.advance(1)
        self.assertTrue(self.monitor.ingest_line("FALL\n"))
        self.clock.advance(1)
        self.assertTrue(self.monitor.ingest_line("CRY"))
        snapshot = self.monitor.snapshot()
        self.assertEqual(snapshot["protocol"], "baby-ble-v5")
        self.assertEqual(snapshot["capabilities"], {"numeric_telemetry": False, "hardware_controls": False})
        self.assertEqual(snapshot["messages"]["counts"], {"OK": 1, "FALL": 1, "CRY": 1})
        self.assertEqual(snapshot["messages"]["last_token"], "CRY")
        self.assertEqual(snapshot["messages"]["last_heartbeat_at"], "2026-01-01T00:00:00.000Z")
        self.assertEqual(snapshot["messages"]["last_fall_at"], "2026-01-01T00:00:01.000Z")
        self.assertEqual(snapshot["messages"]["last_cry_at"], "2026-01-01T00:00:02.000Z")
        self.assertEqual(snapshot["connection"]["last_seen"], snapshot["messages"]["last_received_at"])
        self.assertEqual(snapshot["connection"]["transport"], "BLE · GATT FFE0 / FFE1")
        self.assertTrue(snapshot["connection"]["bluetooth"])
        self.assertEqual(snapshot["telemetry"]["state"], "unknown")
        self.assertEqual(snapshot["telemetry"]["fall_stage"], "unknown")
        for field in ("accel", "gyro"):
            self.assertTrue(all(value is None for value in snapshot["telemetry"][field].values()))
        for field in ("armed", "muted_until", "sound_level"):
            self.assertIsNone(snapshot["telemetry"][field])
        self.assertIsNone(snapshot["device"]["battery_pct"])
        self.assertEqual(snapshot["history"], [])
        self.assertEqual(self.store.history(), [])

    def test_heartbeat_does_not_clear_or_acknowledge_reported_alerts(self):
        self.monitor.ingest_line("FALL")
        self.clock.advance(0.5)
        self.monitor.ingest_line("CRY")
        before = [e for e in self.store.events() if e["type"] in {"fall", "cry"}]
        for _ in range(5):
            self.clock.advance(1)
            self.monitor.ingest_line("OK")
        after = [e for e in self.store.events() if e["type"] in {"fall", "cry"}]
        self.assertEqual(after, before)
        self.assertTrue(all(not e["acknowledged"] for e in after))
        snapshot = self.monitor.snapshot()
        self.assertEqual(snapshot["telemetry"]["state"], "unknown")
        self.assertIsNotNone(snapshot["messages"]["last_fall_at"])
        self.assertIsNotNone(snapshot["messages"]["last_cry_at"])
        self.assertFalse(any("clear" in e["title"].lower() or "settled" in e["title"].lower() for e in self.store.events()))

    def test_repeated_cry_reports_are_counted_but_grouped_as_reception_bursts(self):
        for _ in range(4):
            self.monitor.ingest_line("CRY")
            self.monitor.ingest_line("OK")
            self.clock.advance(1)
        cries = [e for e in self.store.events() if e["type"] == "cry"]
        self.assertEqual(len(cries), 1)
        self.assertIn("reception burst", cries[0]["detail"])
        self.assertEqual(self.monitor.snapshot()["messages"]["counts"]["CRY"], 4)
        self.clock.advance(2)  # Three seconds since the preceding CRY report.
        self.monitor.ingest_line("CRY")
        self.assertEqual(len([e for e in self.store.events() if e["type"] == "cry"]), 2)
        self.assertEqual(self.monitor.snapshot()["messages"]["counts"]["CRY"], 5)

    def test_every_fall_token_is_preserved_without_claiming_detection_reason(self):
        self.monitor.ingest_line("FALL")
        self.clock.advance(0.1)
        self.monitor.ingest_line("FALL")
        falls = [e for e in self.store.events() if e["type"] == "fall"]
        self.assertEqual(len(falls), 2)
        self.assertTrue(all("BOOT" in e["detail"] and "sensor-loss" in e["detail"] for e in falls))
        self.assertTrue(all(e["title"] == "Possible fall reported" for e in falls))
        self.assertEqual(self.monitor.snapshot()["messages"]["counts"]["FALL"], 2)

    def test_invalid_lines_do_not_extend_liveness_or_change_message_counts(self):
        self.monitor.ingest_line("OK")
        last_seen = self.monitor.snapshot()["connection"]["last_seen"]
        self.clock.advance(3)
        invalid = ["ACK", "ok", "OK ", " OK", "[BLE] READY", "status | link=UP", "CRY_END", "OK\nFALL", "OK\n\n", "OK\r", "OK\r\r\n", "", json.dumps(telemetry()), b"\xff", b"X" * (MAX_LINE_BYTES + 1)]
        for line in invalid:
            with self.subTest(line=repr(line)[:60]):
                self.assertFalse(self.monitor.ingest_line(line))
        snapshot = self.monitor.snapshot()
        self.assertEqual(snapshot["connection"]["status"], "stale")
        self.assertEqual(snapshot["connection"]["last_seen"], last_seen)
        self.assertEqual(snapshot["messages"]["counts"], {"OK": 1, "FALL": 0, "CRY": 0})
        self.assertEqual(self.monitor.invalid_packets, len(invalid))
        self.clock.advance(2)
        self.assertEqual(self.monitor.snapshot()["connection"]["status"], "offline")

    def test_stale_and_offline_deadlines_then_recovery_preserve_alert_history(self):
        self.monitor.ingest_line("FALL")
        self.clock.advance(2.999)
        self.assertEqual(self.monitor.snapshot()["connection"]["status"], "connected")
        self.clock.advance(0.001)
        snapshot = self.monitor.snapshot()
        self.assertEqual(snapshot["connection"]["status"], "stale")
        self.assertFalse(snapshot["connection"]["bluetooth"])
        self.assertEqual(snapshot["telemetry"]["state"], "offline")
        self.clock.advance(2)
        self.assertEqual(self.monitor.snapshot()["connection"]["status"], "offline")
        self.monitor.ingest_line("OK")
        snapshot = self.monitor.snapshot()
        self.assertEqual(snapshot["connection"]["status"], "connected")
        self.assertEqual(snapshot["telemetry"]["state"], "unknown")
        self.assertEqual(len([e for e in snapshot["events"] if e["type"] == "fall"]), 1)
        self.monitor.set_serial(False)
        self.assertFalse(self.monitor.snapshot()["connection"]["bluetooth"])

    def test_controls_and_direct_json_ingestion_are_rejected_without_mutation(self):
        from state import UnsupportedControlError
        self.monitor.ingest_line("FALL")
        before = self.monitor.snapshot()
        for action in ("arm", "disarm", "acknowledge"):
            with self.assertRaises(UnsupportedControlError):
                self.monitor.prepare_command(action)
        with self.assertRaises(ValueError):
            self.monitor.ingest(telemetry())
        self.assertEqual(self.monitor.snapshot(), before)
        self.assertEqual(self.monitor.pending, {})

    def test_restart_keeps_event_history_but_not_live_state_or_session_counts(self):
        self.monitor.ingest_line("CRY")
        restarted = Monitor(self.store, clock=self.clock, protocol="baby-ble-v5")
        snapshot = restarted.snapshot()
        self.assertFalse(snapshot["connection"]["bluetooth"])
        self.assertEqual(snapshot["messages"]["counts"], {"OK": 0, "FALL": 0, "CRY": 0})
        self.assertIsNone(snapshot["messages"]["last_received_at"])
        self.assertTrue(any(e["type"] == "cry" for e in snapshot["events"]))

    def test_invalid_protocol_is_rejected(self):
        with self.assertRaises(ValueError):
            Monitor(self.store, protocol="auto")


def room_status(armed=1, baby="linked", age=0, mic="remote", cry=0):
    return f"status | armed={armed} baby={baby} lastMsg={age}s ago mic={mic} cry={cry}"


class UnoRoomTests(unittest.TestCase):
    def setUp(self):
        self.store = Store(":memory:")
        self.clock = FakeClock()
        self.monitor = Monitor(self.store, port="COM5", clock=self.clock, protocol="uno-room-v1")
        self.monitor.set_serial(True)

    def tearDown(self):
        self.store.close()

    def line(self, text):
        self.assertTrue(self.monitor.ingest_line(text))
        return self.monitor.snapshot()

    def startup(self):
        from state import ROOM_READY
        return self.line(ROOM_READY)

    def test_late_attach_keeps_fall_and_mute_unknown(self):
        result = self.line(room_status())
        receiver = result["receiver"]
        self.assertTrue(receiver["fresh"])
        self.assertTrue(receiver["status_fresh"])
        self.assertEqual(receiver["status"], "connected")
        self.assertTrue(receiver["armed"])
        self.assertFalse(receiver["cry_active"])
        self.assertIsNone(receiver["fall_active"])
        self.assertFalse(receiver["mute_known"])
        self.assertIsNone(receiver["muted_until"])
        self.assertTrue(result["connection"]["bluetooth"])
        self.assertTrue(result["connection"]["wearable_age_estimated"])
        self.assertIsNone(result["messages"])
        self.assertEqual(result["history"], [])
        self.assertFalse(result["capabilities"]["hardware_controls"])
        self.assertFalse(result["capabilities"]["numeric_telemetry"])

    def test_startup_establishes_known_defaults_and_resets_prior_live_flags(self):
        self.line("!!! FALL ALERT from baby unit !!!")
        self.line("CRY reported by baby unit")
        self.line("ACKNOWLEDGED (sent ACK to baby unit)")
        result = self.startup()
        receiver = result["receiver"]
        self.assertTrue(receiver["armed"])
        self.assertFalse(receiver["fall_active"])
        self.assertFalse(receiver["cry_active"])
        self.assertFalse(receiver["link_lost"])
        self.assertTrue(receiver["mute_known"])
        self.assertIsNone(receiver["muted_until"])
        self.assertEqual(result["connection"]["status"], "waiting")
        self.assertIsNone(result["connection"]["last_seen"])
        self.assertEqual(receiver["counters"], {"fall_reports": 1, "cry_episodes": 1, "acknowledgments": 1, "wander_reports": 0})
        self.assertTrue(any(e["type"] == "fall" for e in result["events"]))

    def test_healthy_periodic_status_does_not_clear_fall(self):
        self.line("!!! FALL ALERT from baby unit !!!")
        self.clock.advance(2)
        result = self.line(room_status())
        self.assertTrue(result["receiver"]["fall_active"])
        self.assertFalse(result["receiver"]["cry_active"])
        self.assertEqual(result["receiver"]["counters"]["fall_reports"], 1)

    def test_ack_clears_fall_and_mutes_but_preserves_cry_and_link_loss(self):
        self.line("!!! FALL ALERT from baby unit !!!")
        self.line("CRY reported by baby unit")
        self.line("!!! LINK LOST - no signal from baby unit !!!")
        result = self.line("ACKNOWLEDGED (sent ACK to baby unit)")
        receiver = result["receiver"]
        self.assertFalse(receiver["fall_active"])
        self.assertTrue(receiver["cry_active"])
        self.assertTrue(receiver["link_lost"])
        self.assertTrue(receiver["mute_known"])
        self.assertEqual(receiver["muted_until"], "2026-01-01T00:00:15.000Z")
        self.assertFalse(result["connection"]["bluetooth"])
        for age in range(2, 17, 2):
            self.clock.advance(2)
            result = self.line(room_status(baby="LOST", age=age, cry=1))
        self.assertIsNone(result["receiver"]["muted_until"])
        self.assertTrue(result["receiver"]["mute_known"])
        self.assertTrue(result["receiver"]["cry_active"])

    def test_arm_toggle_clears_flags_preserves_mute_and_does_not_fake_heartbeat(self):
        self.startup()
        self.line("ACKNOWLEDGED (sent ACK to baby unit)")
        self.line("!!! FALL ALERT from baby unit !!!")
        self.line("CRY reported by baby unit")
        self.clock.advance(1)
        result = self.line("DISARMED")
        self.assertFalse(result["receiver"]["armed"])
        self.assertFalse(result["receiver"]["fall_active"])
        self.assertFalse(result["receiver"]["cry_active"])
        self.assertFalse(result["receiver"]["link_lost"])
        self.assertIsNotNone(result["receiver"]["muted_until"])
        self.assertIsNone(result["connection"]["wearable_age_ms"])
        self.clock.advance(1)
        result = self.line(room_status(armed=0, age=1))
        self.assertFalse(result["connection"]["bluetooth"])
        self.clock.advance(2)
        result = self.line(room_status(armed=0, age=3))
        self.assertFalse(result["connection"]["bluetooth"])
        self.clock.advance(2)
        result = self.line(room_status(armed=0, age=0))
        self.assertTrue(result["connection"]["bluetooth"])

    def test_fall_is_recorded_while_disarmed(self):
        self.line("DISARMED")
        result = self.line("!!! FALL ALERT from baby unit !!!")
        self.assertFalse(result["receiver"]["armed"])
        self.assertTrue(result["receiver"]["fall_active"])

    def test_room_activity_does_not_extend_baby_activity_clock(self):
        self.line(room_status())
        self.clock.advance(3)
        self.line("ACKNOWLEDGED (sent ACK to baby unit)")
        self.clock.advance(2)
        self.line("cry ended")
        self.clock.advance(1)
        result = self.monitor.snapshot()
        self.assertTrue(result["receiver"]["fresh"])
        self.assertFalse(result["connection"]["bluetooth"])
        self.assertEqual(result["connection"]["wearable_age_ms"], 6000)
        self.assertEqual(result["connection"]["status"], "offline")

    def test_disarmed_linked_status_with_old_lastmsg_is_not_live(self):
        result = self.line(room_status(armed=0, age=20))
        self.assertFalse(result["connection"]["bluetooth"])
        self.assertFalse(result["receiver"]["link_lost"])
        self.assertTrue(result["receiver"]["fresh"])
        self.assertFalse(result["receiver"]["armed"])

    def test_periodic_status_and_explicit_cry_end_clear_only_sound_flag(self):
        self.line("!!! FALL ALERT from baby unit !!!")
        self.line("CRY reported by baby unit")
        result = self.line("cry ended")
        self.assertFalse(result["receiver"]["cry_active"])
        self.assertTrue(result["receiver"]["fall_active"])
        self.line("CRY reported by baby unit")
        result = self.line(room_status(cry=0))
        self.assertFalse(result["receiver"]["cry_active"])
        self.assertEqual(result["receiver"]["counters"]["cry_episodes"], 2)

    def test_stale_receiver_and_disconnect_invalidate_unobserved_current_state(self):
        self.startup()
        self.line("!!! FALL ALERT from baby unit !!!")
        self.line("ACKNOWLEDGED (sent ACK to baby unit)")
        self.clock.advance(5)
        result = self.monitor.snapshot()
        self.assertEqual(result["receiver"]["status"], "stale")
        self.assertFalse(result["receiver"]["fresh"])
        for key in ("armed", "fall_active", "cry_active", "link_lost", "muted_until"):
            self.assertIsNone(result["receiver"][key])
        self.assertFalse(result["receiver"]["mute_known"])
        result = self.line(room_status())
        self.assertIsNone(result["receiver"]["fall_active"])
        self.line("!!! FALL ALERT from baby unit !!!")
        self.monitor.set_serial(False)
        result = self.monitor.snapshot()
        self.assertEqual(result["receiver"]["status"], "offline")
        self.assertIsNone(result["receiver"]["fall_active"])
        self.monitor.set_serial(True)
        result = self.line(room_status())
        self.assertIsNone(result["receiver"]["fall_active"])
        self.assertFalse(result["receiver"]["mute_known"])

    def test_invalid_and_unknown_lines_never_act_as_controls_or_heartbeat(self):
        self.line(room_status())
        self.clock.advance(4)
        before = self.monitor.snapshot()["connection"]["base_last_seen"]
        self.line("unknown msg: ARMED")
        self.assertIsNone(self.monitor.snapshot()["connection"]["last_seen"])
        self.assertEqual(self.monitor.snapshot()["connection"]["base_last_seen"], before)
        invalid = ["OK", "FALL", "ACK", "armed", "unknown msg: ", "prefix ARMED", "ARMED suffix", room_status(armed=2), room_status(mic=1024), room_status(age=4294968), room_status(baby="LOst"), room_status()+" extra", "status | armed=1 baby=linked lastMsg=-1s ago mic=remote cry=0"]
        for line in invalid:
            self.assertFalse(self.monitor.ingest_line(line), line)
        self.clock.advance(1)
        self.assertFalse(self.monitor.snapshot()["receiver"]["fresh"])
        self.assertEqual(self.monitor.snapshot()["receiver"]["counters"], {"fall_reports": 0, "cry_episodes": 0, "acknowledgments": 0, "wander_reports": 0})

    def test_unknown_message_timer_reset_and_link_notices_are_not_valid_baby_tokens(self):
        self.line("Baby unit LINKED (first message received)")
        result = self.line("unknown msg: nonsense")
        self.assertFalse(result["connection"]["bluetooth"])
        self.clock.advance(2)
        result = self.line(room_status(age=2))
        self.assertFalse(result["connection"]["bluetooth"])
        self.clock.advance(2)
        result = self.line(room_status(age=0))
        self.assertTrue(result["connection"]["bluetooth"])

    def test_missing_arm_event_does_not_preserve_unjustified_fall_or_mute(self):
        self.startup()
        self.line("ACKNOWLEDGED (sent ACK to baby unit)")
        self.line("!!! FALL ALERT from baby unit !!!")
        self.clock.advance(2)
        result = self.line(room_status(armed=0))
        self.assertIsNone(result["receiver"]["fall_active"])
        self.assertFalse(result["receiver"]["mute_known"])
        self.assertFalse(result["connection"]["bluetooth"])

    def test_optional_local_mic_logs_are_accepted_without_inventing_relative_levels(self):
        self.line("Room unit ready. Mic baseline = 512")
        self.clock.advance(2)
        result = self.line(room_status(baby="waiting", age=2, mic=600))
        self.assertIsNone(result["telemetry"]["sound_level"])
        self.assertFalse(result["connection"]["bluetooth"])
        self.assertEqual(result["receiver"]["counters"]["cry_episodes"], 0)

    def test_armed_only_logs_after_missed_arm_transition_invalidate_old_fall_state(self):
        for log in ("CRY reported by baby unit", "cry ended", "!!! LINK LOST - no signal from baby unit !!!"):
            with self.subTest(log=log):
                self.startup()
                self.line("DISARMED")
                self.line("!!! FALL ALERT from baby unit !!!")
                result = self.line(log)
                self.assertTrue(result["receiver"]["armed"])
                self.assertIsNone(result["receiver"]["fall_active"])
                self.assertFalse(result["receiver"]["mute_known"])
                result = self.line(room_status(armed=1, baby="LOST" if "LINK LOST" in log else "linked"))
                self.assertIsNone(result["receiver"]["fall_active"])

    def test_demo_monitor_mode_is_unavailable(self):
        with self.assertRaises(ValueError):
            Monitor(self.store, mode="demo", protocol="uno-room-v1")


class PersistenceTests(unittest.TestCase):
    def test_local_history_survives_restart_without_restoring_live_connection(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "monitor.sqlite3"
            store = Store(path)
            monitor = Monitor(store, clock=FakeClock())
            monitor.set_serial(True)
            monitor.ingest(telemetry(state="cry"))
            store.close()
            store = Store(path)
            restarted = Monitor(store, clock=FakeClock())
            result = restarted.snapshot()
            self.assertEqual(len(result["history"]), 1)
            self.assertTrue(any(event["type"] == "cry" for event in result["events"]))
            self.assertFalse(result["connection"]["bluetooth"])
            self.assertEqual(result["telemetry"]["state"], "offline")
            store.close()


HAVE_API_DEPS = all(importlib.util.find_spec(name) for name in ("fastapi", "httpx"))


@unittest.skipUnless(HAVE_API_DEPS, "Install server/requirements-test.txt for HTTP and WebSocket tests")
class ApiTests(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        from app import Settings, create_app
        self.app = create_app(Settings(database=":memory:", protocol="json-v1"))
        self.client = TestClient(self.app)
        self.client.__enter__()
        # Explicit test fixture, never a runtime simulation mode or endpoint.
        self.client.portal.call(self.app.state.monitor.set_serial, True)
        self.client.portal.call(self.app.state.monitor.ingest, telemetry())

    def tearDown(self):
        self.client.__exit__(None, None, None)

    def test_live_status_websocket_history_and_export(self):
        response = self.client.get("/api/status")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["mode"], "live")
        with self.client.websocket_connect("/ws") as ws:
            snapshot = ws.receive_json()
            self.assertEqual(snapshot["type"], "snapshot")
            self.assertTrue(snapshot["connection"]["bluetooth"])
        self.assertGreaterEqual(len(self.client.get("/api/history?limit=5").json()), 1)
        export = self.client.get("/api/export.csv")
        self.assertEqual(export.status_code, 200)
        self.assertIn("sound_level_relative_0_100", export.text)
        self.assertIn("live", export.text)

    def test_control_requires_configured_serial_transport(self):
        self.assertEqual(self.client.post("/api/control", json={"action": "disarm"}).status_code, 503)

    def test_foreign_browser_origin_is_rejected(self):
        response = self.client.post("/api/control", json={"action": "disarm"}, headers={"Origin": "https://unrelated.example"})
        self.assertEqual(response.status_code, 403)
        from starlette.websockets import WebSocketDisconnect
        with self.assertRaises(WebSocketDisconnect):
            with self.client.websocket_connect("/ws", headers={"Origin": "https://unrelated.example"}):
                pass

    def test_invalid_action_and_unbounded_queries_are_rejected(self):
        self.assertEqual(self.client.post("/api/control", json={"action": "reboot"}).status_code, 422)
        self.assertEqual(self.client.get("/api/history?limit=999999999").status_code, 422)

    def test_partial_and_oversized_serial_framing(self):
        from app import LineFramer
        framing = LineFramer()
        self.assertEqual(framing.feed(b'{"state":'), [])
        self.assertEqual(framing.feed(b'"normal"}\n'), [b'{"state":"normal"}'])
        self.assertEqual(framing.feed(b'x' * (MAX_LINE_BYTES + 20)), [])
        self.assertEqual(framing.feed(b'ignored tail\n{"state":"fall"}\n'), [b'{"state":"fall"}'])
        self.assertEqual(framing.dropped, 1)


@unittest.skipUnless(HAVE_API_DEPS, "Install server/requirements-test.txt for receiver HTTP tests")
class LiveReceiverApiTests(unittest.TestCase):
    def test_default_app_waits_for_hardware_and_never_generates_values(self):
        from fastapi.testclient import TestClient
        import app
        from app import Settings, create_app
        self.assertFalse(hasattr(app, "DemoTransport"))
        with TestClient(create_app(Settings(database=":memory:"))) as client:
            for snapshot in (client.get("/api/status").json(), client.get("/api/status").json()):
                self.assertEqual(snapshot["protocol"], "uno-room-v1")
                self.assertEqual(snapshot["mode"], "live")
                self.assertFalse(snapshot["connection"]["serial"])
                self.assertFalse(snapshot["connection"]["bluetooth"])
                self.assertEqual(snapshot["receiver"]["counters"], {"fall_reports": 0, "cry_episodes": 0, "acknowledgments": 0, "wander_reports": 0})
                self.assertFalse(snapshot["capabilities"]["numeric_telemetry"])
                self.assertFalse(snapshot["capabilities"]["hardware_controls"])
                self.assertIsNone(snapshot["telemetry"]["sound_level"])
                self.assertIsNone(snapshot["receiver"]["fall_active"])
                self.assertFalse(snapshot["receiver"]["mute_known"])
                self.assertIsNone(snapshot["messages"])
            self.assertEqual(client.get("/api/history").json(), [])
            self.assertEqual(len(client.get("/api/export.csv").text.splitlines()), 1)
            with client.websocket_connect("/ws") as websocket:
                message = websocket.receive_json()
                self.assertEqual(message["protocol"], "uno-room-v1")
                self.assertEqual(message["receiver"]["status"], "waiting")

    def test_control_api_rejects_before_send_for_both_read_only_profiles(self):
        from fastapi.testclient import TestClient
        from app import Settings, create_app
        class ForbiddenTransport:
            async def send(self, command):
                raise AssertionError("read-only profile attempted serial write")
        for protocol in ("uno-room-v1", "baby-ble-v5"):
            with self.subTest(protocol=protocol):
                app = create_app(Settings(database=":memory:", protocol=protocol))
                with TestClient(app) as client:
                    app.state.transport = ForbiddenTransport()
                    for action in ("arm", "disarm", "acknowledge"):
                        response = client.post("/api/control", json={"action": action})
                        self.assertEqual(response.status_code, 409)
                        self.assertIn("unavailable", response.json()["detail"])
                    snapshot = client.get("/api/status").json()
                    self.assertEqual(snapshot["pending_controls"], [])
                    self.assertIsNone(snapshot["last_control"])

    def test_profiles_have_separate_live_databases_and_no_demo_setting(self):
        from app import Settings
        paths = {Settings(protocol=protocol).db_path for protocol in ("uno-room-v1", "baby-ble-v5", "json-v1")}
        self.assertEqual(len(paths), 3)
        self.assertEqual(Settings().protocol, "uno-room-v1")
        self.assertEqual(Settings().baud, 9600)
        self.assertEqual(Settings(database=":memory:").db_path, ":memory:")
        with self.assertRaises(ValueError):
            Settings(protocol="unknown")
        with self.assertRaises(TypeError):
            Settings(demo=True)

    def test_split_crlf_and_invalid_framed_lines_do_not_create_false_heartbeats(self):
        from app import LineFramer
        store = Store(":memory:")
        try:
            monitor = Monitor(store, protocol="baby-ble-v5")
            monitor.set_serial(True)
            framer = LineFramer()
            self.assertEqual(framer.feed(b"FA"), [])
            lines = framer.feed(b"LL\r\nOK\r\r\nACK\nCRY\r\n")
            results = [monitor.ingest_line(line) for line in lines]
            self.assertEqual(results, [True, False, False, True])
            self.assertEqual(monitor.snapshot()["messages"]["counts"], {"OK": 0, "FALL": 1, "CRY": 1})
        finally:
            store.close()


@unittest.skipUnless(HAVE_API_DEPS and os.name == "posix" and importlib.util.find_spec("serial"), "Serial integration test requires POSIX and installed dependencies")
class SerialIntegrationTests(unittest.TestCase):
    def test_uno_usb_logs_reach_http_and_controls_write_no_serial_bytes(self):
        import pty
        import select
        from fastapi.testclient import TestClient
        from app import Settings, create_app
        from state import ROOM_READY
        master, slave = pty.openpty()
        try:
            with TestClient(create_app(Settings(port=os.ttyname(slave), database=":memory:"))) as client:
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline:
                    if client.get("/api/status").json()["connection"]["serial"]:
                        break
                    time.sleep(0.02)
                self.assertTrue(client.get("/api/status").json()["connection"]["serial"])
                payload = (ROOM_READY + "\r\n!!! FALL ALERT from baby unit !!!\r\n" + room_status() + "\r\n").encode()
                os.write(master, payload[:23])
                os.write(master, payload[23:])
                deadline = time.monotonic() + 2
                while time.monotonic() < deadline:
                    snapshot = client.get("/api/status").json()
                    if snapshot["receiver"]["fall_active"] is True:
                        break
                    time.sleep(0.02)
                self.assertTrue(snapshot["receiver"]["fall_active"])
                self.assertTrue(snapshot["connection"]["bluetooth"])
                self.assertEqual(snapshot["receiver"]["counters"]["fall_reports"], 1)
                self.assertEqual(client.post("/api/control", json={"action": "acknowledge"}).status_code, 409)
                self.assertEqual(select.select([master], [], [], 0.1)[0], [])
                os.write(master, b"ACKNOWLEDGED (sent ACK to baby unit)\r\n")
                deadline = time.monotonic() + 2
                while time.monotonic() < deadline:
                    snapshot = client.get("/api/status").json()
                    if snapshot["receiver"]["counters"]["acknowledgments"] == 1:
                        break
                    time.sleep(0.02)
                self.assertFalse(snapshot["receiver"]["fall_active"])
                self.assertIsNotNone(snapshot["receiver"]["muted_until"])
                os.close(master)
                master = None
                deadline = time.monotonic() + 2
                while time.monotonic() < deadline:
                    snapshot = client.get("/api/status").json()
                    if not snapshot["connection"]["serial"]:
                        break
                    time.sleep(0.02)
                self.assertFalse(snapshot["connection"]["serial"])
                self.assertIsNone(snapshot["receiver"]["fall_active"])
                self.assertFalse(snapshot["receiver"]["mute_known"])
        finally:
            if master is not None:
                os.close(master)
            os.close(slave)

    def test_real_pyserial_transport_receives_data_and_confirms_command(self):
        """A pseudo-terminal emulates the base board; no Bluetooth hardware is claimed."""
        import pty
        import select
        from fastapi.testclient import TestClient
        from app import Settings, create_app

        master, slave = pty.openpty()
        try:
            serial_path = os.ttyname(slave)
            with TestClient(create_app(Settings(port=serial_path, database=":memory:", protocol="json-v1"))) as client:
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline:
                    if client.get("/api/status").json()["connection"]["serial"]:
                        break
                    time.sleep(0.02)
                self.assertTrue(client.get("/api/status").json()["connection"]["serial"])
                os.write(master, json.dumps(telemetry()).encode() + b"\n")
                deadline = time.monotonic() + 2
                while time.monotonic() < deadline:
                    status = client.get("/api/status").json()
                    if status["connection"]["bluetooth"]:
                        break
                    time.sleep(0.02)
                self.assertTrue(status["connection"]["bluetooth"])
                response = client.post("/api/control", json={"action": "disarm"})
                self.assertEqual(response.status_code, 202)
                command_id = response.json()["id"]
                self.assertTrue(client.get("/api/status").json()["telemetry"]["armed"])
                readable, _, _ = select.select([master], [], [], 2)
                self.assertTrue(readable)
                wire = json.loads(os.read(master, 4096).split(b"\n")[0])
                self.assertEqual(wire, {"type": "command", "id": command_id, "action": "disarm"})
                ack = {"type": "command_ack", "id": command_id, "ok": True, "armed": False, "muted_ms": 0}
                os.write(master, json.dumps(ack).encode() + b"\n")
                deadline = time.monotonic() + 2
                while time.monotonic() < deadline:
                    result = client.get(f"/api/control/{command_id}").json()
                    if result["status"] == "confirmed":
                        break
                    time.sleep(0.02)
                self.assertEqual(result["status"], "confirmed")
                self.assertFalse(client.get("/api/status").json()["telemetry"]["armed"])
                os.close(master)
                master = None
                deadline = time.monotonic() + 2
                while time.monotonic() < deadline:
                    if not client.get("/api/status").json()["connection"]["serial"]:
                        break
                    time.sleep(0.02)
                self.assertFalse(client.get("/api/status").json()["connection"]["serial"])
        finally:
            if master is not None:
                os.close(master)
            os.close(slave)


@unittest.skipUnless(HAVE_API_DEPS, "Install server/requirements-test.txt for archive download test")
class DownloadTests(unittest.TestCase):
    def test_extracted_project_can_download_source_without_private_runtime_files(self):
        from io import BytesIO
        import shutil
        from zipfile import ZipFile
        from fastapi.testclient import TestClient
        import app

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for relative in app.PROJECT_FILES:
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(app.PROJECT_ROOT / relative, target)
            # These files must never enter a generated download.
            for relative in (".env", ".git/config", ".openai/hosting.json", "personal-notes.txt"):
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("private runtime fixture")
            config = app.Settings(database=root / "server/data/auraguard.sqlite3", static_dir=root / "dist")
            with patch.object(app, "PROJECT_ROOT", root):
                with TestClient(app.create_app(config)) as client:
                    response = client.get("/downloads/auraguard-project.zip")
                    self.assertEqual(response.status_code, 200)
                    self.assertIn("attachment", response.headers["content-disposition"])
                    self.assertTrue((root / "server/data/auraguard.sqlite3").is_file())
                    with ZipFile(BytesIO(response.content)) as archive:
                        names = set(archive.namelist())
                    self.assertEqual(names, set(app.PROJECT_FILES))
                    self.assertIn("dist/app.js", names)
                    self.assertIn("server/app.py", names)
                    self.assertIn("firmware/base_station/base_station.ino", names)
                    self.assertIn("firmware/wearable/wearable.ino", names)
                    self.assertFalse(any("sqlite" in name or "/data/" in name for name in names))
                    self.assertNotIn(".env", names)
                    self.assertNotIn("personal-notes.txt", names)


if __name__ == "__main__":
    unittest.main()
