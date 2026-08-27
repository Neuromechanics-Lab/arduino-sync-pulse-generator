/*
 * sync_pulse_simple - BENCH TEST build of the sync pulse generator.
 *
 * The bare pseudo-random square wave and nothing else: same 5V/0V signal
 * on ALL pins, fixed seed, always running from power-up.
 *   - no timecode frames
 *   - no FREE/TRIG switch or TRIG input (pins 2/3 are plain outputs here)
 *   - no serial commands, no EEPROM
 *
 * The full firmware lives in ../sync_pulse_generator (untouched) — reflash
 * that when bench testing is done. Same wave parameters as its defaults
 * (seed 42, 50-500 ms, 5 ms steps), so recordings still match templates
 * generated with timecode disabled.
 *
 * Build (Pro Micro):
 *   arduino-cli compile --fqbn arduino:avr:micro \
 *     --build-property "compiler.cpp.extra_flags=-DBOARD_PRO_MICRO" .
 */

#define MIN_HIGH_MS 50
#define MAX_HIGH_MS 500
#define MIN_LOW_MS  50
#define MAX_LOW_MS  500
#define PRNG_SEED   42
#define STEP_MS     5

#ifdef BOARD_PRO_MICRO
const uint8_t OUTPUT_PINS[] = {0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10,
                               14, 15, 16, 18, 19, 20, 21};
#else
const uint8_t OUTPUT_PINS[] = {0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13,
                               18, 19, 20, 21, 22, 23};
#endif
const uint8_t NUM_PINS = sizeof(OUTPUT_PINS);

uint32_t prngState = PRNG_SEED;
bool level = false;
unsigned long toggleAtMs = 0;

uint32_t xorshift32() {
  prngState ^= prngState << 13;
  prngState ^= prngState >> 17;
  prngState ^= prngState << 5;
  return prngState;
}

unsigned long randomDuration(unsigned long mn, unsigned long mx) {
  if (mn >= mx) return mn;
  unsigned long steps = (mx - mn) / STEP_MS + 1;
  return mn + (xorshift32() % steps) * STEP_MS;
}

void setAll(bool high) {
  for (uint8_t i = 0; i < NUM_PINS; i++)
    digitalWrite(OUTPUT_PINS[i], high ? HIGH : LOW);
}

void setup() {
  for (uint8_t i = 0; i < NUM_PINS; i++) {
    pinMode(OUTPUT_PINS[i], OUTPUT);
    digitalWrite(OUTPUT_PINS[i], LOW);
  }
  toggleAtMs = millis();   // first toggle (to HIGH) immediately
}

void loop() {
  if ((long)(millis() - toggleAtMs) >= 0) {
    level = !level;
    setAll(level);
    toggleAtMs += level ? randomDuration(MIN_HIGH_MS, MAX_HIGH_MS)
                        : randomDuration(MIN_LOW_MS, MAX_LOW_MS);
  }
}
