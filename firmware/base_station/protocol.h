#ifndef LITTLE_SIGNAL_PROTOCOL_H
#define LITTLE_SIGNAL_PROTOCOL_H

#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <ctype.h>
#include <errno.h>

struct WearableFrame {
  uint32_t sequence, uptime;
  bool valid;
  int16_t motion[6];
  uint8_t stage;
};

static bool parseUnsigned(const char *&p, uint32_t &out) {
  if (!isdigit((unsigned char)*p)) return false;
  char *end;
  errno = 0;
  unsigned long value = strtoul(p, &end, 10);
  if (errno || value > UINT32_MAX) return false;
  out = uint32_t(value);
  p = end;
  return true;
}

static bool parseFrame(const char *line, WearableFrame &out) {
  if (strncmp(line, "LS1,", 4) != 0) return false;
  const char *p = line + 4;
  WearableFrame frame;
  uint32_t valid, stage;
  if (!parseUnsigned(p, frame.sequence) || *p++ != ',' ||
      !parseUnsigned(p, frame.uptime) || *p++ != ',' ||
      !parseUnsigned(p, valid) || valid > 1 || *p++ != ',') return false;
  for (uint8_t i = 0; i < 6; ++i) {
    if (*p != '-' && !isdigit((unsigned char)*p)) return false;
    char *end;
    errno = 0;
    long value = strtol(p, &end, 10);
    const long limit = i < 3 ? 16000 : 20000;
    if (errno || end == p || value < -limit || value > limit || *end != ',')
      return false;
    frame.motion[i] = int16_t(value);
    p = end + 1;
  }
  if (!parseUnsigned(p, stage) || stage > 4 || *p != 0) return false;
  frame.valid = valid == 1;
  frame.stage = uint8_t(stage);
  out = frame; // Never partially modify the last valid measurement.
  return true;
}

struct Command {
  char id[65];
  char action[16];
};

static void skipSpace(const char *&p) {
  while (*p == ' ' || *p == '\t' || *p == '\r') ++p;
}

static bool readString(const char *&p, char *out, size_t capacity) {
  if (*p++ != '"') return false;
  size_t n = 0;
  while (*p && *p != '"') {
    const unsigned char c = (unsigned char)*p++;
    // The control protocol requires plain ASCII identifiers, not JSON escapes.
    if (c < 0x20 || c > 0x7E || c == '\\' || n + 1 >= capacity) return false;
    out[n++] = char(c);
  }
  if (*p++ != '"') return false;
  out[n] = 0;
  return true;
}

// Strict, allocation-free parser for this four-field flat command protocol.
static bool parseCommand(const char *line, Command &out) {
  const char *p = line;
  skipSpace(p);
  if (*p++ != '{') return false;
  bool seenType = false, seenId = false, seenAction = false, seenSeconds = false;
  Command command = {};
  while (true) {
    skipSpace(p);
    char key[12], value[65];
    if (!readString(p, key, sizeof(key))) return false;
    skipSpace(p);
    if (*p++ != ':') return false;
    skipSpace(p);
    if (strcmp(key, "seconds") == 0) {
      uint32_t seconds;
      if (seenSeconds || !parseUnsigned(p, seconds) || seconds != 15) return false;
      seenSeconds = true;
    } else {
      if (!readString(p, value, sizeof(value))) return false;
      if (strcmp(key, "type") == 0) {
        if (seenType || strcmp(value, "command") != 0) return false;
        seenType = true;
      } else if (strcmp(key, "id") == 0) {
        if (seenId || !*value) return false;
        for (const char *q = value; *q; ++q)
          if (!isalnum((unsigned char)*q) && *q != '-' && *q != '_') return false;
        strcpy(command.id, value);
        seenId = true;
      } else if (strcmp(key, "action") == 0) {
        if (seenAction || (strcmp(value, "arm") && strcmp(value, "disarm") &&
                           strcmp(value, "acknowledge"))) return false;
        strcpy(command.action, value);
        seenAction = true;
      } else return false;
    }
    skipSpace(p);
    if (*p == '}') { ++p; break; }
    if (*p++ != ',') return false;
  }
  skipSpace(p);
  if (*p || !seenType || !seenId || !seenAction ||
      (seenSeconds && strcmp(command.action, "acknowledge"))) return false;
  out = command;
  return true;
}

#endif
