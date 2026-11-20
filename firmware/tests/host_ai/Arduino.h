/* Minimal Arduino API stubs for host-compiling the AI sketch with g++.
   Only what esp32_baby_unit_ai.ino uses. Not for hardware. */
#pragma once
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <cstdlib>
#include <cmath>
#include <string>
#include <iostream>

#define PI 3.14159265358979323846
#define degrees(rad) ((rad) * 180.0f / PI)
#define INPUT_PULLUP 0x2
#define INPUT 0x1
#define OUTPUT 0x3
#define HIGH 0x1
#define LOW 0x0

typedef uint8_t byte;

// scripted test doubles (defined in main.cpp)
extern unsigned long stubMillis;
extern unsigned long stubMicros;
extern const int *stubAdcScript;
extern int stubAdcLen;
extern int stubAdcPos;
extern int stubDigitalReadValue;

static inline unsigned long millis() { return stubMillis; }
static inline unsigned long micros() { return stubMicros += 50; }
static inline void delay(unsigned long ms) { stubMillis += ms; stubMicros += ms * 1000; }
static inline void delayMicroseconds(unsigned int us) { stubMicros += us; }
static inline void pinMode(int, int) {}
static inline int digitalRead(int) { return stubDigitalReadValue; }
static inline void digitalWrite(int, int) {}
static inline int analogRead(int) {
  if (stubAdcScript && stubAdcPos < stubAdcLen) return stubAdcScript[stubAdcPos++];
  return 2048;
}

struct StubSerial {
  void begin(unsigned long) {}
  template <typename... Args> void printf(const char *fmt, Args... args) { std::printf(fmt, args...); }
  template <typename T> void print(T v) { std::cout << v; }
  template <typename T> void println(T v) { std::cout << v << "\n"; }
  void println() { std::printf("\n"); }
};
extern StubSerial SerialStub;
#define Serial SerialStub

struct StubESP { void restart() { std::printf("[stub] ESP.restart()\n"); } };
extern StubESP ESP;
