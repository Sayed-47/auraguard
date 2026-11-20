/* Host cross-validation of the AI sketch against the Python reference.
   Feeds generated vectors through the sketch's own C feature+inference code
   and compares probabilities; also exercises the AI fall gate end to end. */
#include <fstream>
#include <sstream>
#include <vector>
#include <string>

#include "Arduino.h"
#include "Wire.h"
#include "BLEDevice.h"

// stub globals
unsigned long stubMillis = 100000;
unsigned long stubMicros = 100000000;
const int *stubAdcScript = nullptr;
int stubAdcLen = 0;
int stubAdcPos = 0;
int stubDigitalReadValue = HIGH;
int stubRssi = -60;
StubSerial SerialStub;
StubESP ESP;
TwoWire Wire;

// symbols defined by the sketch
extern float ringAx[], ringAy[], ringAz[], ringSvm[], ringGmag[];
extern int ringPos, ringFill;
extern int burstPos, burstCount;
extern unsigned long cooldownUntil;
int motionFeatures(float *feat);
int classifyMotion(float *probs);
void captureBurst();
float classifyCry();
void evaluateCandidate(unsigned long now, bool stillOk);

#define MOTION_N 100
#define AUDIO_BURSTS 8
#define AUDIO_N 128

static std::vector<double> parseCsvLine(const std::string &line) {
  std::vector<double> out;
  std::stringstream ss(line);
  std::string cell;
  while (std::getline(ss, cell, ',')) out.push_back(std::stod(cell));
  return out;
}

static int failures = 0;
static void check(bool ok, const char *what) {
  if (!ok) { failures++; std::printf("FAIL: %s\n", what); }
}

int main(int argc, char **argv) {
  std::string dir = argc > 1 ? argv[1] : ".";
  char msg[160];

  // ---- motion vectors: label,p0,p1,p2, then 100 x (ax,ay,az,svm,gmag) ----
  {
    std::ifstream fh(dir + "/motion_vectors.csv");
    std::string line;
    int n = 0;
    while (std::getline(fh, line)) {
      if (line.empty()) continue;
      auto v = parseCsvLine(line);
      ringPos = 0; ringFill = 0;
      for (int i = 0; i < MOTION_N; i++) {
        ringAx[i] = (float)v[4 + i * 5 + 0];
        ringAy[i] = (float)v[4 + i * 5 + 1];
        ringAz[i] = (float)v[4 + i * 5 + 2];
        ringSvm[i] = (float)v[4 + i * 5 + 3];
        ringGmag[i] = (float)v[4 + i * 5 + 4];
      }
      ringFill = MOTION_N; ringPos = 0;
      float probs[3];
      classifyMotion(probs);
      for (int c = 0; c < 3; c++) {
        double diff = std::fabs(probs[c] - v[1 + c]);
        if (diff > 1e-3) {
          std::snprintf(msg, sizeof msg, "motion row %d class %d: C=%.6f python=%.6f", n, c, probs[c], v[1 + c]);
          check(false, msg);
        }
      }
      int expect = (int)v[0];
      int best = 0;
      for (int c = 1; c < 3; c++) if (probs[c] > probs[best]) best = c;
      if (best != expect) {
        std::snprintf(msg, sizeof msg, "motion row %d: predicted %d expected %d", n, best, expect);
        check(false, msg);
      }
      n++;
    }
    std::printf("motion vectors: %d checked\n", n);
    check(n == 12, "expected 12 motion vectors");
  }

  // ---- cry vectors: label,prob, then 8 x 128 raw ADC counts ----
  {
    std::ifstream fh(dir + "/cry_vectors.csv");
    std::string line;
    int n = 0;
    static int adc[AUDIO_N];
    while (std::getline(fh, line)) {
      if (line.empty()) continue;
      auto v = parseCsvLine(line);
      burstPos = 0; burstCount = 0;
      for (int b = 0; b < AUDIO_BURSTS; b++) {
        for (int i = 0; i < AUDIO_N; i++) adc[i] = (int)v[2 + b * AUDIO_N + i];
        stubAdcScript = adc; stubAdcLen = AUDIO_N; stubAdcPos = 0;
        captureBurst();
      }
      float prob = classifyCry();
      double diff = std::fabs(prob - v[1]);
      if (diff > 2e-3) {
        std::snprintf(msg, sizeof msg, "cry row %d: C=%.6f python=%.6f", n, prob, v[1]);
        check(false, msg);
      }
      int predicted = prob >= 0.5 ? 1 : 0;
      if (predicted != (int)v[0]) {
        std::snprintf(msg, sizeof msg, "cry row %d: predicted %d expected %d (p=%.3f)", n, predicted, (int)v[0], prob);
        check(false, msg);
      }
      n++;
    }
    std::printf("cry vectors: %d checked\n", n);
    check(n == 12, "expected 12 cry vectors");
  }

  // ---- AI fall gate behavior (fusion rules compiled into the sketch) ----
  {
    std::ifstream fh(dir + "/motion_vectors.csv");
    std::string line;
    std::vector<std::vector<double>> rows;
    while (std::getline(fh, line)) if (!line.empty()) rows.push_back(parseCsvLine(line));
    auto loadRing = [&](const std::vector<double> &v) {
      ringPos = 0; ringFill = 0;
      for (int i = 0; i < MOTION_N; i++) {
        ringAx[i] = (float)v[4 + i * 5 + 0];
        ringAy[i] = (float)v[4 + i * 5 + 1];
        ringAz[i] = (float)v[4 + i * 5 + 2];
        ringSvm[i] = (float)v[4 + i * 5 + 3];
        ringGmag[i] = (float)v[4 + i * 5 + 4];
      }
      ringFill = MOTION_N; ringPos = 0;
    };
    // FALL sent -> cooldown set to now+5000; veto/ignore -> now+1000 (sketch constants)
    const unsigned long SENT = stubMillis + 5000, NOT_SENT = stubMillis + 1000;
    int falls = 0, vetoes = 0;
    for (auto &v : rows) {
      if ((int)v[0] != 2) continue;
      loadRing(v);
      cooldownUntil = 0;
      evaluateCandidate(stubMillis, true);
      if (cooldownUntil != SENT) { std::snprintf(msg, sizeof msg, "fall window: no FALL sent (cooldown=%lu)", cooldownUntil); check(false, msg); }
      falls++;
    }
    for (auto &v : rows) {
      if ((int)v[0] != 1) continue;
      loadRing(v);
      cooldownUntil = 0;
      evaluateCandidate(stubMillis, false);
      if (cooldownUntil != NOT_SENT) { std::snprintf(msg, sizeof msg, "active window: FALL wrongly sent"); check(false, msg); }
      vetoes++;
    }
    std::printf("fall gate: %d falls sent, %d active windows vetoed\n", falls, vetoes);
    check(falls == 4, "all 4 fall windows should send FALL");
    check(vetoes == 4, "all 4 active windows should be vetoed");
  }

  if (failures) { std::printf("HOST CROSS-CHECK FAILED: %d failure(s)\n", failures); return 1; }
  std::printf("HOST CROSS-CHECK PASSED\n");
  return 0;
}
