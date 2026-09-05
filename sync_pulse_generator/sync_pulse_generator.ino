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

#if TRIG_FEATURE
bool isReservedPin(int p) {
  if (p == TRIG_IN_PIN || p == MODE_SWITCH_PIN) return true;
#if EVENT_CHANNEL_ENABLED
  // The event channel is driven independently, so it must not be swept along
  // with the train by setOutput().
  if (p == EVENT_CHANNEL_PIN) return true;
#endif
  return false;
}
#else
bool isReservedPin(int p) {
  (void)p;
#if EVENT_CHANNEL_ENABLED
  if (p == EVENT_CHANNEL_PIN) return true;
#endif
  return false;
}
#endif

// ---- Runtime settings (loaded from EEPROM or config.h defaults) ----
unsigned long minHighMs;
unsigned long maxHighMs;
unsigned long minLowMs;
unsigned long maxLowMs;
unsigned long prngSeed;
bool tcEnabled;
unsigned long tcIntervalS;
uint8_t  trigMode_cfg;          // TRIG_MODE_* — what TRIG IN does
bool     leadinPulseEnabled;    // emit a marker pulse on trigger
unsigned long leadinPulseMs;    // its width
unsigned long leadinPauseMs;    // LOW hold after it, before the train

// ---- State ----
bool outputState = LOW;
unsigned long nextToggleTime = 0;
bool running = true;

// Timecode frame state. A frame is 55 pulses / 54 gaps = 109 alternating
// segments (even = pulse HIGH, odd = gap LOW). Segments 1,3 are preamble
// gaps; odd segments 5..107 carry the 52 payload bits MSB-first.
enum RunMode { MODE_PR, MODE_LEADIN, MODE_FRAME, MODE_MARK, MODE_MARKPAUSE };
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
  uint8_t  trigMode;
  uint8_t  leadinEnabled;
  uint32_t leadinPulseMs;
  uint32_t leadinPauseMs;
};

void loadDefaults() {
  minHighMs   = DEFAULT_MIN_HIGH_MS;
  maxHighMs   = DEFAULT_MAX_HIGH_MS;
  minLowMs    = DEFAULT_MIN_LOW_MS;
  maxLowMs    = DEFAULT_MAX_LOW_MS;
  prngSeed    = DEFAULT_PRNG_SEED;
  tcEnabled   = DEFAULT_TC_ENABLED;
  tcIntervalS = DEFAULT_TC_INTERVAL_S;
  trigMode_cfg       = DEFAULT_TRIG_MODE;
  leadinPulseEnabled = DEFAULT_LEADIN_PULSE_ENABLED;
  leadinPulseMs      = DEFAULT_LEADIN_PULSE_MS;
  leadinPauseMs      = DEFAULT_LEADIN_PAUSE_MS;
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
  trigMode_cfg       = data.trigMode;
  leadinPulseEnabled = data.leadinEnabled != 0;
  leadinPulseMs      = data.leadinPulseMs;
  leadinPauseMs      = data.leadinPauseMs;
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
  data.trigMode      = trigMode_cfg;
  data.leadinEnabled = leadinPulseEnabled ? 1 : 0;
  data.leadinPulseMs = leadinPulseMs;
  data.leadinPauseMs = leadinPauseMs;
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

// Durations are computed and scheduled in MICROSECONDS. The configured
// min/max stay in ms because that is how they are set and reported.
uint32_t randomDurationUs(unsigned long minMs, unsigned long maxMs) {
  if (minMs >= maxMs) return minMs * 1000UL;
  uint32_t lo = minMs * 1000UL, hi = maxMs * 1000UL;
  uint32_t steps = (hi - lo) / DURATION_STEP_US + 1;
  return lo + (prngNext() % steps) * DURATION_STEP_US;
}

uint32_t computeNextDurationUs() {
  return (outputState == HIGH) ? randomDurationUs(minHighMs, maxHighMs)
                               : randomDurationUs(minLowMs, maxLowMs);
}

#if EVENT_CHANNEL_ENABLED
// ---- Event channel ---------------------------------------------------------
// Runs as its own non-blocking state machine so the sync train is never held
// up waiting for a marker to finish. The two are completely independent: the
// train does not know events exist, and an aborted marker cannot disturb it.
//
// Marker shape:  [200 ms MARK][gap][8 payload symbols, MSB first][gap]
// where a symbol is 50 ms for 0 and 100 ms for 1, each followed by a gap.
// The MARK's rising edge is the event timestamp.
uint8_t  eventCounter    = 0;      // wraps at 255; 0 = no events yet this run
bool     eventActive     = false;  // a marker is playing
uint8_t  eventSeg        = 0;      // 0 = mark, then 1..2N alternating gap/sym
uint8_t  eventPayload    = 0;      // the counter value being transmitted
uint32_t eventNextChange = 0;
bool     eventPinState   = LOW;

void eventPinWrite(bool st) {
  eventPinState = st;
  digitalWrite(EVENT_CHANNEL_PIN, st);
}

// Total segments after the mark: for each bit, one gap then one symbol.
static const uint8_t EVENT_SEGS = 1 + 2 * EVENT_COUNTER_BITS;

// Duration of segment `seg`. Even segments after 0 are gaps, odd are symbols.
uint16_t eventSegMs(uint8_t seg) {
  if (seg == 0) return EVENT_MARK_MS;
  if ((seg & 1) == 1) return EVENT_GAP_MS;          // gap
  uint8_t bitIndex = (seg / 2) - 1;                  // 0..N-1, MSB first
  uint8_t shift = (EVENT_COUNTER_BITS - 1) - bitIndex;
  bool one = (eventPayload >> shift) & 1;
  return one ? EVENT_BIT1_MS : EVENT_BIT0_MS;
}

// Fire a marker NOW. Called from the trigger path; the rising edge here is
// what analysis reads as the event time, so nothing may delay it — including
// a marker already in progress, which is simply cut short.
void eventFire() {
  eventCounter++;                     // first event of a run is 1
  eventPayload = eventCounter;
  eventActive = true;
  eventSeg = 0;
  eventPinWrite(HIGH);
  eventNextChange = millis() + EVENT_MARK_MS;
}

void serviceEventChannel() {
  if (!eventActive) return;
  if ((int32_t)(millis() - eventNextChange) < 0) return;
  eventSeg++;
  if (eventSeg > EVENT_SEGS) {
    eventActive = false;
    eventPinWrite(LOW);
    return;
  }
  // Gaps are LOW, symbols are HIGH.
  eventPinWrite((eventSeg & 1) ? LOW : HIGH);
  eventNextChange = millis() + eventSegMs(eventSeg);
}
#endif  // EVENT_CHANNEL_ENABLED

// ---- Output: two port writes, not eight digitalWrite() calls ---------------
// Called from the ISR, so it must be fast and it must not touch pins outside
// the masks -- other bits on these ports belong to the trigger inputs, the
// event channel and USB.
inline void writeOutputs(bool state) {
  const uint8_t d = OUT_PORTD_MASK;
  const uint8_t f = OUT_PORTF_MASK;
  const uint8_t b = OUT_PORTB_MASK | PANEL_LED_MASK;  // LED mirrors the train
  if (state) {
    if (d) PORTD |= d;
    if (f) PORTF |= f;
    PORTB |= b;
  } else {
    if (d) PORTD &= ~d;
    if (f) PORTF &= ~f;
    PORTB &= ~b;
  }
}

void setOutput(bool state) {
  outputState = state;
  writeOutputs(state);
}

// (Re)start a fresh run: re-seed, outputs LOW, new run ID.
void startNewRun() {
#if EVENT_CHANNEL_ENABLED
  // Event numbering is per-run: event 3 of run 7 is unambiguous, and a
  // counter that carried across runs would not be.
  eventCounter = 0;
  eventActive = false;
  eventPinWrite(LOW);
#endif
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
  // The draw ALWAYS happens, even if the segment is then clamped: the PRNG
  // sequence must not depend on where frames fall, or the waveform stops
  // being reproducible from (seed, config).
  uint32_t dUs = computeNextDurationUs();
  unsigned long now = millis();
  if (tcEnabled) {
    long remaining = (long)(nextFrameDueMs - TC_LEADIN_MS - now);
    if (remaining <= 0) { enterLeadIn(); return; }          // ran late
    if ((long)(dUs / 1000UL) > remaining) {
      nextToggleTime = now + remaining;
      leadinPending = true;
      scheduleEdgeUs((uint32_t)remaining * 1000UL);
      return;
    }
  }
  nextToggleTime = now + (dUs / 1000UL);
  scheduleEdgeUs(dUs);
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
  Serial.print(F("  Firmware: ")); Serial.print(F(FW_VERSION));
  Serial.print(F("  built ")); Serial.println(F(FW_DATE));
  Serial.print(F("  Protocol: ")); Serial.print(PROTOCOL_VERSION);
  Serial.println(F("   (the signal on the wire; decoders match on this)"));
  Serial.print(F("  Hardware: ")); Serial.print(F(HW_VARIANT));
#if EVENT_CHANNEL_ENABLED
  Serial.print(F("+event"));
#endif
#if !TRIG_FEATURE
  Serial.print(F(" freerun-build"));
#endif
  Serial.println();
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
  // Only the pins actually carrying the train. Printing the raw array listed
  // the reserved trigger pins and the event channel as sync outputs, which is
  // exactly the sort of thing someone wires a BNC to and then cannot explain.
  {
    const uint8_t panel[] = PANEL_PINS;
    const uint8_t n = sizeof(panel);
    Serial.print(F("  BNC 1-"));
    Serial.print(n);
    Serial.print(F(":  "));
    for (uint8_t i = 0; i < n; i++) {
      if (i) Serial.print(F(", "));
      Serial.print(panel[i]);
#if EVENT_CHANNEL_ENABLED
      if (panel[i] == EVENT_CHANNEL_PIN) Serial.print(F("=EVENT"));
#endif
    }
    Serial.println();
#if EVENT_CHANNEL_ENABLED
    Serial.print(F("  Sync:      ")); Serial.print(n - 1);
    Serial.println(F(" channels; BNC 8 carries events"));
#else
    Serial.print(F("  Sync:      ")); Serial.print(n);
    Serial.println(F(" channels; event channel off"));
#endif
    Serial.println(F("             2 port writes, ~0.13 us sweep"));
  }
  Serial.print(F("  Panel LED: ")); Serial.println(PANEL_LED_PIN);
  Serial.print(F("  Quantum:   ")); Serial.print(DURATION_STEP_US);
  Serial.println(F(" us, Timer3 compare-match (~1 us ISR latency)"));
#if EVENT_CHANNEL_ENABLED
#endif
#if TRIG_FEATURE
  Serial.print(F("  Reserved:  "));
  Serial.print(TRIG_IN_PIN); Serial.print(F(" TRIG IN, "));
  Serial.print(MODE_SWITCH_PIN); Serial.println(F(" MODE SW"));
#endif
#if TRIG_FEATURE
  Serial.print(F("  Mode:     "));
  Serial.println(digitalRead(MODE_SWITCH_PIN) == LOW
                 ? (MODE_FREE_IS_LOW ? F("FREE RUN") : F("TRIG RUN"))
                 : (MODE_FREE_IS_LOW ? F("TRIG RUN") : F("FREE RUN")));
#endif
  Serial.print(F("  TrigMode: "));
  Serial.println(trigMode_cfg == TRIG_MODE_EDGE_START  ? F("start")
               : trigMode_cfg == TRIG_MODE_EDGE_TOGGLE ? F("toggle")
                                                       : F("gate"));
  Serial.print(F("  Marker:   "));
  if (leadinPulseEnabled) {
    Serial.print(F("ON, ")); Serial.print(leadinPulseMs);
    Serial.print(F(" ms pulse + ")); Serial.print(leadinPauseMs);
    Serial.println(F(" ms pause"));
  } else {
    Serial.println(F("OFF"));
  }
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
  Serial.println(F("  trigmode <m>      - start|toggle|gate"));
  Serial.println(F("  mark on|off       - lead-in marker pulse on trigger"));
  Serial.println(F("  markms <p> <g>    - marker pulse ms, then pause ms"));
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
  else if (strcmp(token, "trigmode") == 0) {
    char* sVal = strtok(NULL, " ");
    int m = -1;
    if (sVal) {
      if      (strcmp(sVal, "start")  == 0) m = TRIG_MODE_EDGE_START;
      else if (strcmp(sVal, "toggle") == 0) m = TRIG_MODE_EDGE_TOGGLE;
      else if (strcmp(sVal, "gate")   == 0) m = TRIG_MODE_LEVEL_GATE;
      else if (sVal[0] >= '0' && sVal[0] <= '2') m = sVal[0] - '0';
    }
    if (m >= 0) {
      trigMode_cfg = (uint8_t)m;
      Serial.print(F("Trigger mode: "));
      Serial.println(m == TRIG_MODE_EDGE_START  ? F("start (edge starts; later edges ignored)")
                   : m == TRIG_MODE_EDGE_TOGGLE ? F("toggle (edge starts, next edge stops)")
                                                : F("gate (runs while TRIG IN is HIGH)"));
    } else {
      Serial.println(F("Usage: trigmode start|toggle|gate"));
    }
  }
  else if (strcmp(token, "mark") == 0) {
    char* sVal = strtok(NULL, " ");
    if (sVal && (strcmp(sVal, "on") == 0 || strcmp(sVal, "off") == 0)) {
      leadinPulseEnabled = (strcmp(sVal, "on") == 0);
      Serial.print(F("Lead-in marker pulse: "));
      Serial.println(leadinPulseEnabled ? F("ON") : F("OFF"));
    } else {
      Serial.println(F("Usage: mark on|off"));
    }
  }
  else if (strcmp(token, "markms") == 0) {
    char* sPulse = strtok(NULL, " ");
    char* sPause = strtok(NULL, " ");
    if (sPulse && sPause && atol(sPulse) > 0 && atol(sPause) >= 0) {
      leadinPulseMs = atol(sPulse);
      leadinPauseMs = atol(sPause);
      Serial.print(F("Marker: "));
      Serial.print(leadinPulseMs);
      Serial.print(F(" ms pulse, "));
      Serial.print(leadinPauseMs);
      Serial.println(F(" ms pause"));
    } else {
      Serial.println(F("Usage: markms <pulse_ms> <pause_ms>"));
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
  else if (strcmp(token, "pintest") == 0) {
    // Walk the eight panel outputs one at a time so each can be confirmed on
    // a meter or a scope. Verifying the compile is not verifying the pins:
    // a set that includes JTAG-owned pins compiles perfectly and drives
    // nothing.
    bool wasRunning = running;
    running = false;
    setOutput(LOW);
    const uint8_t panel[] = PANEL_PINS;
    Serial.println(F("Walking outputs, 400 ms each. Watch each channel."));
    for (uint8_t i = 0; i < sizeof(panel); i++) {
      Serial.print(F("  pin ")); Serial.print(panel[i]);
      Serial.println(F(" HIGH"));
      digitalWrite(panel[i], HIGH);
      delay(400);
      digitalWrite(panel[i], LOW);
    }
    // Read the port back after a PORT-WRITE (not digitalWrite): if JTAG still
    // owns PF4-PF7 the bits will not stick, and digitalWrite would have
    // masked that by taking a different path.
    writeOutputs(HIGH);
    delayMicroseconds(50);
    uint8_t f_hi = PINF & OUT_PORTF_MASK;
    uint8_t b_hi = PINB & OUT_PORTB_MASK;
    writeOutputs(LOW);
    delayMicroseconds(50);
    uint8_t f_lo = PINF & OUT_PORTF_MASK;
    uint8_t b_lo = PINB & OUT_PORTB_MASK;
    Serial.print(F("  PORTF readback hi=0x")); Serial.print(f_hi, HEX);
    Serial.print(F(" lo=0x")); Serial.print(f_lo, HEX);
    Serial.print(F("  expect 0x")); Serial.print(OUT_PORTF_MASK, HEX);
    Serial.println(F(" / 0x0"));
    Serial.print(F("  PORTB readback hi=0x")); Serial.print(b_hi, HEX);
    Serial.print(F(" lo=0x")); Serial.print(b_lo, HEX);
    Serial.print(F("  expect 0x")); Serial.print(OUT_PORTB_MASK, HEX);
    Serial.println(F(" / 0x0"));
    Serial.println((f_hi == OUT_PORTF_MASK && f_lo == 0 &&
                    b_hi == OUT_PORTB_MASK && b_lo == 0)
                   ? F("  PORT WRITES OK -- all eight driven")
                   : F("  *** PORT WRITE FAILED -- check JTD / masks ***"));
    Serial.println(F("All eight together, 3 x 300 ms"));
    for (uint8_t k = 0; k < 3; k++) {
      writeOutputs(HIGH); delay(300);
      writeOutputs(LOW);  delay(300);
    }
    Serial.println(F("pintest done"));
    running = wasRunning;
    if (running) { setOutput(LOW); schedulePrSegment(); }
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

// ---- Timer3: the emission clock --------------------------------------------
// Free-running at 0.5 us per tick with the next edge scheduled on compare
// match. Everything the ISR needs is prepared outside it; the ISR itself only
// flips the pins, advances the state machine and arms the next compare.
//
// The compare value is 16-bit, so a single wait is capped at 32.7 ms. Longer
// intervals -- a 500 ms pulse is 15 of them -- are counted down in whole
// chunks. This keeps the LAST chunk exact, which is what matters: the edge
// lands on the tick, not at the end of an accumulating error.
volatile uint32_t edgeRemainingTicks = 0;   // ticks still to wait
volatile bool     timerArmed = false;

#define TIMER_MAX_TICKS 60000UL   // < 65535, leaves headroom for the reload

static inline void armTimer() {
  uint16_t chunk = (edgeRemainingTicks > TIMER_MAX_TICKS)
                 ? (uint16_t)TIMER_MAX_TICKS : (uint16_t)edgeRemainingTicks;
  edgeRemainingTicks -= chunk;
  TCNT3 = 0;
  OCR3A = chunk;
  timerArmed = true;
}

// Schedule the next edge `us` microseconds from now.
void scheduleEdgeUs(uint32_t us) {
  uint32_t ticks = us * TICKS_PER_US;
  if (ticks < 2) ticks = 2;
  uint8_t sreg = SREG; cli();
  edgeRemainingTicks = ticks;
  armTimer();
  SREG = sreg;
}

void timerInit() {
  uint8_t sreg = SREG; cli();
  TCCR3A = 0;
  TCCR3B = _BV(WGM32) | _BV(CS31);   // CTC on OCR3A, prescaler 8
  TCCR3C = 0;
  TCNT3  = 0;
  OCR3A  = 0xFFFF;
  TIMSK3 = _BV(OCIE3A);
  SREG = sreg;
}

// Set by the ISR when a train edge has been emitted, so the main loop can do
// the bookkeeping (frames, PRNG draws) that is too slow for interrupt context.
volatile bool edgeFired = false;

ISR(TIMER3_COMPA_vect) {
  if (edgeRemainingTicks) { armTimer(); return; }   // long wait, another chunk
  timerArmed = false;
  edgeFired = true;
}

void setup() {
  // ---- Free the A-pins from JTAG ------------------------------------------
  // PF4-PF7 (A3..A0 on a Pro Micro) are the JTAG pins TCK/TMS/TDO/TDI. With
  // the JTAGEN fuse set -- which is the factory default -- the JTAG interface
  // owns them and writing PORTF does nothing useful: four of the eight
  // channels would simply never toggle, silently.
  //
  // Setting JTD in MCUCR releases them to GPIO. The write must happen TWICE
  // within four clock cycles or the hardware ignores it, which is why this
  // looks redundant and must not be "tidied" into one line. No fuse change is
  // needed and it costs only the ability to attach a JTAG debugger.
  {
    uint8_t sreg = SREG; cli();
    MCUCR |= _BV(JTD);
    MCUCR |= _BV(JTD);
    SREG = sreg;
  }

  // Exactly the eight panel pins, from the same list the port masks were
  // derived from. Walking OUTPUT_PINS here instead would set a direction on
  // pins the ISR never touches -- and, on a Pro Micro, would leave the A-pins
  // as inputs, so the PORTF write would have driven pullups rather than
  // outputs and nothing would have appeared on four of the eight channels.
  {
    const uint8_t panel[] = PANEL_PINS;
    for (uint8_t i = 0; i < sizeof(panel); i++) {
      pinMode(panel[i], OUTPUT);
      digitalWrite(panel[i], LOW);
    }
  }
#if TRIG_FEATURE
  timerInit();
#if EVENT_CHANNEL_ENABLED
  pinMode(EVENT_CHANNEL_PIN, OUTPUT);
  digitalWrite(EVENT_CHANNEL_PIN, LOW);
#endif
  pinMode(PANEL_LED_PIN, OUTPUT);
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
bool trigWasHigh = false;   // edge detect: previous TRIG IN level

// Start a run, optionally prefixed by the lead-in marker pulse.
//
// With the marker enabled the sequence is: one clean pulse of leadinPulseMs,
// then LOW for leadinPauseMs, then the pseudo-random train. A single
// unambiguous flash is far easier to find in video than a pseudo-random train
// is, so a camera watching an LED can be aligned off that one event without
// decoding anything.
//
// The run clock starts at the LEADING EDGE of the marker, not after the pause,
// so embedded timecode stays referenced to the trigger instant. The pause is a
// known constant, so analysis places the train relative to the marker exactly.
void startRunMaybeMarked() {
  startNewRun();                       // resets the clock, bumps the run ID
  if (leadinPulseEnabled) {
    mode = MODE_MARK;
    setOutput(HIGH);
    nextToggleTime = millis() + leadinPulseMs;
  }
}

void serviceTrigger() {
  bool swLow = digitalRead(MODE_SWITCH_PIN) == LOW;
  bool nowTrig = (swLow != (bool)MODE_FREE_IS_LOW);
  if (nowTrig != trigMode) {
    trigMode = nowTrig;
    if (trigMode) {
      running = false;
      setOutput(LOW);
      trigLowSince = 0;
      trigWasHigh = digitalRead(TRIG_IN_PIN) != LOW;
      Serial.println(F("TRIG mode: outputs held LOW, waiting for TRIG IN"));
    } else {
      startRunMaybeMarked();
      Serial.println(F("FREE RUN mode: started"));
    }
  }
  if (!trigMode) return;

  bool level = digitalRead(TRIG_IN_PIN) != LOW;

  if (trigMode_cfg == TRIG_MODE_LEVEL_GATE) {
    // Output runs while TRIG IN is HIGH. Each rising edge starts a fresh run,
    // so every gated segment carries its own run ID and its own elapsed clock
    // — which is what lets the analysis tell one gated segment from another.
    if (level && !running) {
#if EVENT_CHANNEL_ENABLED
      eventFire();
#endif
      startRunMaybeMarked();
      Serial.println(F("Gate HIGH: running"));
    } else if (!level && running) {
      running = false;
      setOutput(LOW);
      Serial.println(F("Gate LOW: stopped"));
    }
    trigWasHigh = level;
    return;
  }

  // Edge modes. The line must sit LOW for TRIG_ARM_LOW_MS before a rising
  // edge counts, so an unconnected jack cannot false-trigger.
  if (!level) {
    if (trigLowSince == 0) trigLowSince = millis();
  } else {
    bool armed = trigLowSince != 0 &&
                 (millis() - trigLowSince) >= TRIG_ARM_LOW_MS;
    if (armed && !trigWasHigh) {
#if EVENT_CHANNEL_ENABLED
      // EVERY qualifying edge is an event, including ones that do not change
      // the run state. In EDGE_START this is the whole point: the first
      // trigger starts the run, and every trigger after it is an event to be
      // marked rather than something to ignore.
      eventFire();
#endif
      if (!running) {
        startRunMaybeMarked();
        Serial.println(F("Triggered!"));
      } else if (trigMode_cfg == TRIG_MODE_EDGE_TOGGLE) {
        running = false;
        setOutput(LOW);
        Serial.println(F("Triggered: stopped"));
      } else {
        Serial.print(F("Event "));
        Serial.println(eventCounter);
      }
    }
    trigLowSince = 0;
  }
  trigWasHigh = level;
}
#endif

void loop() {
#if TRIG_FEATURE
  serviceTrigger();
#endif
#if EVENT_CHANNEL_ENABLED
  serviceEventChannel();
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

  // A train segment is due when the TIMER says so; frame and marker segments
  // remain millis()-scheduled, since their symbols are whole milliseconds and
  // their accuracy is not what the analysis leans on. Consuming edgeFired
  // here keeps the two paths from racing.
  bool timerDue = false;
  if (edgeFired) { uint8_t sr = SREG; cli(); edgeFired = false; SREG = sr; timerDue = true; }
  if (running && (timerDue || millis() >= nextToggleTime)) {
    if (mode == MODE_MARK) {
      // Marker pulse just ended: hold LOW for the configured pause. The run
      // clock is already running from the marker's leading edge, so timecode
      // stays referenced to the trigger instant, not to the end of the pause.
      mode = MODE_MARKPAUSE;
      setOutput(LOW);
      nextToggleTime = millis() + leadinPauseMs;
      scheduleEdgeUs((uint32_t)leadinPauseMs * 1000UL);
    } else if (mode == MODE_MARKPAUSE) {
      // Pause over: begin the pseudo-random train.
      mode = MODE_PR;
      setOutput(HIGH);
      schedulePrSegment();
    } else if (mode == MODE_FRAME) {
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
