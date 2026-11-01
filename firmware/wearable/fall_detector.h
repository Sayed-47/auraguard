#ifndef LITTLE_SIGNAL_FALL_DETECTOR_H
#define LITTLE_SIGNAL_FALL_DETECTOR_H

#include <stdint.h>
#include <math.h>

// Bench-only heuristic. These example thresholds require sensor/mount calibration.
// Stages: 0 monitoring, 1 impact, 2 orientation, 3 stillness, 4 confirmed.
class FallDetector {
 public:
  uint8_t stage = 0;

  void reset() {
    stage = 0;
    baselineSamples = 0;
    bx = 0; by = 0; bz = 1;
    stillStarted = false;
  }

  void update(uint32_t now, float ax, float ay, float az,
              float gx, float gy, float gz) {
    const float norm = sqrtf(ax * ax + ay * ay + az * az);
    const float spin = sqrtf(gx * gx + gy * gy + gz * gz);
    if (!isfinite(norm) || !isfinite(spin) || norm < 0.05f) return;
    if (stage == 4) return; // Explicit reset on arm/disarm; acknowledge only mutes.

    if (stage == 0) {
      if (baselineSamples >= 25 && norm >= IMPACT_G) {
        stage = 1;
        impactAt = now;
        stillStarted = false;
        return;
      }
      if (fabsf(norm - 1.0f) < 0.2f && spin < 20.0f) {
        const float alpha = baselineSamples == 0 ? 1.0f : 0.08f;
        bx += alpha * (ax / norm - bx);
        by += alpha * (ay / norm - by);
        bz += alpha * (az / norm - bz);
        if (baselineSamples < 255) ++baselineSamples;
      }
      return;
    }

    if (uint32_t(now - impactAt) > MAX_SEQUENCE_MS) {
      reset();
      return;
    }

    if (stage == 1) {
      const float bnorm = sqrtf(bx * bx + by * by + bz * bz);
      const float cosine = (ax * bx + ay * by + az * bz) / (norm * bnorm);
      if (norm > 0.7f && norm < 1.3f && cosine < ORIENTATION_COS) {
        stage = 2;
      } else if (uint32_t(now - impactAt) > ORIENTATION_WINDOW_MS) {
        reset();
      }
      return;
    }

    const bool isStill = fabsf(norm - 1.0f) < STILL_G_TOLERANCE && spin < STILL_DPS;
    if (!isStill) {
      stage = 2;
      stillStarted = false; // Require two continuous seconds, not accumulated quiet.
      return;
    }
    if (!stillStarted) {
      stillStarted = true;
      stillAt = now;
      stage = 3;
    } else if (uint32_t(now - stillAt) >= STILL_MS) {
      stage = 4;
    }
  }

 private:
  static constexpr float IMPACT_G = 2.8f;
  static constexpr float ORIENTATION_COS = 0.70710678f; // 45 degrees.
  static constexpr float STILL_G_TOLERANCE = 0.12f;
  static constexpr float STILL_DPS = 8.0f;
  static const uint32_t ORIENTATION_WINDOW_MS = 1000;
  static const uint32_t STILL_MS = 2000;
  static const uint32_t MAX_SEQUENCE_MS = 5000;
  uint8_t baselineSamples = 0;
  float bx = 0, by = 0, bz = 1;
  uint32_t impactAt = 0, stillAt = 0;
  bool stillStarted = false;
};

#endif
