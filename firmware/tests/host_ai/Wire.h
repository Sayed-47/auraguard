/* Minimal TwoWire stub for host compilation. I2C transactions are no-ops;
   tests fill the motion ring buffers directly instead of scripting the bus. */
#pragma once
#include "Arduino.h"

class TwoWire {
public:
  void begin(int = -1, int = -1) {}
  void end() {}
  void setClock(unsigned long) {}
  void beginTransmission(int) {}
  size_t write(uint8_t) { return 1; }
  uint8_t endTransmission(bool = true) { return 0; }
  size_t requestFrom(int, int) { return 0; }
  int read() { return 0; }
};
extern TwoWire Wire;
