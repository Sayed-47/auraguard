# Firmware

The lab uses the two supplied sketches below. Both are copied byte-for-byte from the uploads. The gateway reads the room sketch's existing logs; no firmware modification is required for this connection method.

| File | Role |
| --- | --- |
| [esp32_baby_unit_ble_v5.ino](esp32_baby_unit_ble_v5/esp32_baby_unit_ble_v5.ino) | Baby ESP32: MPU6050 acceleration and analog sound, BLE client. |
| [uno_room_receiver_cry.ino](uno_room_receiver_cry/uno_room_receiver_cry.ino) | Room Uno: receives baby messages, drives alarms, handles physical switches, prints USB logs. |

## Supplied configuration

The baby connects to the room BLE peripheral using service `FFE0` and characteristic `FFE1`. It writes `OK`, `FALL`, and `CRY`; it only logs received notification text. A configured name of `HC-05` does not identify the physical module's radio model.

The room sketch uses **9600 baud for both USB Serial and the Bluetooth-module UART**. The baby's USB diagnostics use 115200 baud. `LOCAL_MIC = false` means the supplied room code takes sound reports from the ESP32 rather than reading the Uno A0 microphone.

### Pins defined by the supplied code

| Connection | Pin / setting |
| --- | --- |
| MPU6050 SDA / SCL on baby ESP32 | GPIO21 / GPIO22 |
| Analog sound input on baby ESP32 | GPIO34 |
| ESP32 BOOT test button | GPIO0 |
| Room module TX → Uno RX | D2 |
| Uno TX → room module RX | D3, through the supplied setup's 1k/2.2k voltage divider |
| Room buzzer | D5 |
| Red / yellow / green LEDs | D6 / D7 / D8 |
| Physical ACK / ARM switches | D9 / D10 to ground, internal pull-ups |
| Uno microphone A0 | Unused with `LOCAL_MIC = false` |

These are code and supplied wiring definitions; verify that the assembled circuit matches them. The sketches have not been board-compiled or flashed in this environment.

## Receiver behavior

ACK clears `fallActive`, sets a 15-second mute timer, sends `ACK` over the module UART, and logs the action to USB. It does not clear `cryActive` or `linkLost`. ARM toggles armed state and clears fall, sound, and link-loss flags; it leaves the mute timer unchanged.

The Uno prints status approximately every 2 seconds. It clears the sound flag after more than 2.5 seconds without a `CRY` report, and checks link loss after more than 6 seconds without a Bluetooth line while armed and after a message has been seen. Status omits fall and mute, so the gateway keeps those values unknown if it misses the logs that establish them.

The receiver does not read USB `Serial` input. Use the physical controls; this firmware has no supported web-command path.

```bash
python server/app.py --port COM4 --baud 9600 --protocol uno-room-v1
```

Replace the port with the room Uno's USB device and close any serial monitor first. See [the lab guide](../docs/LAB_SETUP.md), [exact protocol](../docs/PROTOCOL.md), and [baby detector analysis](../docs/BABY_BLE_V5.md).

## Optional legacy reference: `json-v1`

**Everything below describes the generated Classic SPP / CSV / JSON reference, not the supplied BLE v5 sketch.** Run the matching server with `--protocol json-v1`. Replacing either half with the supplied BLE sketch will not produce this protocol. These files are retained for API/reference integrations. The final lab dashboard expects `uno-room-v1`, and the supplied firmware pair is the lab target.

These sketches add the telemetry protocol used by the AuraGuard dashboard to the hardware described in the SRS. The existing project's firmware can instead emit the same serial JSON; replacing its detection logic is not required.

**This is a bench prototype.** The thresholds below are examples, not a validated infant fall detector or a trained cry classifier. Use a test fixture for calibration. The SRS explicitly says the breadboard wearable must not be attached to a real baby. Physical testing and board compilation remain required before use.

### Data path

ESP32 + MPU6050 → Bluetooth Classic SPP → HC-05 + Arduino Uno → USB serial → Python server → local browser.

The original ESP32's built-in radio handles Bluetooth, so the wearable does not need a separate HC-05. The HC-05 is on the room/base station. If your server receives a paired Bluetooth COM port directly instead, your firmware must send the **base USB JSON protocol**, not the compact wearable CSV protocol.

The code targets **Arduino-ESP32 3.x** with Classic SPP enabled and an **Arduino Uno**. ESP32-C3/S3 do not implement Classic SPP. Espressif's current `BluetoothSerial` source also marks default support as deprecated for its future 4.0 core, so do not assume an arbitrary later core is compatible. [Espressif Bluetooth documentation](https://docs.espressif.com/projects/arduino-esp32/en/latest/api/bluetooth.html), [chip support matrix](https://docs.espressif.com/projects/arduino-esp32/en/latest/libraries.html), [BluetoothSerial header](https://github.com/espressif/arduino-esp32/blob/master/libraries/BluetoothSerial/src/BluetoothSerial.h).

### Files and dependencies

| Sketch | Board | Dependencies |
| --- | --- | --- |
| `wearable/wearable.ino` | Original ESP32 development board | `Wire`, `BluetoothSerial`, ESP32 core; accompanying `fall_detector.h` |
| `base_station/base_station.ino` | Arduino Uno | Arduino AVR core, built-in `SoftwareSerial`; accompanying `protocol.h` |

Open each `.ino` from its existing folder in Arduino IDE. No third-party IMU or JSON libraries are needed. The Uno uses fixed-size input buffers and flash-resident output strings instead of allocating a JSON document or Arduino `String` objects. Confirm the actual SRAM report after compiling for your board.

### Wiring used by the sketches

| Connection | Pin |
| --- | --- |
| MPU6050 SDA → ESP32 | GPIO 21 |
| MPU6050 SCL → ESP32 | GPIO 22 |
| MPU6050 address | `0x68`; change `MPU_ADDRESS` to `0x69` if AD0 is high |
| HC-05 TX → Uno RX | D2 |
| Uno TX → HC-05 RX | D3 **through the existing 5 V → 3.3 V level divider** |
| Analog microphone output → Uno | A0 |
| Active buzzer control | D5 |
| Green / yellow / red LEDs | D6 / D7 / D8, each with its series resistor |
| Acknowledge button | D9 to ground, internal pull-up enabled |
| Arm/disarm button | D10 to ground, internal pull-up enabled |

Use common grounds and verify your sensor/module supply ratings. A buzzer that exceeds the Uno output pin's current rating needs a transistor driver; D5 is a control signal. For initial bench testing, use appropriate USB supplies. These sketches do not validate or replace the SRS battery/regulator circuit.

### Pairing and upload

1. Upload the wearable sketch. Its USB Serial Monitor at **115200 baud** prints the ESP32 **Bluetooth MAC**.
2. In the HC-05's documented AT configuration mode, set it to **master**, bind it to that Bluetooth MAC, and match its PIN to `BT_PIN` (the example is `1234`). Configure its **data-mode UART to 9600 baud, 8N1**. AT commands and AT-mode baud rates vary across HC-05 firmware; use the module's own command reference. The Uno sketch does not automatically reconfigure the HC-05.
3. Return the HC-05 to data mode. Upload the Uno base sketch. Its USB port uses **115200 baud**; its D2/D3 HC-05 port uses **9600 baud**.
4. Verify newline-delimited JSON in the Uno USB Serial Monitor, then close Serial Monitor so the Python bridge can open the port.
5. Run the Python bridge against the **Uno USB COM/tty port**, not the ESP32 programming port. For this legacy pair only, use `python server/app.py --port COM4 --baud 115200 --protocol json-v1`, replacing the port as needed. This is an API/reference integration, not the final lab dashboard profile.

The ESP32 runs as an SPP slave. The configured HC-05 master is responsible for reconnecting to the bound device. `disableSSP()` selects legacy PIN pairing for HC-05 compatibility; this is a legacy prototype link, not a claim of modern Bluetooth security. `setPin(pin, length)` is the Arduino-ESP32 3.x API. [Espressif implementation](https://github.com/espressif/arduino-esp32/blob/master/libraries/BluetoothSerial/src/BluetoothSerial.cpp).

### Motion and fall logic

The MPU6050 is sampled at **50 Hz**, with an acceleration range of ±8 g and a gyroscope range of ±500 °/s. Acceleration uses `4096 LSB/g`; angular velocity uses `65.5 LSB/(°/s)`. The device's internal temperature register is skipped; it is not a baby-temperature sensor. [TDK MPU6050 register map](https://invensense.tdk.com/wp-content/uploads/2015/02/MPU-6000-Register-Map1.pdf).

The example detector requires:

1. At least 25 relatively quiet samples to establish a pre-impact gravity direction.
2. Acceleration magnitude at least **2.8 g**.
3. At least **45° orientation change within 1 second**, measured when acceleration is close to 1 g.
4. **2 continuous seconds of stillness**, using acceleration magnitude within 0.12 g of 1 g and angular velocity magnitude below 8 °/s. Movement restarts the stillness timer.

An incomplete sequence expires after 5 seconds. A confirmed event remains latched until an arm/disarm transition resets it. Acknowledge only silences the buzzer for 15 seconds; it does not clear the visible fall indication. These parameters are in `fall_detector.h`. They are configurable implementation assumptions, except the SRS's 2-second stillness requirement. They need calibration for the actual sensor, placement, and test fixture; 50 Hz can miss short impacts.

The wearable sends 5 telemetry packets per second and sends immediately when its fall stage changes. This avoids waiting for the next 1-second browser telemetry update before the base can activate its hardware alarm. Actual end-to-end latency has not been measured.

### Sound and local alarms

The base measures peak-to-peak ADC amplitude over nominal 25 ms windows:

```text
sound_level = 100 × (window maximum ADC − window minimum ADC) / 1023
```

This is a **relative amplitude from 0 to 100, not dB**. `SOUND_THRESHOLD = 65` is a starting point. A warning requires the threshold to be exceeded continuously for **1.5 seconds**. Calibrate it for the microphone and room; ambient sound can trigger it. If your sound module provides a filtered envelope rather than a microphone waveform, adapt `updateSound()` to that sensor's output.

The base starts armed. Green means its monitoring checks currently report no event; yellow indicates sound warning or blinks when disarmed; red indicates a latched fall or unavailable wearable/IMU while armed. The active buzzer has distinct cadence for those events. Both the physical acknowledge button and a confirmed web command mute it for 15 seconds. Physical arm/disarm and acknowledge controls continue to work without a browser or Python server.

The reference uses debounced button polling rather than installing pin-change interrupts that could conflict with `SoftwareSerial` on the Uno. This is an implementation difference from the SRS's interrupt-based requirement; verify the response time on hardware or adapt the interrupt handling in the existing firmware.

Link health is determined from fresh **wearable packets**, never from the base's own sound sampling. Three seconds without a valid wearable packet makes `bt_connected` false. If Bluetooth frames still arrive but the IMU fails, `bt_connected` stays true while motion values become `null` and state becomes `offline`.

### Protocol

#### Wearable → HC-05 / Uno

Each compact CSV frame ends in `\n`:

```text
LS1,sequence,uptime_ms,imu_valid,ax_mg,ay_mg,az_mg,gx_tenths_dps,gy_tenths_dps,gz_tenths_dps,stage
```

Stage codes are `0` monitoring, `1` impact, `2` orientation, `3` stillness, `4` confirmed. For example:

```text
LS1,42,8400,1,10,-20,1000,3,-4,0,0
```

The Uno discards malformed, oversized, out-of-range, or duplicate last frames. Its reverse control is the literal line `RESET\n`, sent on arm/disarm transitions. Bytes from an incomplete or oversized line are ignored until the next newline.

#### Uno USB → Python

The base emits one JSON object per line at 1 Hz and after state/control changes:

```json
{"type":"telemetry","seq":42,"uptime_ms":42000,"ax":0.010,"ay":-0.020,"az":1.000,"gx":0.3,"gy":-0.4,"gz":0.0,"sound_level":12,"state":"normal","fall_stage":"monitoring","armed":true,"muted_ms":0,"bt_connected":true,"wearable_age_ms":20,"battery_pct":null}
```

- Accelerometer values are in **g**; gyro values are in **degrees/second**.
- `state`: `normal`, `cry`, `fall`, or `offline`.
- `fall_stage`: `monitoring`, `impact`, `orientation`, `stillness`, or `confirmed`.
- `wearable_age_ms` is `null` until the first valid wearable frame.
- Motion values are `null` if the wearable/IMU is unavailable. The last known motion value must not be interpreted as a fresh reading.
- `battery_pct` is always `null`: there is no battery-voltage measurement circuit in this reference.
- Timestamps come from the Python server; `uptime_ms` is not a date.

#### Python → Uno control and confirmation

```json
{"type":"command","id":"cmd-123abc","action":"acknowledge","seconds":15}
```

Allowed actions are `arm`, `disarm`, and `acknowledge`. IDs contain up to 64 ASCII letters, digits, hyphens, or underscores. `seconds` is optional and, when supplied, must be 15 on an acknowledge command. Valid commands receive:

```json
{"type":"command_ack","id":"cmd-123abc","ok":true,"armed":true,"muted_ms":15000}
```

The base then emits telemetry. A repeated immediately previous command ID is acknowledged again without applying it twice. Invalid commands receive no confirmation; the bridge must time out and keep the prior confirmed hardware state. The control protocol is intended for the local USB connection, not an untrusted public network.

### Verification completed and still required

Host C++ tests exercise detector timing, rejection of impact without orientation change, restart of the stillness timer, explicit latch reset, `millis()` rollover, CSV bounds, duplicate JSON-key rejection, and command parsing. To run them from the project root:

```bash
g++ -std=c++11 -Wall -Wextra -Werror firmware/tests/test_logic.cpp -o firmware-tests
./firmware-tests
```

The tests passed with AddressSanitizer/UndefinedBehaviorSanitizer enabled in the development environment (leak detection was disabled because this container blocks its process inspection). **The Arduino sketches have not been compiled against installed board cores or flashed to hardware here.** Confirm board compilation, SRAM use, radio pairing/reconnect, sensor calibration, hardware button behavior, and alarm latency on your test rig. The host tests do not prove the detector's accuracy on real motion or sound.
