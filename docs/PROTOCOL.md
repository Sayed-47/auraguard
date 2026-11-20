# AuraGuard communication protocols

The final lab dashboard reads the supplied Uno receiver's USB logs using **`uno-room-v1` at 9600 baud**. The gateway parses these logs directly; neither supplied sketch needs a forwarding patch. All server operation is live hardware input.

The `baby-ble-v5` raw-line and `json-v1` profiles remain explicit API/reference integrations. The final dashboard asks for `uno-room-v1` when connected to either advanced profile.

## Supplied Uno USB logs: `uno-room-v1`

Source: [uno_room_receiver_cry.ino](../firmware/uno_room_receiver_cry/uno_room_receiver_cry.ino), with `LOCAL_MIC = false`. Both its USB Serial and module UART are 9600 baud. USB output is newline-delimited text; the receiver's trailing carriage returns are accepted.

### Periodic status

Approximately every 2 seconds the receiver emits:

```text
status | armed=1 baby=linked lastMsg=0s ago mic=remote cry=0
```

| Field | Values | Evidence |
| --- | --- | --- |
| `armed` | `0` or `1` | Current receiver armed flag. |
| `baby` | `waiting`, `linked`, or `LOST` | Receiver's seen/link-loss flags. |
| `lastMsg` | Nonnegative whole seconds, followed by `s ago` | Receiver's elapsed timer, rounded down to seconds. |
| `mic` | `remote` in the supplied configuration | Sound reports come from the baby ESP32. |
| `cry` | `0` or `1` | Current receiver sound-alert flag. |

This line does not contain `fallActive`, `mutedUntil`, raw sensor measurements, an exact heartbeat count, or a baby-device timestamp. A live status cannot fill in those missing fields.

### Event and startup lines

| Exact line | Code behavior |
| --- | --- |
| `Room unit ready. Cry detection comes from the baby unit (CRY messages).` | Receiver startup. Initial state is armed; fall, cry, link-loss, and mute are reset; no baby message has yet been seen. |
| `Baby unit LINKED (first message received)` | First nonempty Bluetooth line reached the receiver. |
| `Link restored` | A Bluetooth line arrived while the receiver's link-loss flag was set. |
| `!!! FALL ALERT from baby unit !!!` | Sets the receiver fall flag. The baby reason is not included. |
| `CRY reported by baby unit` | Starts the receiver sound flag while armed. Repeated `CRY` messages normally do not print this line again. |
| `cry ended` | Clears the receiver sound flag after more than 2.5 seconds without another `CRY` report. |
| `!!! LINK LOST - no signal from baby unit !!!` | Sets link loss after more than 6 seconds without a Bluetooth line, only while armed and after a message has been seen. |
| `ACKNOWLEDGED (sent ACK to baby unit)` | Physical ACK cleared fall, started 15 seconds of muting, and wrote `ACK` toward the baby. |
| `ARMED` | Physical ARM toggle enabled alarms and cleared fall, cry, and link-loss flags. |
| `DISARMED` | Physical ARM toggle disabled alarms and cleared fall, cry, and link-loss flags. |
| `!!! WANDER - baby near Bluetooth range limit !!!` | AI receiver variant only: starts the receiver wander flag while armed. The AI baby unit sends `WANDER` after 8+ seconds at the Bluetooth range limit. |
| `wander cleared` | AI receiver variant only: clears the wander flag after more than 5 seconds without another `WANDER` report. |

The receiver may also print `unknown msg: <text>`. It updates its own message timer before validating the Bluetooth line, so that log is not evidence of an `OK` heartbeat or a known sensor event.

### State rules

ACK leaves the receiver's cry and link-loss flags unchanged. ARM leaves the mute timer unchanged. A `FALL` message can set the fall flag even while disarmed, though alarm outputs remain off while disarmed. `CRY` messages are ignored while disarmed.

The Uno resets `lastBabyMsg` when ARM is toggled, even without a baby transmission. It also updates that timer for unknown nonempty Bluetooth messages. Consequently, `baby=linked` alone is not proof of a fresh, recognized heartbeat. The gateway keeps room USB freshness separate from baby-link evidence and does not advance the baby clock on arbitrary room events.

If the gateway attaches mid-session, it cannot reconstruct the fall flag or mute timer from periodic status. Fall remains unknown until an observed startup, ARM, ACK, or fall event establishes it. A mute countdown is based only on an observed ACK; it is not inferred from LEDs, `cry=0`, a fresh serial connection, or later status.

`FALL` is a report from the baby algorithm or test path. The ESP32 uses the same payload for detector output, a trigger followed by sensor fault, and the BOOT hardware test. The dashboard cannot identify a confirmed accident from that line. `cry ended` establishes a cleared receiver flag after reports stopped, not a measured quiet room.

### Hardware controls

The supplied Uno never reads from USB `Serial`. The gateway therefore has no supported PC-to-room arm, disarm, or mute command. Physical ACK is pin 9 and physical ARM is pin 10. The browser displays observed actions without writing control bytes to the receiver.

## Normalized receiver snapshot

This excerpt shows the receiver-specific portion of a `uno-room-v1` snapshot. Times use the gateway UTC clock; status and event timestamps record log receipt:

```json
{
  "protocol": "uno-room-v1",
  "capabilities": {
    "numeric_telemetry": false,
    "hardware_controls": false
  },
  "receiver": {
    "fresh": true,
    "status": "connected",
    "armed": true,
    "fall_active": null,
    "cry_active": false,
    "wander_active": false,
    "link_lost": false,
    "muted_until": null,
    "mute_known": false,
    "last_status_at": "2026-11-01T15:30:00.000Z",
    "last_line": "status | armed=1 baby=linked lastMsg=0s ago mic=remote cry=0",
    "counters": {
      "fall_reports": 0,
      "cry_episodes": 0,
      "acknowledgments": 0,
      "wander_reports": 0
    },
    "session_started_at": "2026-11-01T15:29:55.000Z",
    "status_fresh": true
  }
}
```

This example is a gateway that attached after receiver startup: armed and cry are known from status, while fall and mute remain unknown. `receiver.status` is `waiting`, `connected`, `stale`, or `offline`. A recognized room log received within 5 seconds can establish room freshness; `status_fresh` separately requires recent periodic status. A stale or disconnected receiver has unavailable current flags, even when old events remain in history.

Baby-link age has its own 6-second limit and uses the receiver's reported age plus elapsed gateway time. Room status is not a synthetic baby heartbeat. ARM/unknown-message timing effects invalidate artificial age evidence until later receiver status demonstrates newer activity. First-link/restoration text alone does not identify which baby token arrived.

Receiver counters describe observed reports/actions since the gateway started. They cannot recover exact ESP32 `OK` or `CRY` packet totals, and missed pre-connection events cannot be recreated. `muted_until` is an estimated gateway UTC end time derived from the received ACK log; it is not the Uno's internal `millis()` value.

## Browser API and storage

The local web page and API share an origin. At `http://127.0.0.1:8000`, the socket is `ws://127.0.0.1:8000/ws`. Browser WebSocket and control-origin checks remain enforced.

| Method and path | Response |
| --- | --- |
| `GET /api/status` | Current normalized snapshot and protocol/capabilities. |
| `GET /api/events?limit=100` | Observed events, newest first; limit 1–2000. |
| `WS /ws` | Current snapshot approximately once per second. |
| `GET /healthz` | Gateway process health, independent of baby connectivity. |
| `GET /api/history?limit=120` | Retained numeric history for a compatible reference integration. The supplied Uno has no numeric sensor stream. |
| `GET /api/export.csv?limit=86400` | Retained history export. |
| `POST /api/control` | Reference integrations only; unsupported for the supplied Uno. |
| `GET /api/control/{id}` | Reference control result for the current server session. |

Events use gateway receipt timestamps. A snapshot timestamp is not the time a physical incident occurred and must not substitute for receiver or baby-link freshness. Browser socket freshness must also be tracked independently.

The default live database is `server/data/auraguard-uno-room-v1-live.sqlite3`. Explicit profiles use their own live files. `--db` overrides the path; use separate files for different inputs. Event retention is 2000 rows. Compatible numeric reference integrations retain approximately 86,400 samples; no readings are fabricated for the supplied Uno. No simulator is started when hardware is absent or disconnects.

Run one server worker. Close any Arduino IDE/CLI serial monitor before the gateway opens the Uno port.

## AI baby unit (`esp32_baby_unit_ai` + `uno_room_receiver_ai`)

The AI firmware pair keeps the `uno-room-v1` log grammar above and adds the
two wander lines in the event table. The baby unit's Bluetooth messages are
`OK\n`, `FALL\n`, `CRY\n` (same meanings as v5, now produced by on-device
classifiers) plus `WANDER\n` every 2 seconds while the baby has sat at the
Bluetooth range limit for 8+ seconds. The supplied receiver prints
`unknown msg: WANDER`; the AI receiver variant prints the wander lines.
See [AI.md](AI.md) for the classifiers, training, and verification.

## Appendix A: raw baby BLE lines (`baby-ble-v5`)

This API/reference profile requires a separate adapter that forwards exact baby UART lines. It is **not** the supplied Uno's USB format, and it is not the final dashboard profile.

The baby writes `OK\n`, `FALL\n`, and `CRY\n` to BLE service `FFE0`, characteristic `FFE1`. `OK` is nominally sent once per second; active `CRY` reports repeat about once per second. There is no baby-level clear message, numeric telemetry, or command confirmation. Details are in [BABY_BLE_V5.md](BABY_BLE_V5.md).

The old profile's `messages` object records last received token, receive/heartbeat/fall/cry times, and counts of recognized raw lines. These fields apply only when those raw lines actually reach the gateway. They must not be inferred from the supplied Uno's status logs.

## Appendix B: legacy `json-v1` serial telemetry

Use UTF-8 JSON objects separated by a newline (`\n`). The legacy reference Uno uses 115200 baud, 8 data bits, no parity, and 1 stop bit. A trailing carriage return is accepted. Send a full telemetry packet at least once per second and after significant state changes.

One complete packet, shown on multiple lines for readability:

```json
{
  "type": "telemetry",
  "seq": 42,
  "uptime_ms": 42000,
  "ax": 0.010,
  "ay": -0.020,
  "az": 1.000,
  "gx": 0.3,
  "gy": -0.4,
  "gz": 0.0,
  "sound_level": 12,
  "state": "normal",
  "fall_stage": "monitoring",
  "armed": true,
  "muted_ms": 0,
  "bt_connected": true,
  "wearable_age_ms": 20,
  "battery_pct": null
}
```

On the wire, send the object on a **single line**, followed by `\n`.

| Field | Type / units | Meaning |
| --- | --- | --- |
| `type` | String | `telemetry`; omission also selects telemetry. |
| `seq` | Nonnegative integer | Base-station sequence number. It may reset when the base reboots. |
| `uptime_ms` | Nonnegative integer | Base uptime in milliseconds; never interpreted as a date. |
| `ax`, `ay`, `az` | Number or `null`, g | Acceleration including gravity. Server validation accepts −64 to +64 g. |
| `gx`, `gy`, `gz` | Number or `null`, degrees/s | Angular velocity. Server validation accepts −4000 to +4000 degrees/s. |
| `sound_level` | Number or `null`, 0–100 | Relative microphone amplitude, not dB. |
| `state` | String | `normal`, `cry`, `fall`, or `offline`. |
| `fall_stage` | String | `monitoring`, `impact`, `orientation`, `stillness`, or `confirmed`. |
| `armed` | Boolean or `null` | Confirmed base-station alarm state. `null` means unknown. |
| `muted_ms` | Number or `null`, 0–15000 | Remaining buzzer-silence duration. Zero means no active silence. |
| `bt_connected` | Boolean or `null` | Base's evidence that the wearable link has fresh packets. |
| `wearable_age_ms` | Nonnegative integer or `null` | Time since the base last received a valid wearable packet. |
| `battery_pct` | Number or `null`, 0–100 | Measured battery percentage, if implemented. |

The server accepts numeric fields only when finite and within range. A boolean is not accepted as a number. Integer counters can be at most `2^53 − 1`. It accepts the state aliases `OK`/`ok`, `crying`, and `lost`, normalizing them to `normal`, `cry`, and `offline`.

The parser accepts partial telemetry for custom integrations, but the legacy reference firmware sends every field. Send explicit `null` for an unavailable sensor; omission may retain its earlier value. Before declaring a new reading, preserve the distinction between a fresh base packet and a fresh wearable packet. A base can continue reporting room sound while Bluetooth is disconnected.

### Missing data and failure states

- Before the first wearable packet, send `bt_connected:false`, `wearable_age_ms:null`, and null motion values.
- After the link fails, send `bt_connected:false`, increasing `wearable_age_ms`, and null motion values.
- If Bluetooth frames arrive but the IMU is unavailable, `bt_connected` may remain `true` while `state` is `offline` and motion values are null.
- The reference firmware always sends `battery_pct:null`; it has no battery-measurement circuit.
- `armed:false` means alarm outputs are disarmed. It does not mean the connection or sensors are unavailable.

The Python framer retains incomplete reads until a newline arrives. It caps each input line at 4096 bytes and discards an oversized frame through its next newline. Malformed JSON, unknown packet types, and invalid field values increment diagnostics and do not count as valid telemetry.

### Reference sound measurement

The Uno uses a nominal 25 ms peak-to-peak ADC window:

```text
sound_level = 100 × (maximum ADC sample − minimum ADC sample) / 1023
```

The reference threshold is 65, sustained for 1.5 seconds. This is an adjustable bench parameter. It does not establish sound pressure in dB or distinguish crying from other sustained sound. Full calibration details are in [the firmware guide](../firmware/README.md).

### Legacy `json-v1` API controls

Controls use the same newline-delimited JSON framing in the reverse direction:

```json
{"type":"command","id":"cmd-123abc","action":"acknowledge","seconds":15}
```

Allowed actions:

| `action` | Requested behavior |
| --- | --- |
| `arm` | Enable monitoring alarms at the base. |
| `disarm` | Disable monitoring alarms at the base. |
| `acknowledge` | Silence the buzzer for 15 seconds. |

`id` must contain 1–64 ASCII letters, digits, hyphens, or underscores. The reference Uno accepts `seconds` only for `acknowledge`, with the value `15`; the server includes it automatically. It rejects duplicate keys and unsupported fields in a command.

A successful hardware acknowledgment includes the same ID and actual resulting state:

```json
{"type":"command_ack","id":"cmd-123abc","ok":true,"armed":true,"muted_ms":15000}
```

The server also accepts `request_id` as an acknowledgment-ID alias. `ok:false` rejects the pending command. An `ok:true` acknowledgment must include evidence of the requested state: `armed:true` for arm, `armed:false` for disarm, or positive `muted_ms` for acknowledge.

Only one command can be pending at a time. The server waits up to 5 seconds for a matching acknowledgment or a fresh telemetry packet with the requested state. Unsolicited or late acknowledgments do not modify confirmed state. A dropped serial link fails a pending command. A timeout does not cause the dashboard to assume success.

The reference Uno acknowledges an immediately repeated command ID without applying its action again. Invalid commands receive no acknowledgment. Acknowledge preserves the visible fall latch; an arm/disarm transition resets the reference detector. The browser never treats acknowledgment as evidence that the infant is safe.

### Legacy normalized snapshot example

```json
{
  "type": "snapshot",
  "timestamp": "2026-11-01T15:30:00.000Z",
  "mode": "live",
  "connection": {
    "server": true,
    "serial": true,
    "bluetooth": true,
    "status": "connected",
    "last_seen": "2026-11-01T15:29:59.980Z",
    "base_last_seen": "2026-11-01T15:30:00.000Z",
    "wearable_age_ms": 20,
    "transport": "Bluetooth Classic · SPP",
    "port": "COM4"
  },
  "device": {
    "id": "AG-01",
    "name": "Nursery wearable",
    "battery_pct": null
  },
  "telemetry": {
    "accel": {"x": 0.01, "y": -0.02, "z": 1.0},
    "gyro": {"x": 0.3, "y": -0.4, "z": 0.0},
    "sound_level": 12,
    "motion": "still",
    "fall_stage": "monitoring",
    "state": "normal",
    "armed": true,
    "muted_until": null
  },
  "history": [
    {"timestamp":"2026-11-01T15:30:00.000Z","acceleration":1.00025,"sound_level":12}
  ],
  "events": [],
  "pending_controls": [],
  "last_control": null,
  "diagnostics": {"invalid_packets":0,"last_error":null}
}
```

`timestamp` is the server's snapshot time. It must not substitute for `last_seen`: a server can send fresh snapshots while the wearable remains offline. The browser must also track its own WebSocket freshness, since no server field can report a message that never arrived.

`connection.status` is `waiting`, `connected`, `stale`, or `offline`. For `json-v1`, the server combines elapsed time since a valid base packet with the base-reported wearable age. At 3 seconds it removes fresh-motion status; at 5 seconds it reports offline. A negative base link report takes effect immediately. Fresh sound remains available while the base is responsive even when wearable motion is unavailable.

In `json-v1`, `motion` is `still`, `gentle`, `active`, or `unknown`. It is a dashboard summary, separate from the wearable's fall detector. The server uses acceleration-magnitude deviation from 1 g and angular velocity to produce this label. It is not a sleep or safety classifier.

`muted_until` is a server UTC ISO timestamp or `null`; display the countdown using the current time. Retained history uses acceleration magnitude `sqrt(ax² + ay² + az²)`, not an individual axis. Missing values remain null so charts can show a gap.

### Legacy `json-v1` event example

```json
{
  "id": "evt-example",
  "type": "cry",
  "severity": "warning",
  "title": "Sustained sound detected",
  "detail": "The base station reported sound above its configured threshold for 1.5 seconds.",
  "timestamp": "2026-11-01T15:30:00.000Z",
  "acknowledged": false
}
```

Event types are `fall`, `cry`, `connection`, and `system`; severity is `critical`, `warning`, or `info`. In `json-v1`, a confirmed acknowledge command marks existing unacknowledged records acknowledged and adds its own system event. This is an operator action log, not proof that the underlying condition has resolved.

### Legacy wearable Bluetooth frames

The optional reference firmware uses a smaller CSV frame between the ESP32 and Uno to limit UART bandwidth and Uno memory use:

```text
LS1,sequence,uptime_ms,imu_valid,ax_mg,ay_mg,az_mg,gx_tenths_dps,gy_tenths_dps,gz_tenths_dps,stage
```

`LS1` is a protocol identifier. Stage codes 0–4 map to monitoring, impact, orientation, stillness, and confirmed. The Uno converts this frame to the JSON contract above. The Python bridge does not parse this internal CSV. Details and the reverse `RESET` command are in [firmware/README.md](../firmware/README.md).
