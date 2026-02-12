/*
 * Pseudo-Random Square Wave Sync Pulse Generator
 * Gothic Grandma Studios - Neurotrophy Ecosystem
 *
 * Outputs a pseudo-random square wave on configurable pins.
 * The high and low durations are randomized within configurable
 * min/max ranges (in milliseconds). The pseudo-random pattern
 * has a sharp autocorrelation peak, making it ideal for
 * cross-correlation-based temporal alignment of multi-device
 * recordings (Vicon, EEG, etc.).
 *
 * A fixed seed ensures the pattern is reproducible across runs
 * for verification. The seed and timing ranges are configurable
 * via Serial commands at runtime.
 *
 * Board: Arduino Leonardo
 */

// ---- Configuration ----
// Output pins (accent the same signal on multiple pins for multiple BNC cables)
const int OUTPUT_PINS[] = {2, 3, 4, 5};
const int NUM_PINS = sizeof(OUTPUT_PINS) / sizeof(OUTPUT_PINS[0]);

// Timing ranges in milliseconds
unsigned long minHighMs = 50;
unsigned long maxHighMs = 500;
unsigned long minLowMs  = 50;
unsigned long maxLowMs  = 500;

// PRNG seed (fixed for reproducibility; change via Serial)
unsigned long prngSeed = 42;

// LED pin for visual feedback
const int LED_PIN = 13;

// ---- State ----
bool outputState = LOW;
unsigned long nextToggleTime = 0;
bool running = true;

// Simple LFSR-based PRNG for reproducibility (not using stdlib rand)
// 32-bit xorshift
uint32_t prngState;

void seedPrng(uint32_t seed) {
  prngState = seed ? seed : 1; // must not be zero
}

uint32_t prngNext() {
  prngState ^= prngState << 13;
  prngState ^= prngState >> 17;
  prngState ^= prngState << 5;
  return prngState;
}

// Random duration in [minMs, maxMs]
unsigned long randomDuration(unsigned long minMs, unsigned long maxMs) {
  if (minMs >= maxMs) return minMs;
  uint32_t range = maxMs - minMs + 1;
  return minMs + (prngNext() % range);
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
  digitalWrite(LED_PIN, state);
}

void printConfig() {
  Serial.println(F("=== Sync Pulse Generator Config ==="));
  Serial.print(F("  Seed:     ")); Serial.println(prngSeed);
  Serial.print(F("  High ms:  ")); Serial.print(minHighMs);
  Serial.print(F(" - ")); Serial.println(maxHighMs);
  Serial.print(F("  Low ms:   ")); Serial.print(minLowMs);
  Serial.print(F(" - ")); Serial.println(maxLowMs);
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
  // Tokenize
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
  // Configure output pins
  for (int i = 0; i < NUM_PINS; i++) {
    pinMode(OUTPUT_PINS[i], OUTPUT);
    digitalWrite(OUTPUT_PINS[i], LOW);
  }
  pinMode(LED_PIN, OUTPUT);
  digitalWrite(LED_PIN, LOW);

  // Serial for configuration (Leonardo needs a moment for USB serial)
  Serial.begin(115200);
  unsigned long waitStart = millis();
  while (!Serial && (millis() - waitStart < 3000)) {
    ; // Wait up to 3s for serial connection
  }

  // Seed the PRNG
  seedPrng(prngSeed);

  Serial.println(F("Sync Pulse Generator Ready"));
  printConfig();
  printHelp();

  // Start immediately
  nextToggleTime = millis();
}

void loop() {
  // Handle serial commands
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

  // Square wave generation
  if (running && millis() >= nextToggleTime) {
    // Toggle
    outputState = !outputState;
    setOutput(outputState);

    // Schedule next toggle
    unsigned long duration = computeNextDuration();
    nextToggleTime = millis() + duration;
  }
}
