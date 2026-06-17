/*
 * Pseudo-Random Square Wave Sync Pulse Generator
 * Nathan Baune
 *
 * Outputs a pseudo-random square wave on configurable pins.
 * The high and low durations are randomized within configurable
 * min/max ranges (in milliseconds). The pseudo-random pattern
 * has a sharp autocorrelation peak, making it ideal for
 * cross-correlation-based temporal alignment of multi-device
 * recordings (Vicon, EEG, etc.).
 *
 * Configuration:
 *   - Edit config.h for compile-time defaults
 *   - Use Serial commands at runtime to adjust
 *   - 'save' persists current settings to EEPROM
 *   - Settings survive power cycles after saving
 *
 * Voltage: 5V HIGH / 0V LOW (hardware fixed by ATmega32U4)
 *
 * Supported boards (both use ATmega32U4):
 *   - Arduino Leonardo          -- FQBN: arduino:avr:leonardo  (20 pins)
 *   - Pro Micro ATmega32U4 5V  -- FQBN: arduino:avr:micro      (18 pins)
 *     Define BOARD_PRO_MICRO in config.h or via compiler flag to select
 *     the Pro Micro pin layout.
 */

#include <EEPROM.h>
#include "config.h"

// ---- Pin setup ----
// Pro Micro (BOARD_PRO_MICRO): 18 pins — 0-10, 14-16, A0-A3
// Leonardo (default):          20 pins — 0-13, A0-A5
#ifdef BOARD_PRO_MICRO
const int OUTPUT_PINS[] = {0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 14, 15, 16, A0, A1, A2, A3};
#else
const int OUTPUT_PINS[] = {0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, A0, A1, A2, A3, A4, A5};
#endif
const int NUM_PINS = NUM_OUTPUT_PINS;

// ---- Runtime settings (loaded from EEPROM or config.h defaults) ----
unsigned long minHighMs;
unsigned long maxHighMs;
unsigned long minLowMs;
unsigned long maxLowMs;
unsigned long prngSeed;

// ---- State ----
bool outputState = LOW;
unsigned long nextToggleTime = 0;
bool running = true;

// ---- EEPROM layout ----
// Byte 0: magic, Bytes 1-20: settings
struct EepromData {
  uint8_t magic;
  uint32_t minHigh;
  uint32_t maxHigh;
  uint32_t minLow;
  uint32_t maxLow;
  uint32_t seed;
};

void loadDefaults() {
  minHighMs = DEFAULT_MIN_HIGH_MS;
  maxHighMs = DEFAULT_MAX_HIGH_MS;
  minLowMs  = DEFAULT_MIN_LOW_MS;
  maxLowMs  = DEFAULT_MAX_LOW_MS;
  prngSeed  = DEFAULT_PRNG_SEED;
}

bool loadFromEeprom() {
  EepromData data;
  EEPROM.get(0, data);
  if (data.magic != EEPROM_MAGIC) return false;
  minHighMs = data.minHigh;
  maxHighMs = data.maxHigh;
  minLowMs  = data.minLow;
  maxLowMs  = data.maxLow;
  prngSeed  = data.seed;
  return true;
}

void saveToEeprom() {
  EepromData data;
  data.magic   = EEPROM_MAGIC;
  data.minHigh = minHighMs;
  data.maxHigh = maxHighMs;
  data.minLow  = minLowMs;
  data.maxLow  = maxLowMs;
  data.seed    = prngSeed;
  EEPROM.put(0, data);
}

// ---- PRNG (xorshift32, deterministic) ----
uint32_t prngState;

void seedPrng(uint32_t seed) {
  prngState = seed ? seed : 1;
}

uint32_t prngNext() {
  prngState ^= prngState << 13;
  prngState ^= prngState >> 17;
  prngState ^= prngState << 5;
  return prngState;
}

unsigned long randomDuration(unsigned long minMs, unsigned long maxMs) {
  if (minMs >= maxMs) return minMs;
  uint32_t steps = (maxMs - minMs) / 5 + 1;   // 5 ms increments
  return minMs + (prngNext() % steps) * 5;
}

unsigned long computeNextDuration() {
  if (outputState == HIGH) {
    return randomDuration(minHighMs, maxHighMs);
  } else {
    return randomDuration(minLowMs, maxLowMs);
  }
}

void setOutput(bool state) {
  outputState = state;
  for (int i = 0; i < NUM_PINS; i++) {
    digitalWrite(OUTPUT_PINS[i], state);
  }
}

void printConfig() {
  Serial.println(F("=== Sync Pulse Generator Config ==="));
  Serial.print(F("  Seed:     ")); Serial.println(prngSeed);
  Serial.print(F("  High ms:  ")); Serial.print(minHighMs);
  Serial.print(F(" - "));          Serial.println(maxHighMs);
  Serial.print(F("  Low ms:   ")); Serial.print(minLowMs);
  Serial.print(F(" - "));          Serial.println(maxLowMs);
  Serial.print(F("  Voltage:  5V HIGH / 0V LOW"));
  Serial.println();
  Serial.print(F("  Pins:     "));
  for (int i = 0; i < NUM_PINS; i++) {
    Serial.print(OUTPUT_PINS[i]);
    if (i < NUM_PINS - 1) Serial.print(F(", "));
  }
  Serial.println();
  Serial.print(F("  Running:  ")); Serial.println(running ? "YES" : "NO");
  Serial.println(F("==================================="));
}

void printHelp() {
  Serial.println(F("Commands:"));
  Serial.println(F("  high <min> <max>  - Set high duration range (ms)"));
  Serial.println(F("  low <min> <max>   - Set low duration range (ms)"));
  Serial.println(F("  seed <value>      - Set PRNG seed & restart"));
  Serial.println(F("  save              - Save settings to EEPROM"));
  Serial.println(F("  reset             - Reset to config.h defaults"));
  Serial.println(F("  start             - Start output"));
  Serial.println(F("  stop              - Stop output (pins LOW)"));
  Serial.println(F("  restart           - Re-seed PRNG & restart"));
  Serial.println(F("  config            - Show current config"));
  Serial.println(F("  help              - Show this help"));
}

// ---- Serial command parsing ----
char cmdBuffer[64];
int cmdPos = 0;

void processCommand(const char* cmd) {
  char buf[64];
  strncpy(buf, cmd, sizeof(buf) - 1);
  buf[sizeof(buf) - 1] = '\0';

  char* token = strtok(buf, " ");
  if (!token) return;

  if (strcmp(token, "high") == 0) {
    char* sMin = strtok(NULL, " ");
    char* sMax = strtok(NULL, " ");
    if (sMin && sMax) {
      minHighMs = atol(sMin);
      maxHighMs = atol(sMax);
      Serial.print(F("High range: ")); Serial.print(minHighMs);
      Serial.print(F(" - ")); Serial.println(maxHighMs);
    } else {
      Serial.println(F("Usage: high <min> <max>"));
    }
  }
  else if (strcmp(token, "low") == 0) {
    char* sMin = strtok(NULL, " ");
    char* sMax = strtok(NULL, " ");
    if (sMin && sMax) {
      minLowMs = atol(sMin);
      maxLowMs = atol(sMax);
      Serial.print(F("Low range: ")); Serial.print(minLowMs);
      Serial.print(F(" - ")); Serial.println(maxLowMs);
    } else {
      Serial.println(F("Usage: low <min> <max>"));
    }
  }
  else if (strcmp(token, "seed") == 0) {
    char* sVal = strtok(NULL, " ");
    if (sVal) {
      prngSeed = atol(sVal);
      seedPrng(prngSeed);
      outputState = LOW;
      setOutput(LOW);
      nextToggleTime = millis();
      Serial.print(F("Seed set to ")); Serial.print(prngSeed);
      Serial.println(F(", PRNG restarted"));
    } else {
      Serial.println(F("Usage: seed <value>"));
    }
  }
  else if (strcmp(token, "save") == 0) {
    saveToEeprom();
    Serial.println(F("Settings saved to EEPROM"));
  }
  else if (strcmp(token, "reset") == 0) {
    loadDefaults();
    seedPrng(prngSeed);
    outputState = LOW;
    setOutput(LOW);
    nextToggleTime = millis();
    running = true;
    Serial.println(F("Reset to config.h defaults (use 'save' to persist)"));
    printConfig();
  }
  else if (strcmp(token, "start") == 0) {
    running = true;
    seedPrng(prngSeed);
    outputState = LOW;
    setOutput(LOW);
    nextToggleTime = millis();
    Serial.println(F("Started (PRNG re-seeded)"));
  }
  else if (strcmp(token, "stop") == 0) {
    running = false;
    setOutput(LOW);
    Serial.println(F("Stopped"));
  }
  else if (strcmp(token, "restart") == 0) {
    seedPrng(prngSeed);
    outputState = LOW;
    setOutput(LOW);
    nextToggleTime = millis();
    running = true;
    Serial.println(F("Restarted with same seed"));
  }
  else if (strcmp(token, "config") == 0) {
    printConfig();
  }
  else if (strcmp(token, "help") == 0) {
    printHelp();
  }
  else {
    Serial.print(F("Unknown command: ")); Serial.println(token);
    Serial.println(F("Type 'help' for commands"));
  }
}

// ---- Arduino lifecycle ----

void setup() {
  for (int i = 0; i < NUM_PINS; i++) {
    pinMode(OUTPUT_PINS[i], OUTPUT);
    digitalWrite(OUTPUT_PINS[i], LOW);
  }
  Serial.begin(115200);
  unsigned long waitStart = millis();
  while (!Serial && (millis() - waitStart < 3000)) {
    ;
  }

  // Load settings: EEPROM if valid, otherwise config.h defaults
  if (!loadFromEeprom()) {
    loadDefaults();
    Serial.println(F("Loaded defaults from config.h"));
  } else {
    Serial.println(F("Loaded settings from EEPROM"));
  }

  seedPrng(prngSeed);

  Serial.println(F("Sync Pulse Generator Ready"));
  printConfig();
  printHelp();

  nextToggleTime = millis();
}

void loop() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n' || c == '\r') {
      if (cmdPos > 0) {
        cmdBuffer[cmdPos] = '\0';
        processCommand(cmdBuffer);
        cmdPos = 0;
      }
    } else if (cmdPos < (int)(sizeof(cmdBuffer) - 1)) {
      cmdBuffer[cmdPos++] = c;
    }
  }

  if (running && millis() >= nextToggleTime) {
    outputState = !outputState;
    setOutput(outputState);
    unsigned long duration = computeNextDuration();
    nextToggleTime = millis() + duration;
  }
}
