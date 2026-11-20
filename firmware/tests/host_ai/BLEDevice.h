/* Minimal BLE API stubs for host compilation of the AI sketch. */
#pragma once
#include "Arduino.h"

class BLEUUID {
public:
  BLEUUID() {}
  BLEUUID(uint16_t) {}
};

class BLEAddress {
  std::string value;
public:
  BLEAddress() : value("00:00:00:00:00:00") {}
  std::string toString() const { return value; }
};

class BLERemoteCharacteristic {
public:
  bool canWrite() { return true; }
  bool canNotify() { return true; }
  void registerForNotify(void (*)(BLERemoteCharacteristic *, uint8_t *, size_t, bool)) {}
  void writeValue(uint8_t *, size_t, bool) {}
};

class BLERemoteService {
public:
  BLERemoteCharacteristic *getCharacteristic(BLEUUID) { static BLERemoteCharacteristic c; return &c; }
};

class BLEClient;
class BLEClientCallbacks {
public:
  virtual ~BLEClientCallbacks() {}
  virtual void onConnect(BLEClient *) {}
  virtual void onDisconnect(BLEClient *) {}
};

extern int stubRssi;

class BLEClient {
public:
  void setClientCallbacks(BLEClientCallbacks *) {}
  bool connect(void *) { return true; }
  void disconnect() {}
  BLERemoteService *getService(BLEUUID) { static BLERemoteService s; return &s; }
  int getRssi() { return stubRssi; }
};

class BLEAdvertisedDevice {
public:
  BLEAdvertisedDevice() {}
  BLEAdvertisedDevice(const BLEAdvertisedDevice &) {}
  bool haveName() { return false; }
  std::string getName() { return ""; }
  BLEAddress getAddress() { return BLEAddress(); }
  int getRSSI() { return stubRssi; }
};

class BLEAdvertisedDeviceCallbacks {
public:
  virtual ~BLEAdvertisedDeviceCallbacks() {}
  virtual void onResult(BLEAdvertisedDevice) {}
};

class BLEScan {
public:
  void setAdvertisedDeviceCallbacks(BLEAdvertisedDeviceCallbacks *) {}
  void setActiveScan(bool) {}
  void setInterval(int) {}
  void setWindow(int) {}
  int start(int, bool) { return 0; }
  void clearResults() {}
  void stop() {}
};

class BLEDevice {
public:
  static void init(const char *) {}
  static BLEScan *getScan() { static BLEScan s; return &s; }
  static BLEClient *createClient() { static BLEClient c; return &c; }
};
