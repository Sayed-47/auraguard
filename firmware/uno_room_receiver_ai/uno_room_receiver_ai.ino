/*
  ROOM UNIT (Arduino Uno), AI variant - for the AI baby unit (esp32_baby_unit_ai)
  Identical to the supplied uno_room_receiver_cry except it also understands the
  baby unit's WANDER message (sent when the baby sits at the Bluetooth range
  limit for 8+ seconds). Wander warning: yellow slow blink + low beep, below
  FALL/LINK-LOST/CRY in priority, cleared after 5 s without a WANDER message.
  Wiring (unchanged): HC-05 TXD->pin2, HC-05 RXD<-pin3 via 1k/2.2k divider,
  buzzer->pin5, red LED->6, yellow->7, green->8, ACK switch->9, ARM switch->10.
  Serial Monitor: 9600 baud.
  Messages from baby unit:  OK  FALL  CRY  WANDER     Message to baby unit:  ACK
  The gateway parses the new wander logs with --protocol uno-room-v1, same as before.
*/
#include <SoftwareSerial.h>
SoftwareSerial BT(2, 3);   // RX, TX

const int LED_RED = 6, LED_YELLOW = 7, LED_GREEN = 8;
const int BUZZER = 5, BTN_ACK = 9, BTN_ARM = 10, MIC = A0;
const bool LINK_CHECK = true;
const bool LOCAL_MIC = false;                  // false = cry comes from the ESP32 (message CRY)
const int MIC_MARGIN = 150;
const unsigned long CRY_MIN_MS = 1500;
const unsigned long MUTE_MS = 15000;
const unsigned long LINK_TIMEOUT_MS = 6000;
const unsigned long WANDER_TIMEOUT_MS = 5000;    // no WANDER for this long = back in safe range

bool armed = true, cryActive = false, fallActive = false, wanderActive = false;
bool babySeen = false, linkLost = false;
int micBase = 0;
unsigned long mutedUntil = 0, lastBabyMsg = 0, lastStatus = 0, lastCryMsg = 0, lastWanderMsg = 0;
bool lastAck = HIGH, lastArm = HIGH;
unsigned long lastAckT = 0, lastArmT = 0;
char btBuf[24];
byte btLen = 0;

void handleLine(const char *s) {
  lastBabyMsg = millis();
  if (!babySeen) { babySeen = true; Serial.println(F("Baby unit LINKED (first message received)")); }
  if (linkLost)  { linkLost = false; Serial.println(F("Link restored")); }
  if (strcmp(s, "FALL") == 0) {
    fallActive = true;
    Serial.println(F("!!! FALL ALERT from baby unit !!!"));
  } else if (strcmp(s, "CRY") == 0) {
    if (armed) {
      if (!cryActive) Serial.println(F("CRY reported by baby unit"));
      cryActive = true; lastCryMsg = millis();
    }
  } else if (strcmp(s, "WANDER") == 0) {
    if (armed) {
      if (!wanderActive) Serial.println(F("!!! WANDER - baby near Bluetooth range limit !!!"));
      wanderActive = true; lastWanderMsg = millis();
    }
  } else if (strcmp(s, "OK") != 0) {
    Serial.print(F("unknown msg: ")); Serial.println(s);
  }
}

void pollBluetooth() {
  while (BT.available()) {
    char c = BT.read();
    if (c == '\n') { btBuf[btLen] = 0; if (btLen > 0) handleLine(btBuf); btLen = 0; }
    else if (c != '\r' && btLen < sizeof(btBuf) - 1) btBuf[btLen++] = c;
  }
}

void checkLink() {
  if (armed && babySeen && !linkLost && millis() - lastBabyMsg > LINK_TIMEOUT_MS) {
    linkLost = true;
    Serial.println(F("!!! LINK LOST - no signal from baby unit !!!"));
  }
}

void checkButtons() {
  bool ack = digitalRead(BTN_ACK);
  if (lastAck == HIGH && ack == LOW && millis() - lastAckT > 250) {
    lastAckT = millis();
    fallActive = false;
    mutedUntil = millis() + MUTE_MS;
    BT.print("ACK\n");
    Serial.println(F("ACKNOWLEDGED (sent ACK to baby unit)"));
  }
  lastAck = ack;

  bool arm = digitalRead(BTN_ARM);
  if (lastArm == HIGH && arm == LOW && millis() - lastArmT > 250) {
    lastArmT = millis();
    armed = !armed;
    cryActive = false; fallActive = false; linkLost = false; wanderActive = false;
    lastBabyMsg = millis();
    Serial.println(armed ? F("ARMED") : F("DISARMED"));
  }
  lastArm = arm;
}

void updateOutputs() {
  unsigned long now = millis();
  if (!armed) {
    digitalWrite(LED_GREEN, (now / 500) % 2);
    digitalWrite(LED_YELLOW, LOW); digitalWrite(LED_RED, LOW);
    noTone(BUZZER);
    return;
  }
  bool muted = now < mutedUntil;
  bool fall = fallActive && !muted, lost = linkLost && !muted, cry = cryActive && !muted, wander = wanderActive && !muted;
  bool fast = (now / 150) % 2, slow = (now / 500) % 2;

  digitalWrite(LED_GREEN, !(fall || lost || cry || wander));
  digitalWrite(LED_YELLOW, (cry && !fall && !lost) ? HIGH : (wander && !fall && !lost && !cry) ? slow : LOW);
  digitalWrite(LED_RED, fall ? fast : (lost ? slow : 0));

  if (fall)        tone(BUZZER, fast ? 2000 : 1500);
  else if (lost)   { if (slow) tone(BUZZER, 800); else noTone(BUZZER); }
  else if (cry)    { if (now % 1500 < 100) tone(BUZZER, 1000); else noTone(BUZZER); }
  else if (wander) { if (now % 2000 < 120) tone(BUZZER, 700); else noTone(BUZZER); }
  else             noTone(BUZZER);
}

void setup() {
  Serial.begin(9600);
  BT.begin(9600);
  pinMode(LED_RED, OUTPUT); pinMode(LED_YELLOW, OUTPUT); pinMode(LED_GREEN, OUTPUT);
  pinMode(BUZZER, OUTPUT);
  pinMode(BTN_ACK, INPUT_PULLUP); pinMode(BTN_ARM, INPUT_PULLUP);
  Serial.println(F("Room unit ready. Cry detection comes from the baby unit (CRY messages)."));
  lastBabyMsg = millis();
}

void loop() {
  checkButtons();
  pollBluetooth();
  checkLink();
  if (armed) {
    if (cryActive && millis() - lastCryMsg > 2500) { cryActive = false; Serial.println(F("cry ended")); }
    if (wanderActive && millis() - lastWanderMsg > WANDER_TIMEOUT_MS) { wanderActive = false; Serial.println(F("wander cleared")); }
  }
  updateOutputs();

  if (millis() - lastStatus >= 2000) {
    lastStatus = millis();
    Serial.print(F("status | armed=")); Serial.print(armed);
    Serial.print(F(" baby="));
    Serial.print(!babySeen ? F("waiting") : (linkLost ? F("LOST") : F("linked")));
    Serial.print(F(" lastMsg=")); Serial.print((millis() - lastBabyMsg) / 1000); Serial.print(F("s ago"));
    Serial.print(F(" mic=remote"));
    Serial.print(F(" cry=")); Serial.println(cryActive);
  }
}
