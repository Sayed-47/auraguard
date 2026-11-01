#include <cassert>
#include <cstring>
#include <iostream>
#include "../wearable/fall_detector.h"
#include "../base_station/protocol.h"

static uint32_t baseline(FallDetector &d, uint32_t start = 1000) {
  for (unsigned i = 0; i < 50; ++i) d.update(start + i * 20, 0, 0, 1, 0, 0, 0);
  return start + 1000;
}

int main() {
  FallDetector d;
  uint32_t t = baseline(d);
  d.update(t, 0, 0, 3.5f, 0, 0, 0); assert(d.stage == 1);
  d.update(t + 20, 1, 0, 0, 0, 0, 0); assert(d.stage == 2);
  d.update(t + 40, 1, 0, 0, 0, 0, 0); assert(d.stage == 3);
  d.update(t + 2039, 1, 0, 0, 0, 0, 0); assert(d.stage == 3);
  d.update(t + 2040, 1, 0, 0, 0, 0, 0); assert(d.stage == 4);
  d.update(t + 9000, 0, 0, 1, 0, 0, 0); assert(d.stage == 4);
  d.reset(); assert(d.stage == 0);

  t = baseline(d);
  d.update(t, 0, 0, 3.5f, 0, 0, 0);
  d.update(t + 1001, 0, 0, 1, 0, 0, 0); assert(d.stage == 0); // Impact alone.
  t = baseline(d);
  d.update(t, 0, 0, 3.5f, 0, 0, 0);
  d.update(t + 20, 1, 0, 0, 0, 0, 0);
  d.update(t + 40, 1, 0, 0, 0, 0, 0);
  d.update(t + 1900, 1, 0, 0, 20, 0, 0); assert(d.stage == 2);
  d.update(t + 1920, 1, 0, 0, 0, 0, 0);
  d.update(t + 2100, 1, 0, 0, 0, 0, 0); assert(d.stage == 3); // Stillness reset.
  d.update(t + 3920, 1, 0, 0, 0, 0, 0); assert(d.stage == 4);

  d.reset();
  t = baseline(d, UINT32_MAX - 1500);
  d.update(t, 0, 0, 3.5f, 0, 0, 0);
  d.update(t + 20, 1, 0, 0, 0, 0, 0);
  d.update(t + 40, 1, 0, 0, 0, 0, 0);
  d.update(t + 2040, 1, 0, 0, 0, 0, 0); assert(d.stage == 4); // millis rollover.

  WearableFrame f = {};
  assert(parseFrame("LS1,42,3000,1,-120,50,1000,10,-20,0,4", f));
  assert(f.sequence == 42 && f.stage == 4 && f.motion[0] == -120);
  assert(parseFrame("LS1,4294967295,4294967295,0,0,0,0,0,0,0,0", f));
  assert(!parseFrame("LS1,42,3000,1,-120,50,99999,10,-20,0,4", f));
  assert(!parseFrame("LS1,42,3000,1,-120,50,1000,10,-20,0,4,evil", f));
  assert(!parseFrame("LS1,42,3000,1,-120,50,1000,10,-20,0", f));
  assert(!parseFrame("LS1,42,3000,1,-120,50,1000,10,-20,nan,4", f));
  assert(!parseFrame("LS1,42,3000,1,-120,50,1000,10,-20,0,9", f));
  assert(!parseFrame("LS1,4294967296,3000,1,0,0,1000,0,0,0,0", f));

  Command c;
  assert(parseCommand("{\"type\":\"command\",\"id\":\"cmd-123\",\"action\":\"arm\"}", c));
  assert(!strcmp(c.id, "cmd-123") && !strcmp(c.action, "arm"));
  assert(parseCommand("{ \"id\" : \"cmd-123\", \"type\":\"command\", \"action\":\"acknowledge\",\"seconds\":15 }", c));
  assert(!parseCommand("{\"type\":\"command\",\"id\":\"cmd-123\",\"action\":\"arm\",\"action\":\"disarm\"}", c));
  assert(!parseCommand("{\"type\":\"command\",\"id\":\"bad\\\"id\",\"action\":\"arm\"}", c));
  assert(!parseCommand("{\"type\":\"command\",\"id\":\"cmd-123\",\"action\":\"acknowledge\",\"seconds\":1500}", c));
  assert(!parseCommand("{\"type\":\"command\",\"id\":\"cmd-123\",\"action\":\"arm\"}garbage", c));
  assert(!parseCommand("{\"type\":\"command\",\"id\":\"cmd-123\",\"action\":\"arm\",}", c));
  std::cout << "Detector timing, reset, rollover, frame bounds, and command parser checks passed.\n";
}
