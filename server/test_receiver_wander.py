"""Gateway parsing of the AI room receiver's wander log lines.

The AI baby unit sends WANDER after 8+ seconds at the Bluetooth range limit;
the AI receiver (firmware/uno_room_receiver_ai) logs it. These tests pin the
gateway's interpretation of those two lines against the uno-room-v1 protocol.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest

from server.state import Clock, Monitor, Store


class TestClock(Clock):
    def __init__(self):
        self.value = 100.0

    def monotonic(self):
        return self.value

    def now(self):
        return datetime(2026, 11, 1, tzinfo=timezone.utc) + timedelta(seconds=self.value)

    def advance(self, seconds):
        self.value += seconds


STATUS = "status | armed=1 baby=linked lastMsg=0s ago mic=remote cry=0"


def fresh_monitor():
    clock = TestClock()
    monitor = Monitor(Store(":memory:"), protocol="uno-room-v1", clock=clock)
    monitor.set_serial(True)
    assert monitor.ingest_line(STATUS)
    return monitor, clock


class WanderLineTests(unittest.TestCase):
    def test_wander_line_sets_flag_and_event(self):
        monitor, _ = fresh_monitor()
        self.assertTrue(monitor.ingest_line("!!! WANDER - baby near Bluetooth range limit !!!"))
        snap = monitor.snapshot()
        self.assertTrue(snap["receiver"]["wander_active"])
        self.assertEqual(snap["receiver"]["counters"]["wander_reports"], 1)
        event = snap["events"][0]
        self.assertEqual(event["title"], "Baby near Bluetooth range limit")
        self.assertEqual(event["severity"], "warning")

    def test_wander_cleared(self):
        monitor, _ = fresh_monitor()
        monitor.ingest_line("!!! WANDER - baby near Bluetooth range limit !!!")
        self.assertTrue(monitor.ingest_line("wander cleared"))
        snap = monitor.snapshot()
        self.assertFalse(snap["receiver"]["wander_active"])

    def test_wander_counts_as_baby_activity(self):
        monitor, clock = fresh_monitor()
        clock.advance(4)
        monitor.ingest_line("!!! WANDER - baby near Bluetooth range limit !!!")
        self.assertEqual(monitor.snapshot()["connection"]["status"], "connected")

    def test_arm_resets_wander(self):
        monitor, _ = fresh_monitor()
        monitor.ingest_line("!!! WANDER - baby near Bluetooth range limit !!!")
        monitor.ingest_line("DISARMED")
        self.assertFalse(monitor.snapshot()["receiver"]["wander_active"])

    def test_old_receiver_lines_still_reject_garbage(self):
        monitor, _ = fresh_monitor()
        self.assertFalse(monitor.ingest_line("!!! WANDER but not quite the right text !!!"))


if __name__ == "__main__":
    unittest.main()
