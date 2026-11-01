// AuraGuard: Arduino Uno + HC-05 room/base station bench reference.
// USB output is NDJSON at 115200. HC-05 data-mode UART must be 9600 baud.
#include <Arduino.h>
#include <SoftwareSerial.h>
#include "protocol.h"

constexpr uint8_t BUZZER = 5, GREEN_LED = 6, YELLOW_LED = 7, RED_LED = 8;
constexpr uint8_t ACK_BUTTON = 9, ARM_BUTTON = 10, SOUND_PIN = A0;
constexpr uint32_t LINK_TIMEOUT_MS = 3000, MUTE_MS = 15000;
constexpr uint32_t SOUND_WINDOW_MS = 25, CRY_MS = 1500;
constexpr uint8_t SOUND_THRESHOLD = 65; // Example relative amplitude; calibrate.
SoftwareSerial bluetooth(2, 3); // RX <- HC-05 TX; TX -> level divider -> HC-05 RX.

WearableFrame wearable = {};
uint32_t lastWearable = 0, lastTelemetry = 0, sequence = 0;
bool seenWearable = false, armed = true, fallLatched = false;
bool ignoreConfirmedUntilClear = false, forceTelemetry = false;
bool muteActive = false;
uint32_t muteStarted = 0;
uint16_t soundMin = 1023, soundMax = 0;
uint8_t soundLevel = 0;
uint32_t soundWindowStarted = 0, loudStarted = 0;
bool loudActive = false, crying = false;
char btLine[128], usbLine[192];
uint8_t btLength = 0, usbLength = 0;
bool btOverflow = false, usbOverflow = false;
char lastCommandId[65] = "";

struct Button {
  uint8_t pin;
  bool reading, stable;
  uint32_t changed;
};
Button acknowledgeButton = {ACK_BUTTON, HIGH, HIGH, 0};
Button armButton = {ARM_BUTTON, HIGH, HIGH, 0};
// Explicit prototype prevents the Arduino preprocessor from moving this before Button.
bool wasPressed(Button &button, uint32_t now);

bool linkHealthy(uint32_t now) {
  return seenWearable && uint32_t(now - lastWearable) <= LINK_TIMEOUT_MS;
}

uint32_t muteRemaining(uint32_t now) {
  if (!muteActive) return 0;
  const uint32_t elapsed = uint32_t(now - muteStarted);
  if (elapsed >= MUTE_MS) { muteActive = false; return 0; }
  return MUTE_MS - elapsed;
}

void acknowledge(uint32_t now) {
  muteStarted = now;
  muteActive = true;
  // Acknowledge does not clear the fall latch or its visible red indication.
  forceTelemetry = true;
}

void setArmed(bool value) {
  if (armed == value) return;
  armed = value;
  fallLatched = false;
  muteActive = false;
  ignoreConfirmedUntilClear = true;
  bluetooth.println(F("RESET"));
  forceTelemetry = true;
}

void printStage(uint8_t stage) {
  switch (stage) {
    case 1: Serial.print(F("impact")); break;
    case 2: Serial.print(F("orientation")); break;
    case 3: Serial.print(F("stillness")); break;
    case 4: Serial.print(F("confirmed")); break;
    default: Serial.print(F("monitoring")); break;
  }
}

void emitTelemetry(uint32_t now) {
  const bool connected = linkHealthy(now);
  const bool sensorOk = connected && wearable.valid;
  Serial.print(F("{\"type\":\"telemetry\",\"seq\":")); Serial.print(sequence++);
  Serial.print(F(",\"uptime_ms\":")); Serial.print(now);
  Serial.print(F(",\"ax\":")); if (sensorOk) Serial.print(wearable.motion[0] / 1000.0f, 3); else Serial.print(F("null"));
  Serial.print(F(",\"ay\":")); if (sensorOk) Serial.print(wearable.motion[1] / 1000.0f, 3); else Serial.print(F("null"));
  Serial.print(F(",\"az\":")); if (sensorOk) Serial.print(wearable.motion[2] / 1000.0f, 3); else Serial.print(F("null"));
  Serial.print(F(",\"gx\":")); if (sensorOk) Serial.print(wearable.motion[3] / 10.0f, 1); else Serial.print(F("null"));
  Serial.print(F(",\"gy\":")); if (sensorOk) Serial.print(wearable.motion[4] / 10.0f, 1); else Serial.print(F("null"));
  Serial.print(F(",\"gz\":")); if (sensorOk) Serial.print(wearable.motion[5] / 10.0f, 1); else Serial.print(F("null"));
  Serial.print(F(",\"sound_level\":")); Serial.print(soundLevel);
  Serial.print(F(",\"state\":\""));
  if (fallLatched) Serial.print(F("fall"));
  else if (!sensorOk) Serial.print(F("offline"));
  else if (crying) Serial.print(F("cry"));
  else Serial.print(F("normal"));
  Serial.print(F("\",\"fall_stage\":\""));
  printStage(fallLatched ? 4 : (sensorOk ? wearable.stage : 0));
  Serial.print(F("\",\"armed\":")); Serial.print(armed ? F("true") : F("false"));
  Serial.print(F(",\"muted_ms\":")); Serial.print(muteRemaining(now));
  Serial.print(F(",\"bt_connected\":")); Serial.print(connected ? F("true") : F("false"));
  Serial.print(F(",\"wearable_age_ms\":"));
  if (seenWearable) Serial.print(uint32_t(now - lastWearable)); else Serial.print(F("null"));
  Serial.println(F(",\"battery_pct\":null}"));
}

void handleBluetoothLine(uint32_t now) {
  WearableFrame next;
  if (!parseFrame(btLine, next)) return;
  // A replayed last packet is not a heartbeat. A reboot changes uptime and seq.
  if (seenWearable && next.sequence == wearable.sequence && next.uptime == wearable.uptime) return;
  if (ignoreConfirmedUntilClear && next.stage != 4) ignoreConfirmedUntilClear = false;
  if (armed && next.valid && next.stage == 4 && !ignoreConfirmedUntilClear) {
    if (!fallLatched) forceTelemetry = true;
    fallLatched = true;
  }
  if (!linkHealthy(now)) forceTelemetry = true;
  wearable = next;
  lastWearable = now;
  seenWearable = true;
}

void emitAck(const Command &command, uint32_t now) {
  Serial.print(F("{\"type\":\"command_ack\",\"id\":\""));
  Serial.print(command.id);
  Serial.print(F("\",\"ok\":true,\"armed\":"));
  Serial.print(armed ? F("true") : F("false"));
  Serial.print(F(",\"muted_ms\":")); Serial.print(muteRemaining(now));
  Serial.println(F("}"));
}

void handleCommand(uint32_t now) {
  Command command;
  if (!parseCommand(usbLine, command)) return; // Invalid input causes bridge timeout.
  if (strcmp(lastCommandId, command.id) != 0) {
    if (!strcmp(command.action, "arm")) setArmed(true);
    else if (!strcmp(command.action, "disarm")) setArmed(false);
    else acknowledge(now);
    strcpy(lastCommandId, command.id);
  }
  emitAck(command, now);
  forceTelemetry = true;
}

void readSerialLines(uint32_t now) {
  while (bluetooth.available()) {
    const char c = char(bluetooth.read());
    if (c == '\n') {
      if (!btOverflow) { btLine[btLength] = 0; handleBluetoothLine(now); }
      btLength = 0; btOverflow = false;
    } else if (c != '\r') {
      if (btLength < sizeof(btLine) - 1) btLine[btLength++] = c;
      else btOverflow = true;
    }
  }
  while (Serial.available()) {
    const char c = char(Serial.read());
    if (c == '\n') {
      if (!usbOverflow) { usbLine[usbLength] = 0; handleCommand(now); }
      usbLength = 0; usbOverflow = false;
    } else if (c != '\r') {
      if (usbLength < sizeof(usbLine) - 1) usbLine[usbLength++] = c;
      else usbOverflow = true;
    }
  }
}

bool wasPressed(Button &button, uint32_t now) {
  const bool reading = digitalRead(button.pin);
  if (reading != button.reading) { button.reading = reading; button.changed = now; }
  if (uint32_t(now - button.changed) >= 35 && reading != button.stable) {
    button.stable = reading;
    return reading == LOW;
  }
  return false;
}

void updateSound(uint32_t now) {
  const uint16_t reading = analogRead(SOUND_PIN);
  if (reading < soundMin) soundMin = reading;
  if (reading > soundMax) soundMax = reading;
  if (uint32_t(now - soundWindowStarted) < SOUND_WINDOW_MS) return;
  soundWindowStarted = now;
  soundLevel = uint32_t(soundMax - soundMin) * 100UL / 1023UL;
  soundMin = 1023; soundMax = 0;
  const bool previouslyCrying = crying;
  if (soundLevel >= SOUND_THRESHOLD) {
    if (!loudActive) { loudActive = true; loudStarted = now; }
    crying = uint32_t(now - loudStarted) >= CRY_MS;
  } else {
    loudActive = false;
    crying = false;
  }
  if (crying != previouslyCrying) forceTelemetry = true;
}

void updateOutputs(uint32_t now) {
  const bool connected = linkHealthy(now) && wearable.valid;
  digitalWrite(GREEN_LED, armed && connected && !fallLatched && !crying);
  digitalWrite(YELLOW_LED, (!armed && (now / 800) % 2) || (armed && crying));
  digitalWrite(RED_LED, armed && (fallLatched || !connected));
  bool buzzerOn = false;
  if (armed && !muteRemaining(now)) {
    if (fallLatched) buzzerOn = (now % 250) < 130;
    else if (!connected) buzzerOn = (now % 1200) < 150;
    else if (crying) buzzerOn = (now % 1000) < 100;
  }
  digitalWrite(BUZZER, buzzerOn ? HIGH : LOW); // Active buzzer; no timer conflict.
}

void setup() {
  Serial.begin(115200);
  bluetooth.begin(9600);
  pinMode(BUZZER, OUTPUT);
  pinMode(GREEN_LED, OUTPUT); pinMode(YELLOW_LED, OUTPUT); pinMode(RED_LED, OUTPUT);
  pinMode(ACK_BUTTON, INPUT_PULLUP); pinMode(ARM_BUTTON, INPUT_PULLUP);
  forceTelemetry = true;
}

void loop() {
  const uint32_t now = millis();
  readSerialLines(now);
  updateSound(now);
  if (wasPressed(acknowledgeButton, now)) acknowledge(now);
  if (wasPressed(armButton, now)) setArmed(!armed);
  updateOutputs(now);
  if (forceTelemetry || uint32_t(now - lastTelemetry) >= 1000) {
    forceTelemetry = false;
    lastTelemetry = now;
    emitTelemetry(now);
  }
}
