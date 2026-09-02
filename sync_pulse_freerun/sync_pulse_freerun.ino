/*
 * Pseudo-Random Square Wave Sync Pulse Generator — FREE-RUN-ONLY BUILD
 * Nathan Baune
 *
 * Identical to ../sync_pulse_generator in every respect that reaches the
 * wire — same PRNG, same seed, same timecode frames, same persistent run
 * counter, same serial commands — except that there is no trigger input and
 * no mode switch. Output begins at power-up and continues while powered.
 *
 * Use this build when the box has no TRIG BNC and no panel toggle fitted.
 *
 * WHY THIS BUILD EXISTS. In the full firmware MODE_SWITCH_PIN is an
 * INPUT_PULLUP and MODE_FREE_IS_LOW is 1, so closed-to-ground means FREE RUN.
 * An UNWIRED switch pin therefore floats HIGH and reads as TRIG RUN: the
 * outputs are held LOW waiting for a trigger that never arrives, and the box
 * sits silent with no indication that anything is wrong. On hardware with no
 * switch fitted that is the default state, not an edge case. Compiling the
 * trigger code out removes the failure entirely rather than relying on the
 * pin being tied correctly.
 *
 * Two further consequences, both benign:
 *   - TRIG_IN_PIN and MODE_SWITCH_PIN (2 and 3) are excluded from the output
 *     set in the full firmware; here they carry the signal like any other pin.
 *   - Nothing reads a floating input, so no unwired pin is ever sampled.
 *
 * The emitted waveform is byte-identical to the full firmware running in FREE
 * RUN, so recordings made with either build align against the same template
 * and are interchangeable.
 *
 * Outputs a pseudo-random square wave on configurable pins. The high and low
 * durations are randomized within configurable min/max ranges (in
 * milliseconds), interrupted every TC_INTERVAL_S by a timecode frame carrying
 * the run ID and elapsed seconds.
 *
 * Voltage: 5V HIGH / 0V LOW (hardware fixed by ATmega32U4)
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

#if TRIG_FEATURE
bool isReservedPin(int p) { return p == TRIG_IN_PIN || p == MODE_SWITCH_PIN; }
#else
bool isReservedPin(int p) { (void)p; return false; }
#endif

// ---- Runtime settings (loaded from EEPROM or config.h defaults) ----
unsigned long minHighMs;
unsigned long maxHighMs;
unsigned long minLowMs;
unsigned long maxLowMs;
unsigned long prngSeed;
bool tcEnabled;
unsigned long tcIntervalS;

// ---- State ----
bool outputState = LOW;
unsigned long nextToggleTime = 0;
bool running = true;

// Timecode frame state. A frame is 55 pulses / 54 gaps = 109 alternating
// segments (even = pulse HIGH, odd = gap LOW). Segments 1,3 are preamble
// gaps; odd segments 5..107 carry the 52 payload bits MSB-first.
enum RunMode { MODE_PR, MODE_LEADIN, MODE_FRAME };
RunMode mode = MODE_PR;
bool leadinPending = false;   // current PR segment was clamped at the lead-in start
uint8_t  frameSeg = 0;
uint64_t framePayload = 0;          // 52 bits: runId<<36 | elapsed<<4 | cksum
uint16_t runId = 0;                 // EEPROM boot counter, ++ per PRNG start
unsigned long runStartMs = 0;       // when the PRNG (re)started
unsigned long nextFrameDueMs = 0;

// ---- EEPROM layout ----
// Byte 0: magic, Bytes 1-20: settings
struct EepromData {
  uint8_t magic;
  uint32_t minHigh;
  uint32_t maxHigh;
  uint32_t minLow;
  uint32_t maxLow;
  uint32_t seed;
  uint8_t  tcEnabled;
  uint32_t tcIntervalS;
};

void loadDefaults() {
  minHighMs   = DEFAULT_MIN_HIGH_MS;
  maxHighMs   = DEFAULT_MAX_HIGH_MS;
  minLowMs    = DEFAULT_MIN_LOW_MS;
  maxLowMs    = DEFAULT_MAX_LOW_MS;
  prngSeed    = DEFAULT_PRNG_SEED;
  tcEnabled   = DEFAULT_TC_ENABLED;
  tcIntervalS = DEFAULT_TC_INTERVAL_S;
}

bool loadFromEeprom() {
  EepromData data;
  EEPROM.get(0, data);
  if (data.magic != EEPROM_MAGIC) return false;
  minHighMs   = data.minHigh;
  maxHighMs   = data.maxHigh;
  minLowMs    = data.minLow;
  maxLowMs    = data.maxLow;
  prngSeed    = data.seed;
  tcEnabled   = data.tcEnabled != 0;
  tcIntervalS = data.tcIntervalS;
  return true;
}

void saveToEeprom() {
  EepromData data;
  data.magic       = EEPROM_MAGIC;
  data.minHigh     = minHighMs;
  data.maxHigh     = maxHighMs;
  data.minLow      = minLowMs;
  data.maxLow      = maxLowMs;
  data.seed        = prngSeed;
  data.tcEnabled   = tcEnabled ? 1 : 0;
  data.tcIntervalS = tcIntervalS;
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
    if (isReservedPin(OUTPUT_PINS[i])) continue;
    digitalWrite(OUTPUT_PINS[i], state);
  }
}

// (Re)start a fresh run: re-seed, outputs LOW, new run ID.
void startNewRun() {
  seedPrng(prngSeed);
  outputState = LOW;
  setOutput(LOW);
  nextToggleTime = millis();
  resetRunClock();
  running = true;
}

// ---- Timecode frames ----
// XOR of the eight 4-bit nibbles of the payload value.
uint8_t checksum4(uint32_t v) {
  uint8_t c = 0;
  for (uint8_t i = 0; i < 8; i++) { c ^= v & 0xF; v >>= 4; }
  return c;
}

// Reset the run clock + frame schedule (called wherever the PRNG restarts).
// Each call is a new RUN: the persistent counter increments so (runId,
// elapsed) stays globally unique across restarts and power cycles.
void resetRunClock() {
  uint16_t counter;
  EEPROM.get(EEPROM_RUNID_ADDR, counter);
  if (counter == 0xFFFF) counter = 0;   // fresh EEPROM
  counter++;
  EEPROM.put(EEPROM_RUNID_ADDR, counter);
  runId = counter;
  runStartMs = millis();
  nextFrameDueMs = runStartMs + tcIntervalS * 1000UL;
  mode = MODE_PR;
  leadinPending = false;
}

// Begin emitting a frame: first preamble pulse goes HIGH now — ON the tick,
// so the encoded elapsed time is exact by construction.
void startFrame() {
  uint32_t elapsedS = (nextFrameDueMs - runStartMs) / 1000UL;
  uint8_t chk = checksum4(elapsedS) ^ checksum4(runId);
  framePayload = ((uint64_t)runId << 36) | ((uint64_t)elapsedS << 4) | chk;
  frameSeg = 0;
  mode = MODE_FRAME;
  setOutput(HIGH);
  nextToggleTime = millis() + TC_PULSE_MS;
}

// Duration of frame segment `seg` (0..108). Even = pulse, odd = gap.
unsigned long frameSegmentDuration(uint8_t seg) {
  if (seg % 2 == 0) return TC_PULSE_MS;
  if (seg < 4) return TC_PREAMBLE_GAP_MS;          // gaps 1, 3
  uint8_t bitIdx = (seg - 5) / 2;                  // odd segs 5..107 -> 0..51
  bool bit = (framePayload >> (51 - bitIdx)) & 1;
  return bit ? TC_GAP_ONE_MS : TC_GAP_ZERO_MS;
}

// Hold LOW until the frame tick; the frame's first pulse then rises ON it.
void enterLeadIn() {
  outputState = LOW;
  setOutput(LOW);
  mode = MODE_LEADIN;
  nextToggleTime = nextFrameDueMs;
}

// Schedule the pseudo-random segment for the state just set. The PRNG draw
// ALWAYS happens (reproducibility); the segment is clamped to end at the
// lead-in start if it would cross it.
void schedulePrSegment() {
  unsigned long d = computeNextDuration();
  unsigned long now = millis();
  if (tcEnabled) {
    long remaining = (long)(nextFrameDueMs - TC_LEADIN_MS - now);
    if (remaining <= 0) { enterLeadIn(); return; }          // loop ran late
    if ((long)d > remaining) {
      nextToggleTime = now + remaining;
      leadinPending = true;
      return;
    }
  }
  nextToggleTime = now + d;
}

// Next frame tick strictly ahead of now (+lead-in) on the run's interval
// grid — used when timecode is switched on or the interval changes mid-run,
// so a stack of overdue frames is never emitted back-to-back.
void scheduleNextFrame() {
  unsigned long period = tcIntervalS * 1000UL;
  unsigned long elapsed = millis() - runStartMs + TC_LEADIN_MS;
  nextFrameDueMs = runStartMs + (elapsed / period + 1) * period;
  leadinPending = false;
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
  Serial.print(F("  Run ID:   ")); Serial.println(runId);
  Serial.print(F("  Timecode: "));
  if (tcEnabled) {
    Serial.print(F("ON, frame every "));
    Serial.print(tcIntervalS);
    Serial.println(F(" s"));
  } else {
    Serial.println(F("OFF (pure pseudo-random)"));
  }
  Serial.print(F("  Pins:     "));
  for (int i = 0; i < NUM_PINS; i++) {
    Serial.print(OUTPUT_PINS[i]);
    if (i < NUM_PINS - 1) Serial.print(F(", "));
  }
  Serial.println();
#if TRIG_FEATURE
  Serial.print(F("  Mode:     "));
  Serial.println(digitalRead(MODE_SWITCH_PIN) == LOW
                 ? (MODE_FREE_IS_LOW ? F("FREE RUN") : F("TRIG RUN"))
                 : (MODE_FREE_IS_LOW ? F("TRIG RUN") : F("FREE RUN")));
#endif
  Serial.print(F("  Running:  ")); Serial.println(running ? "YES" : "NO");
  Serial.println(F("==================================="));
}

void printHelp() {
  Serial.println(F("Commands:"));
  Serial.println(F("  high <min> <max>  - Set high duration range (ms)"));
  Serial.println(F("  low <min> <max>   - Set low duration range (ms)"));
  Serial.println(F("  seed <value>      - Set PRNG seed & restart"));
  Serial.println(F("  tc on|off         - Timecode frames on/off"));
  Serial.println(F("  tcint <seconds>   - Seconds between timecode frames"));
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
      resetRunClock();
      Serial.print(F("Seed set to ")); Serial.print(prngSeed);
      Serial.println(F(", PRNG restarted"));
    } else {
      Serial.println(F("Usage: seed <value>"));
    }
  }
  else if (strcmp(token, "tc") == 0) {
    char* sVal = strtok(NULL, " ");
    if (sVal && strcmp(sVal, "on") == 0) {
      tcEnabled = true;
      if (running) scheduleNextFrame();
      Serial.println(F("Timecode frames ON"));
    } else if (sVal && strcmp(sVal, "off") == 0) {
      tcEnabled = false;
      Serial.println(F("Timecode frames OFF"));
    } else {
      Serial.println(F("Usage: tc on|off"));
    }
  }
  else if (strcmp(token, "tcint") == 0) {
    char* sVal = strtok(NULL, " ");
    if (sVal && atol(sVal) >= 2) {          // a frame is ~1.65 s + lead-in
      tcIntervalS = atol(sVal);
      if (running) scheduleNextFrame();
      Serial.print(F("Timecode interval: "));
      Serial.print(tcIntervalS);
      Serial.println(F(" s"));
    } else {
      Serial.println(F("Usage: tcint <seconds>  (2 or more)"));
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
    resetRunClock();
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
    resetRunClock();
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
    resetRunClock();
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
    if (isReservedPin(OUTPUT_PINS[i])) continue;
    pinMode(OUTPUT_PINS[i], OUTPUT);
    digitalWrite(OUTPUT_PINS[i], LOW);
  }
#if TRIG_FEATURE
  pinMode(TRIG_IN_PIN, INPUT_PULLUP);
  pinMode(MODE_SWITCH_PIN, INPUT_PULLUP);
#endif
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
  resetRunClock();
}

#if TRIG_FEATURE
bool trigMode = false;
unsigned long trigLowSince = 0;

void serviceTrigger() {
  bool swLow = digitalRead(MODE_SWITCH_PIN) == LOW;
  bool nowTrig = (swLow != (bool)MODE_FREE_IS_LOW);
  if (nowTrig != trigMode) {
    trigMode = nowTrig;
    if (trigMode) {
      running = false;
      setOutput(LOW);
      trigLowSince = 0;
      Serial.println(F("TRIG mode: outputs held LOW, waiting for TRIG IN"));
    } else {
      startNewRun();
      Serial.println(F("FREE RUN mode: started"));
    }
  }
  if (trigMode && !running) {
    if (digitalRead(TRIG_IN_PIN) == LOW) {
      if (trigLowSince == 0) trigLowSince = millis();
    } else {
      if (trigLowSince != 0 &&
          millis() - trigLowSince >= TRIG_ARM_LOW_MS) {
        startNewRun();
        Serial.println(F("Triggered!"));
      }
      trigLowSince = 0;
    }
  }
}
#endif

void loop() {
#if TRIG_FEATURE
  serviceTrigger();
#endif
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
    if (mode == MODE_FRAME) {
      // advance through the frame's 109 alternating segments
      frameSeg++;
      if (frameSeg > 108) {
        // frame done (ended on a pulse) — drop LOW and resume pseudo-random
        mode = MODE_PR;
        setOutput(LOW);
        schedulePrSegment();
      } else {
        setOutput(frameSeg % 2 == 0 ? HIGH : LOW);
        nextToggleTime = millis() + frameSegmentDuration(frameSeg);
      }
    } else if (mode == MODE_LEADIN) {
      // ON the tick: the first preamble pulse rises now
      startFrame();
      nextFrameDueMs += tcIntervalS * 1000UL;
    } else if (leadinPending) {
      // the clamped segment just ended at the lead-in start
      leadinPending = false;
      enterLeadIn();
    } else {
      bool next = !outputState;
      if (tcEnabled && next == HIGH &&
          (long)(nextFrameDueMs - TC_LEADIN_MS - millis()) < (long)TC_PULSE_MS) {
        // too close to the lead-in for a real pulse: stay LOW into it
        enterLeadIn();
      } else {
        setOutput(next);
        schedulePrSegment();
      }
    }
  }
}
