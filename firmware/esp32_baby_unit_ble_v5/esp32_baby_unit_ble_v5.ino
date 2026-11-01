/*
  BABY UNIT, BLE CLIENT (v5)  ("Path A")   ESP32 NodeMCU-32S, arduino-esp32 core 3.3.x
  The ESP32 connects by BLE straight to the Uno's "HC-05" module (service FFE0, characteristic FFE1). No phone needed.
  Board: "ESP32 Dev Module". Serial Monitor: 115200.
  If compile says "Sketch too big": Tools > Partition Scheme > "Huge APP (3MB No OTA/1MB SPIFFS)".
  Wiring: MPU6050 VCC->3V3, GND->GND, SDA->21, SCL->22.  Sound sensor: VCC->3V3 (NOT 5V), GND, AO->GPIO34.

  v5 changes vs v4 (fall detection only; the BLE link / sound / heartbeat code is unchanged):
  WHY: in the failed trials the log shows  "trigger: free-fall ... -> I2C error 259 (ESP_ERR_INVALID_STATE) -> [MPU FAULT] ... -> re-init".
       The fall WAS seen (peak 8-10 g) but the impact jolted the MPU6050 wiring, the I2C read failed, and v4's recovery code
       cleared the pending fall ("watching = false"), so the stillness check never ran and no FALL was sent.
  1. A pending fall candidate now SURVIVES an I2C fault / all-zero data / MPU reset: after recovery the stillness window is
     restarted (measured after the glitch) and the normal check runs.
  2. If the MPU6050 stays unusable until CANDIDATE_MAX_MS after a trigger, FALL is sent anyway ("sensor lost after impact")
     when ALERT_ON_SENSOR_LOSS is true (safety first; set false to disable).
  3. Recovery first tries only a bus reset (Wire.end/begin) and keeps the chip config if the MPU is still configured
     (no slow 170 ms re-init); full re-init only if it was really reset.
  4. I2C clock 100 kHz (was 400 kHz): more tolerant of long jumper wires and jolts. (A mitigation, not a proven cure.)
  5. While a fall candidate is pending and the MPU6050 is offline, it is retried every 0.3 s (was 2 s) so confirmation arrives sooner.
  6. Every fault prints its context ([MPU FAULT #n] ... ms since trigger) and the movement burst cut by the fault is printed;
     status line shows i2cFaults. Use these numbers to see whether the wiring is the real cause.
  HARDWARE NOTE: if i2cFaults keeps rising on bumps, fix the wiring: solder the MPU6050 header pins, shorten SDA/SCL wires
  (twist them with GND), strain-relief the cable, add 100 nF across MPU VCC-GND, and mount the MPU rigidly.

  Sends to Uno:   "OK\n" every 1 s (heartbeat), "FALL\n", and "CRY\n" every 1 s while crying   (BOOT button = demo FALL, rings the REAL alarm)
  Receives:       "ACK\n" (notification from the Uno when the caregiver presses ACK)
  The module accepts ONE BLE central at a time: disconnect nRF Connect / turn phone Bluetooth off first.
  Not compiled by the author against the real core (logic checked only in a host simulation). Paste any compiler error back.
*/
#include <Wire.h>
#include <BLEDevice.h>

// ===== SETTINGS =====
const char *TARGET_ADDR = "4d:42:62:50:10:0f";   // module address seen in nRF Connect
const char *TARGET_NAME = "HC-05";               // fallback match by advertised name
static BLEUUID SERVICE_UUID((uint16_t)0xFFE0);
static BLEUUID CHAR_UUID((uint16_t)0xFFE1);      // NOTIFY + WRITE. FFE2 is never touched.
const int BTN_DEMO = 0;                          // BOOT button
const int SOUND_PIN = 34;                        // sound sensor AO (ADC1 pin)
const int CRY_SWING = 400;                       // TUNE: peak-to-peak ADC counts in a 50 ms window that count as "loud"
const unsigned long CRY_MIN_MS = 1500, CRY_QUIET_MS = 1000, SOUND_WINDOW_MS = 50, CRY_SEND_MS = 1000;

const float IMPACT_G = 1.8, FREEFALL_G = 0.5, STILL_SWING = 0.35, STILL_DEV = 0.3;
const int FREEFALL_N = 2;
const unsigned long IGNORE_MS = 600, WATCH_END_MS = 1800, RESTART_LIMIT_MS = 3000;
const unsigned long COOLDOWN_MS = 5000, HEARTBEAT_MS = 1000, RETRY_MS = 3000;
const unsigned long I2C_HZ = 100000;                               // v5: was 400000
const unsigned long CANDIDATE_MAX_MS = 5500;                       // v5: longest a pending fall candidate may live (normal max is 4800)
const bool ALERT_ON_SENSOR_LOSS = true;                            // v5: trigger + MPU fault + no confirmation -> still send FALL

// ===== BLE state =====
BLEClient *client = nullptr;
BLERemoteCharacteristic *rc = nullptr;
BLEAdvertisedDevice *target = nullptr;
volatile bool connected = false, foundTarget = false, lineReady = false;
volatile uint32_t rxBytes = 0;
char rxBuf[24], lastLine[24];
byte rxLen = 0;
int failCount = 0;

// ===== fall detection state =====
int mpuAddr = 0, freefallCount = 0;
float accelLSB = 16384.0;                // set from the chip's ACCEL_CONFIG after init
bool watching = false, windowStarted = false, lastDemo = HIGH;
bool faultSinceTrigger = false;          // v5: an MPU fault happened while a fall candidate was pending
int i2cFaults = 0;                       // v5: total faults since boot
float aMin = 0, aMax = 0, peakG = 0, lastA = 1.0;
unsigned long watchStart = 0, trigStart = 0, cooldownUntil = 0, lastSample = 0, lastBeat = 0;
int zeroCount = 0;
unsigned long lastMpuCheck = 0, lastRecover = 0;
unsigned long burstStart = 0, lastOut = 0; float bMin = 9, bMax = 0; int lowN = 0;
unsigned long lastMpuTry = 0, lastStatus = 0, lastAttempt = 0;

// ===== cry detection state =====
int sMin = 4095, sMax = 0, lastSwing = 0, maxSwing2s = 0;
unsigned long winStart = 0, loudStart = 0, lastLoud = 0, quietSince = 0, lastCrySend = 0;
bool cryActive = false;

// ----- notifications from the module (ACK) -----
static void onNotify(BLERemoteCharacteristic *c, uint8_t *data, size_t len, bool isNotify) {
  for (size_t i = 0; i < len; i++) {
    char ch = (char)data[i];
    rxBytes++;
    if (ch == '\n') {
      rxBuf[rxLen] = 0;
      if (rxLen > 0) { strncpy(lastLine, rxBuf, sizeof(lastLine) - 1); lastLine[sizeof(lastLine) - 1] = 0; lineReady = true; }
      rxLen = 0;
    } else if (ch != '\r' && rxLen < sizeof(rxBuf) - 1) rxBuf[rxLen++] = ch;
  }
}

class ClientCB : public BLEClientCallbacks {
  void onConnect(BLEClient *c) {}
  void onDisconnect(BLEClient *c) { connected = false; rc = nullptr; }
};
static ClientCB clientCB;

class ScanCB : public BLEAdvertisedDeviceCallbacks {
  void onResult(BLEAdvertisedDevice dev) {
    char name[32] = "", addr[20] = "";
    if (dev.haveName()) { strncpy(name, dev.getName().c_str(), sizeof(name) - 1); name[sizeof(name) - 1] = 0; }
    strncpy(addr, dev.getAddress().toString().c_str(), sizeof(addr) - 1); addr[sizeof(addr) - 1] = 0;
    Serial.printf("  seen: %s  name='%s'  rssi=%d\n", addr, name, (int)dev.getRSSI());
    if (strcasecmp(addr, TARGET_ADDR) == 0 || strcmp(name, TARGET_NAME) == 0) {
      if (target) delete target;
      target = new BLEAdvertisedDevice(dev);
      foundTarget = true;
      BLEDevice::getScan()->stop();
    }
  }
};
static ScanCB scanCB;

bool scanForTarget() {
  foundTarget = false;
  BLEScan *scan = BLEDevice::getScan();
  scan->setAdvertisedDeviceCallbacks(&scanCB);
  scan->setActiveScan(true);
  scan->setInterval(100);
  scan->setWindow(99);
  scan->start(6, false);          // blocks up to 6 s, or until the module is found
  scan->clearResults();
  return foundTarget;
}

bool connectToTarget() {
  client = BLEDevice::createClient();
  client->setClientCallbacks(&clientCB);
  Serial.println("[BLE] connecting...");
  if (!client->connect(target)) { Serial.println("[BLE][FAIL] connect() returned false"); return false; }
  connected = true;
  BLERemoteService *svc = client->getService(SERVICE_UUID);
  if (!svc) { Serial.println("[BLE][FAIL] service FFE0 not found"); client->disconnect(); return false; }
  BLERemoteCharacteristic *c = svc->getCharacteristic(CHAR_UUID);
  if (!c) { Serial.println("[BLE][FAIL] characteristic FFE1 not found"); client->disconnect(); return false; }
  Serial.printf("[BLE] FFE1 found: canWrite=%d canNotify=%d\n", (int)c->canWrite(), (int)c->canNotify());
  if (!c->canWrite()) { Serial.println("[BLE][FAIL] FFE1 not writable"); client->disconnect(); return false; }
  if (c->canNotify()) c->registerForNotify(onNotify);   // the library writes the CCCD itself
  rc = c;
  Serial.println("[BLE] READY: FFE1 write + notify");
  return true;
}

void tryLink() {
  Serial.println("[BLE] scanning for the module (phone/nRF must NOT be connected to it)...");
  bool ok = false;
  if (!scanForTarget()) Serial.println("[BLE][FAIL] module not found in scan");
  else ok = connectToTarget();
  if (ok) failCount = 0;
  else if (++failCount >= 10) { Serial.println("[BLE] 10 failures -> restarting ESP32"); delay(300); ESP.restart(); }
}

bool sendLine(const char *s) {
  BLERemoteCharacteristic *r = rc;
  if (!connected || !r) return false;
  r->writeValue((uint8_t *)s, strlen(s), true);          // write WITH response
  return true;
}

// ----- MPU6050 -----
bool mpuRegRead(int addr, uint8_t reg, uint8_t &val) {
  Wire.beginTransmission(addr); Wire.write(reg);
  if (Wire.endTransmission(false) != 0) return false;
  if (Wire.requestFrom(addr, 1) != 1) return false;
  val = (uint8_t)Wire.read();
  return true;
}

bool initMPU() {
  for (int a = 0x68; a <= 0x69; a++) {
    Wire.beginTransmission(a);
    if (Wire.endTransmission() != 0) continue;
    Wire.beginTransmission(a); Wire.write(0x6B); Wire.write(0x00);       // wake up (clear sleep)
    if (Wire.endTransmission() != 0) continue;
    delay(50);
    uint8_t cfg = 0xFF;
    for (int tries = 0; tries < 3; tries++) {                            // set +-8 g, retry until it reads back
      Wire.beginTransmission(a); Wire.write(0x1C); Wire.write(0x10);
      Wire.endTransmission();
      delay(20);
      if (mpuRegRead(a, 0x1C, cfg) && cfg == 0x10) break;
    }
    if (cfg > 0x18) cfg = 0x00;
    accelLSB = 16384.0 / (float)(1 << ((cfg >> 3) & 3));                 // 0->16384, 1->8192, 2->4096, 3->2048
    mpuAddr = a; delay(100);
    Serial.printf("[OK] MPU6050 at 0x%02X, ACCEL_CONFIG=0x%02X (expect 0x10), scale=%.0f LSB/g\n", a, cfg, accelLSB);
    return true;
  }
  mpuAddr = 0;
  return false;
}

// allZero = the six data bytes were all zero: a reset/sleeping or disconnected chip, not a real measurement.
bool readAccelG(float &g, bool &allZero) {
  Wire.beginTransmission(mpuAddr); Wire.write(0x3B);
  if (Wire.endTransmission(false) != 0 || Wire.requestFrom(mpuAddr, 6) != 6) return false;
  int16_t v[3];
  for (int i = 0; i < 3; i++) { int hi = Wire.read(); int lo = Wire.read(); v[i] = (hi << 8) | lo; }
  allZero = (v[0] == 0 && v[1] == 0 && v[2] == 0);
  float x = v[0] / accelLSB, y = v[1] / accelLSB, z = v[2] / accelLSB;
  g = sqrt(x * x + y * y + z * z);
  return true;
}

void busReset() { Wire.end(); delay(2); Wire.begin(21, 22); Wire.setClock(I2C_HZ); }

// v5: a pending fall candidate (watching) is KEPT across a fault; its stillness window restarts after the glitch.
void recoverMPU(const char *why) {
  unsigned long now = millis();
  lastRecover = now; i2cFaults++;
  Serial.printf("[MPU FAULT #%d] %s | pending=%d last|a|=%.2f g peak=%.2f g ms-since-trigger=%lu\n",
                i2cFaults, why, (int)watching, lastA, peakG, watching ? (now - trigStart) : 0UL);
  if (burstStart) {
    Serial.printf("[motion] (cut by fault) %lu ms  min=%.2f g  max=%.2f g\n", lastOut - burstStart, bMin, bMax);
    burstStart = 0;
  }
  if (watching) { faultSinceTrigger = true; watchStart = now; windowStarted = false; }   // keep the candidate, re-measure stillness after the glitch
  zeroCount = 0; freefallCount = 0;
  busReset();
  bool chipOk = false;
  if (mpuAddr) {
    uint8_t pm = 0xFF, cfg = 0xFF;
    chipOk = mpuRegRead(mpuAddr, 0x6B, pm) && mpuRegRead(mpuAddr, 0x1C, cfg) && !(pm & 0x40) && cfg == 0x10;
  }
  if (chipOk) Serial.println("[MPU] bus reset was enough (chip still configured) - no slow re-init");
  else { mpuAddr = 0; initMPU(); }
  lastMpuCheck = millis();
}

void sendFall(const char *why) {
  Serial.printf(">>> FALL (%s) -> sending to room unit\n", why);
  sendLine("FALL\n");
  cooldownUntil = millis() + COOLDOWN_MS;
}

// Diagnostic: prints one line per movement burst (any |a| outside 0.8-1.25 g), whether or not the link is up.
void recordBurst(float a, unsigned long now, bool linked) {
  bool out = (a < 0.8 || a > 1.25);
  if (out) {
    if (!burstStart) { burstStart = now; bMin = a; bMax = a; lowN = 0; }
    lastOut = now;
    if (a < bMin) bMin = a;
    if (a > bMax) bMax = a;
    if (a < FREEFALL_G) lowN++;
  } else if (burstStart && now - lastOut > 400) {
    Serial.printf("[motion] %lu ms  min=%.2f g  max=%.2f g  samples below %.2f g: %d  link=%s\n",
                  lastOut - burstStart, bMin, bMax, FREEFALL_G, lowN, linked ? "UP" : "DOWN");
    burstStart = 0;
  }
}

void fallLogic(float a, unsigned long now) {
  if (a > peakG) peakG = a;
  if (now < cooldownUntil) return;
  if (!watching) {
    bool trig = false; const char *why = "";
    if (a > IMPACT_G) { trig = true; why = "impact"; }
    else if (a < FREEFALL_G) { if (++freefallCount >= FREEFALL_N) { trig = true; why = "free-fall"; } }
    else freefallCount = 0;
    if (trig) {
      watching = true; windowStarted = false; watchStart = now; trigStart = now; freefallCount = 0; faultSinceTrigger = false;
      Serial.printf("trigger: %s (a=%.2f g) -> waiting for stillness...\n", why, a);
    }
    return;
  }
  // a (new) impact while watching = the landing: restart the stillness window after it (limited to 3 s in total)
  if (a > IMPACT_G && now - trigStart < RESTART_LIMIT_MS) { watchStart = now; windowStarted = false; return; }
  unsigned long t = now - watchStart;
  if (t < IGNORE_MS) return;
  if (!windowStarted) { windowStarted = true; aMin = aMax = a; }
  if (a < aMin) aMin = a;
  if (a > aMax) aMax = a;
  if (t >= WATCH_END_MS) {
    watching = false;
    float swing = aMax - aMin, dev = fabs(a - 1.0);
    Serial.printf("stillness check: swing=%.2f g (need < %.2f), |a-1|=%.2f g (need < %.2f)%s\n", swing, STILL_SWING, dev, STILL_DEV,
                  faultSinceTrigger ? "  [after an MPU fault]" : "");
    if (swing < STILL_SWING && dev < STILL_DEV) sendFall(faultSinceTrigger ? "impact + stillness (after MPU fault)" : "impact + stillness");
    else { Serial.println("not still enough -> ignored"); cooldownUntil = now + 1000; }
    faultSinceTrigger = false;
  }
}

// v5: runs every loop, independent of sensor reads. A candidate that could not be confirmed in time because the MPU kept failing
// is reported anyway (a violent trigger followed by a dead sensor is more likely a real fall than a false alarm).
void candidateWatchdog(unsigned long now) {
  if (!watching || now - trigStart <= CANDIDATE_MAX_MS) return;
  watching = false;
  if (ALERT_ON_SENSOR_LOSS && faultSinceTrigger) sendFall("trigger, then MPU fault; stillness could not be confirmed");
  else { Serial.println("fall candidate expired -> ignored"); cooldownUntil = now + 1000; }
  faultSinceTrigger = false;
}

// loud = peak-to-peak swing of the sensor signal in a 50 ms window above CRY_SWING; loud for 1.5 s (dips under 300 ms tolerated) = cry.
void soundLogic(unsigned long now, bool linked) {
  int v = analogRead(SOUND_PIN);
  if (v < sMin) sMin = v;
  if (v > sMax) sMax = v;
  if (now - winStart < SOUND_WINDOW_MS) return;
  lastSwing = sMax - sMin;
  if (lastSwing > maxSwing2s) maxSwing2s = lastSwing;
  sMin = 4095; sMax = 0; winStart = now;
  bool loud = lastSwing > CRY_SWING;
  if (loud) { lastLoud = now; if (loudStart == 0) loudStart = now; }
  else if (now - lastLoud > 300) loudStart = 0;
  if (loudStart != 0 && now - loudStart >= CRY_MIN_MS) {
    if (!cryActive) Serial.println("[CRY] detected");
    cryActive = true; quietSince = 0;
  } else if (loudStart == 0) {
    if (!quietSince) quietSince = now;
    if (cryActive && now - quietSince >= CRY_QUIET_MS) { cryActive = false; Serial.println("[CRY] ended"); }
  }
  if (cryActive && linked && now - lastCrySend >= CRY_SEND_MS) { lastCrySend = now; sendLine("CRY\n"); }
}

void setup() {
  Serial.begin(115200); delay(500);
  Serial.println("\nBABY UNIT (BLE client v5) START");
  pinMode(BTN_DEMO, INPUT_PULLUP);
  pinMode(SOUND_PIN, INPUT);
  Wire.begin(21, 22); Wire.setClock(I2C_HZ);
  if (!initMPU()) Serial.println("[ERROR] MPU6050 not found (will retry)");
  BLEDevice::init("BabyBand-ESP32");
  Serial.println("[BLE] stack started");
}

void loop() {
  unsigned long now = millis();
  bool linked = connected && rc != nullptr;
  static bool wasLinked = false;
  if (linked != wasLinked) { wasLinked = linked; Serial.println(linked ? "[LINK UP] module connected" : "[LINK DOWN]"); }

  if (!linked && now - lastAttempt >= RETRY_MS) { tryLink(); lastAttempt = millis(); return; }

  if (lineReady) { lineReady = false; Serial.print("[room unit] "); Serial.println(lastLine); }

  bool demo = digitalRead(BTN_DEMO);
  if (lastDemo == HIGH && demo == LOW) { if (linked) sendFall("BOOT button demo"); else Serial.println("[BOOT pressed but not linked]"); }
  lastDemo = demo;

  soundLogic(now, linked);

  if (!mpuAddr && now - lastMpuTry >= (watching ? 300UL : 2000UL)) { recoverMPU("MPU6050 offline, retrying"); lastMpuTry = millis(); }   // v5: retry fast while a fall candidate is pending
  if (mpuAddr && now - lastSample >= 5) {
    lastSample = now;
    float a; bool z = false;
    if (readAccelG(a, z)) {
      if (z) {                                           // all-zero data: never feed it to the fall logic; KEEP a pending candidate
        zeroCount++; freefallCount = 0; lastA = 0;
        if (watching) faultSinceTrigger = true;
        if (zeroCount >= 5 && now - lastRecover > 1000) recoverMPU("all-zero accelerometer data (loose wire / power glitch / chip reset?)");
      } else {
        zeroCount = 0; lastA = a;
        recordBurst(a, now, linked);
        if (linked) fallLogic(a, now); else watching = false;
      }
    } else if (now - lastRecover > 1000) recoverMPU("I2C read failed");
  }
  candidateWatchdog(now);
  if (mpuAddr && now - lastMpuCheck >= 500) {           // PWR_MGMT_1 sleep bit set = the chip was reset
    lastMpuCheck = now;
    uint8_t pm = 0;
    if (!mpuRegRead(mpuAddr, 0x6B, pm)) { if (now - lastRecover > 1000) recoverMPU("PWR_MGMT_1 read failed"); }
    else if (pm & 0x40) recoverMPU("MPU6050 is in sleep mode (it was reset)");
  }

  if (linked && now - lastBeat >= HEARTBEAT_MS) { lastBeat = now; sendLine("OK\n"); }

  if (now - lastStatus >= 2000) {
    lastStatus = now;
    Serial.printf("status | link=%s mpu=%s |a|=%.2f g peak=%.2f g i2cFaults=%d rxBytes=%lu | sound swing now=%d max2s=%d (threshold %d) cry=%d\n",
                  linked ? "UP" : "DOWN", mpuAddr ? (zeroCount ? "ZERO-DATA" : "ok") : "offline", lastA, peakG, i2cFaults, (unsigned long)rxBytes,
                  lastSwing, maxSwing2s, CRY_SWING, (int)cryActive);
    peakG = 0; maxSwing2s = 0;
  }
}
