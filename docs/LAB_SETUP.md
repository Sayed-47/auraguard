# Lab setup

Use the supplied baby firmware and room receiver as they are. The gateway parses the room sketch's existing USB output; no forwarding patch is required.

## 1. Connect the room Uno

Power the baby ESP32 and its sensors. Connect the **room Uno's USB port** to the computer running the gateway. The baby-to-room Bluetooth connection stays between the hardware units; the browser talks to the Python server.

The supplied room sketch sets both USB Serial and its Bluetooth-module UART to **9600 baud**. The baby ESP32's own USB diagnostic port is 115200 baud and is not the port used by this dashboard.

## 2. Install the gateway

Run these commands from the extracted project folder.

### Windows PowerShell

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r server\requirements.txt
.\.venv\Scripts\python.exe server\app.py --list-ports
```

Close Arduino IDE Serial Monitor, an Arduino CLI monitor session, or any other program using the Uno's port. Then start the gateway, replacing `COM4` with the listed Uno port:

```powershell
.\.venv\Scripts\python.exe server\app.py --port COM4 --baud 9600 --protocol uno-room-v1
```

### Linux or macOS

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r server/requirements.txt
.venv/bin/python server/app.py --list-ports
```

Close any serial monitor using that device. Replace `/dev/ttyACM0` with the listed Uno port:

```bash
.venv/bin/python server/app.py --port /dev/ttyACM0 --baud 9600 --protocol uno-room-v1
```

A USB adapter may use `/dev/ttyUSB0`; macOS commonly uses `/dev/cu.*`. Use the actual returned device name. Run one gateway process for the port.

## 3. Open the app

Open **http://127.0.0.1:8000** and leave the gateway terminal running.

The receiver prints status about every 2 seconds. Once valid logs arrive, the room connection and armed state should update. The baby link depends on messages reaching the Uno, so it can remain waiting even while USB is connected.

The hosted page cannot read the Uno's USB port. The locally served page is the working lab interface. A disconnected page shows unavailable hardware state rather than generated readings.

## 4. Recognize the receiver logs

These are exact formats printed by the supplied Uno sketch. Status values depend on the current hardware state:

```text
Room unit ready. Cry detection comes from the baby unit (CRY messages).
status | armed=1 baby=waiting lastMsg=2s ago mic=remote cry=0
Baby unit LINKED (first message received)
status | armed=1 baby=linked lastMsg=0s ago mic=remote cry=0
```

Possible subsequent lines include:

```text
!!! FALL ALERT from baby unit !!!
ACKNOWLEDGED (sent ACK to baby unit)
CRY reported by baby unit
cry ended
DISARMED
ARMED
!!! LINK LOST - no signal from baby unit !!!
Link restored
```

The Uno consumes raw `OK` heartbeats and repeated `CRY` reports. It does not echo each one to USB. The dashboard reports receiver state and observed events rather than an exact raw packet counter.

If you inspect these logs with Arduino Serial Monitor, stop the gateway first. Close Serial Monitor before restarting the gateway on the same port.

## 5. Check the lab path

Use the hardware switches and a test fixture. The receiver does not read commands from the computer, so the app has no remote alarm-control buttons.

| Check | Expected receiver behavior |
| --- | --- |
| Physical ARM switch on Uno pin 10 | Logs `DISARMED` or `ARMED`. Each toggle clears fall, sound, and link-loss flags. |
| ESP32 BOOT button while linked | Sends `FALL`; Uno logs the fall alert and activates its real alarm path when armed and unmuted. This tests the reporting path without needing a motion-triggered event. |
| Physical ACK switch on Uno pin 9 | Logs acknowledgment, clears the fall flag, and starts 15 seconds of muting. The gateway can show that countdown if it saw the ACK log. |
| Sustained sound above the ESP32's configured threshold | When armed, Uno logs a sound report. It logs `cry ended` after more than 2.5 seconds without another `CRY` report. |
| Stop baby transmissions after the Uno has received at least one message | While armed, the receiver logs link loss after more than 6 seconds without a message. |
| Resume baby transmissions | Receiver logs restoration if its link-loss flag was set. Subsequent status provides its reported message age. |

ACK does not clear the sound or link-loss flag. ARM does not cancel an existing mute timer. Muting suppresses alarm outputs, so LED color alone does not confirm that every alert flag has cleared.

## If the gateway joins an existing session

Periodic status includes armed state, baby-link state, message age, and sound state. It omits the fall flag and mute timer.

A gateway that missed startup cannot reconstruct those omitted values. It leaves fall unknown until it observes startup, a physical ARM toggle, ACK, or a fall report. It displays a mute countdown only after observing ACK. For a deliberate lab reset, use the physical controls and watch for their logs; a fresh USB connection is not proof that there was no earlier alert.

## Quick troubleshooting

| Symptom | Check |
| --- | --- |
| Port cannot open | Close Arduino IDE/CLI Serial Monitor and any earlier gateway process. Confirm the port belongs to the Uno. |
| No recognizable status | Use 9600 baud and `--protocol uno-room-v1`. The baby's 115200-baud USB logs are a different stream. |
| Room connected, baby waiting | Verify the ESP32 is powered and its existing BLE connection reaches the room module. The Uno must receive at least one nonempty Bluetooth line. |
| Baby status says linked but its age grows | ARM changes and unknown Bluetooth lines can affect the receiver's age field. Check fresh baby traffic; the word `linked` alone is not a new heartbeat. |
| Fall or mute shows unknown | The gateway may have attached after the relevant log. Observe startup or use a deliberate physical control action to establish the missing state. |
| No numeric charts | These receiver logs do not carry acceleration, gyro, sound amplitude, battery, or sensor-health readings. This is the expected interface. |

For field definitions and parser behavior, see [PROTOCOL.md](PROTOCOL.md). The supplied firmware files remain unchanged; these instructions do not establish that the detector has been validated on infant motion.
