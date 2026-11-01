// AuraGuard: original ESP32 + MPU6050 bench reference (Arduino-ESP32 3.x).
// HC-05 must be configured as master and bound to this ESP32's Bluetooth MAC.
#include <Arduino.h>
#include <Wire.h>
#include <BluetoothSerial.h>
#include <esp_bt_device.h>
#include "fall_detector.h"

#if !defined(CONFIG_BT_SPP_ENABLED)
#error "This sketch requires an original ESP32 with Classic Bluetooth SPP."
#endif

constexpr uint8_t MPU_ADDRESS = 0x68; // Change to 0x69 if AD0 is high.
constexpr uint32_t SAMPLE_MS = 20;   // 50 Hz.
constexpr uint32_t TELEMETRY_MS = 200; // 5 Hz over HC-05 UART at 9600 baud.
const char BT_PIN[] = "1234";        // Match the HC-05 pairing configuration.
BluetoothSerial SerialBT;
FallDetector detector;
float ax = 0, ay = 0, az = 0, gx = 0, gy = 0, gz = 0;
uint32_t lastSample = 0, lastTelemetry = 0, lastInit = 0, sequence = 0;
bool imuReady = false, sampleValid = false;
char resetLine[12];
uint8_t resetLength = 0;
bool resetOverflow = false;

bool writeRegister(uint8_t reg, uint8_t value) {
  Wire.beginTransmission(MPU_ADDRESS);
  Wire.write(reg);
  Wire.write(value);
  return Wire.endTransmission() == 0;
}

bool initImu() {
  Wire.beginTransmission(MPU_ADDRESS);
  Wire.write(0x75); // WHO_AM_I
  if (Wire.endTransmission(false) != 0 || Wire.requestFrom(MPU_ADDRESS, uint8_t(1)) != 1)
    return false;
  if ((Wire.read() & 0x7E) != 0x68) return false;
  return writeRegister(0x6B, 0x01) && // Wake, PLL clock.
         writeRegister(0x1A, 0x03) && // DLPF enabled.
         writeRegister(0x19, 19) &&   // 1000 / (19 + 1) = 50 Hz.
         writeRegister(0x1B, 0x08) && // Gyro +/-500 dps, 65.5 LSB/dps.
         writeRegister(0x1C, 0x10);   // Accel +/-8 g, 4096 LSB/g.
}

int16_t readWord() {
  const uint16_t hi = uint8_t(Wire.read());
  const uint16_t lo = uint8_t(Wire.read());
  return int16_t((hi << 8) | lo);
}

bool readImu() {
  Wire.beginTransmission(MPU_ADDRESS);
  Wire.write(0x3B);
  if (Wire.endTransmission(false) != 0 || Wire.requestFrom(MPU_ADDRESS, uint8_t(14)) != 14)
    return false;
  ax = readWord() / 4096.0f;
  ay = readWord() / 4096.0f;
  az = readWord() / 4096.0f;
  (void)readWord(); // Chip temperature is deliberately not exposed as baby temperature.
  gx = readWord() / 65.5f;
  gy = readWord() / 65.5f;
  gz = readWord() / 65.5f;
  return true;
}

void sendTelemetry(uint32_t now) {
  if (!SerialBT.hasClient()) return;
  char line[128];
  // Fixed-point CSV keeps the Uno parser small. Units: milli-g and 0.1 dps.
  const int length = snprintf(line, sizeof(line),
    "LS1,%lu,%lu,%u,%d,%d,%d,%d,%d,%d,%u\n",
    (unsigned long)sequence++, (unsigned long)now, sampleValid ? 1 : 0,
    int(lroundf(ax * 1000)), int(lroundf(ay * 1000)), int(lroundf(az * 1000)),
    int(lroundf(gx * 10)), int(lroundf(gy * 10)), int(lroundf(gz * 10)),
    unsigned(detector.stage));
  if (length > 0 && size_t(length) < sizeof(line))
    SerialBT.write((const uint8_t *)line, size_t(length));
}

void receiveReset() {
  while (SerialBT.available()) {
    const char c = char(SerialBT.read());
    if (c == '\n') {
      if (!resetOverflow) {
        resetLine[resetLength] = 0;
        if (strcmp(resetLine, "RESET") == 0) detector.reset();
      }
      resetLength = 0;
      resetOverflow = false;
    } else if (c != '\r') {
      if (resetLength < sizeof(resetLine) - 1) resetLine[resetLength++] = c;
      else resetOverflow = true;
    }
  }
}

void setup() {
  Serial.begin(115200);
  Wire.begin(21, 22);
  Wire.setClock(400000);
  Wire.setTimeOut(20);
  // HC-05 is a legacy PIN-pairing module, not a BLE/GATT peripheral.
  SerialBT.disableSSP();
  SerialBT.begin("AuraGuard-Wearable");
  SerialBT.setPin(BT_PIN, sizeof(BT_PIN) - 1);
  const uint8_t *mac = esp_bt_dev_get_address();
  if (mac) Serial.printf("Bluetooth MAC: %02X:%02X:%02X:%02X:%02X:%02X\n",
    mac[0], mac[1], mac[2], mac[3], mac[4], mac[5]);
  imuReady = initImu();
}

void loop() {
  const uint32_t now = millis();
  receiveReset();
  if (!imuReady && uint32_t(now - lastInit) >= 2000) {
    lastInit = now;
    imuReady = initImu();
  }
  bool stageChanged = false;
  if (uint32_t(now - lastSample) >= SAMPLE_MS) {
    lastSample = now;
    const uint8_t oldStage = detector.stage;
    sampleValid = imuReady && readImu();
    if (sampleValid) detector.update(now, ax, ay, az, gx, gy, gz);
    else {
      imuReady = false;
      detector.reset();
    }
    stageChanged = oldStage != detector.stage;
  }
  if (stageChanged || uint32_t(now - lastTelemetry) >= TELEMETRY_MS) {
    lastTelemetry = now;
    sendTelemetry(now);
  }
  delay(1);
}
