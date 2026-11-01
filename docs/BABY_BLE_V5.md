# Supplied baby BLE v5 firmware

This document describes the implementation in [esp32_baby_unit_ble_v5.ino](../firmware/esp32_baby_unit_ble_v5/esp32_baby_unit_ble_v5.ino). The file is copied unchanged from the supplied upload. Its matching room receiver is now included as [uno_room_receiver_cry.ino](../firmware/uno_room_receiver_cry/uno_room_receiver_cry.ino); the live gateway reads that receiver's USB logs with `--protocol uno-room-v1` at 9600 baud. The baby sketch has not been compiled for an ESP32 board, flashed, or tested on hardware here. Comments about previous trials and module behavior are the sketch author's notes; static inspection does not independently verify them.

## Bluetooth roles and route

The ESP32 uses `BLEDevice.h`. It actively scans, matches the configured target address or advertised name `HC-05`, creates a BLE client, and connects to the remote GATT service `0xFFE0`. It writes to characteristic `0xFFE1` with response and registers for notifications if that characteristic supports them. `0xFFE2` is not used.

The ESP32 is the central/client, and the room module is the peripheral/server. The code does not create a GATT server on the ESP32, so direct browser connection to this baby device would require a firmware/topology change. [Espressif's BLE documentation](https://docs.espressif.com/projects/arduino-esp32/en/latest/api/ble.html) describes its BLE library and client/server examples.

The name `HC-05` is a scan filter, not proof of the module model. ITead's [HC-05 datasheet, mirrored by Sigma Electrónica](https://www.sigmaelectronica.net/manuals/istd016A.pdf), describes a Bluetooth Classic SPP module. This sketch instead requires a BLE GATT peripheral exposing `FFE0`/`FFE1`. The advertised name alone does not identify the physical module. The supplied receiver code establishes a 9600-baud UART interface, but does not query or identify the module's radio model.

The header says the module accepts one central at a time. That is a stated module constraint, not a property verified by the code. Do not design the web app around a second simultaneous BLE client without checking the actual receiver.

## Messages that cross the BLE connection

Each outgoing message is ASCII with a final LF byte (`\n`):

| Direction | Message | Implementation |
| --- | --- | --- |
| Baby → room | `OK\n` | Nominal heartbeat every 1 second while the BLE link is up. |
| Baby → room | `FALL\n` | One possible-fall report from detection, sensor-fault fallback, or BOOT-button hardware test. |
| Baby → room | `CRY\n` | Repeated every 1 second while the internal sound-alert state is active and linked. |
| Room → baby | Notification text ending in `\n` | Accumulated and printed to baby USB Serial. The comment mentions `ACK`, but the code does not interpret it or perform an action. |

There is no clear, cry-ended, arm, disarm, mute-state, timestamp, sequence-number, or numeric telemetry message. `OK` continues while a sound alert is active and while the accelerometer may be unavailable. It only demonstrates that a heartbeat reached the receiver.

`sendLine()` asks for a GATT write response, but the protocol has no correlated application acknowledgment that the room unit processed a fall or changed its alarm. `sendFall()` does not retry the event if sending fails. An event's meaning must not be expanded beyond the text the receiver received.

## Sensors and data that remain on the baby ESP32

| Item | Code behavior | Available over BLE? |
| --- | --- | --- |
| MPU6050 acceleration | Reads XYZ acceleration, scales from its configuration, and computes vector magnitude. SDA is GPIO21; SCL is GPIO22. | No numeric values. |
| Gyroscope | The MPU6050 has gyroscope registers, but this sketch does not read them. | No. |
| Orientation | No orientation-change stage is implemented. | No. |
| Analog sound | Samples GPIO34; computes peak-to-peak ADC swing in 50 ms windows. | Only `CRY` reports. |
| Battery | No battery measurement is implemented. | No. |
| MPU health / I²C faults | Local checks and diagnostic fault counts. | No. |
| BLE scan RSSI | Printed during discovery. | No periodic receiver telemetry. |

Every 2 seconds, the baby USB Serial output prints link state, MPU status, acceleration magnitude, peak magnitude, I²C faults, received-notification bytes, sound swing, and cry state. This diagnostic output uses 115200 baud and belongs to the baby ESP32's USB port. It is not the room/Uno USB stream that the web server needs.

## Fall logic as implemented

The trigger is acceleration magnitude above **1.8 g**, or below **0.5 g for two consecutive samples**. The main loop attempts acceleration reads at intervals of at least 5 ms, subject to other work. This is a nominal sampling schedule, not a measured end-to-end timing guarantee.

After a trigger, the detector waits for stillness:

1. It ignores the first **600 ms** after `watchStart`.
2. It collects acceleration minimum and maximum until **1,800 ms** after `watchStart`.
3. It sends `FALL` when the collected range is below **0.35 g** and the final magnitude differs from 1 g by less than **0.3 g**.

The nominal collected window is therefore about **1.2 seconds** (600–1,800 ms). A new impact can restart this interval during the first 3 seconds after the original trigger. The algorithm uses acceleration magnitude; it does not require orientation change or two continuous seconds of stillness.

A pending candidate survives an MPU fault. Recovery restarts its stillness window and tries a bus reset before full sensor initialization when possible. With `ALERT_ON_SENSOR_LOSS = true`, a candidate older than **5,500 ms** can emit `FALL` if a sensor fault occurred, even though stillness could not be confirmed. A normal sent event starts a 5-second detector cooldown.

The BOOT button also invokes `sendFall()`. The detailed reason is printed to baby USB Serial, but the room unit receives the same `FALL` text for the button, the detector, and the fault fallback. The dashboard must label it as a reported possible fall without claiming which path produced it.

## Sound logic as implemented

The ESP32 reads the sound sensor itself. Peak-to-peak ADC swing above **400 counts** in a **50 ms window** is considered loud. Roughly **1.5 seconds** of loud activity activates the internal sound state, with gaps of up to about 300 ms tolerated by the threshold logic. The internal state clears after its quiet-time condition is met.

While that state is active, the ESP32 writes `CRY` once per second. `[CRY] detected` and `[CRY] ended` are local diagnostic lines only. No end message is sent over BLE, and `OK` is not an end message. A missing recent `CRY` report can be described as no recent report; it cannot establish silence, a resolved incident, or a healthy sensor. ADC swing is not a calibrated decibel measurement or a trained cry classification.

## The supplied room receiver

The included Uno receiver uses `Serial.begin(9600)` and `BT.begin(9600)`. With `LOCAL_MIC = false`, sound reports come from the ESP32. The Uno consumes baby `OK`/`FALL`/`CRY` messages and prints status or event logs; it does not forward the raw heartbeat stream. The dashboard reads those logs through `uno-room-v1`. See [LAB_SETUP.md](LAB_SETUP.md) for the startup command and [PROTOCOL.md](PROTOCOL.md) for exact log formats.

The receiver establishes the physical controls:

- ACK clears its fall flag, starts a 15-second mute timer, sends `ACK` to the baby, and prints an acknowledgment log. The baby still only prints the incoming notification.
- ARM toggles armed state and clears fall, sound, and link-loss flags. It leaves an existing mute timer unchanged.
- The receiver clears its sound flag after more than 2.5 seconds without another `CRY` report. This is a receiver timeout; the baby sends no explicit cry-ended payload.
- While armed and after seeing at least one message, the receiver reports link loss after more than 6 seconds without a Bluetooth line.

The Uno never reads USB `Serial` input, so the gateway cannot issue web arm/disarm or mute commands. Its status line omits fall and mute; attaching mid-session cannot recover those values until relevant explicit logs arrive. Neither board sends numeric sensor telemetry through the room USB output.

Close Arduino IDE Serial Monitor or any Arduino CLI monitor using the room port before starting the gateway:

```bash
python server/app.py --port COM4 --baud 9600 --protocol uno-room-v1
```

Both supplied sketches are preserved unchanged. Their integration contract is established from code, while board compilation, flashing, and physical validation remain separate lab work.

## Source locations

These references identify the unchanged supplied file:

| Implementation | Lines |
| --- | --- |
| Target, service, characteristic, sensor pins, timing constants | 34–49 |
| Notification accumulation / logging | 79–89, 335 |
| BLE scan and connection | 98–151 |
| GATT write | 153–158 |
| Acceleration magnitude | 194–202 |
| MPU recovery | 207–228 |
| `FALL` emission | 230–234 |
| Fall candidate / stillness logic / watchdog | 252–291 |
| Sound threshold / repeated `CRY` | 294–314 |
| USB Serial initialization | 316–325 |
| BOOT button and main sampling | 327–365 |
| `OK` heartbeat and local diagnostic status | 367–374 |
