/*
 * Dual-Channel Pseudo-Random Pulse Generator
 *
 * A simplified cousin of sync_pulse_generator that drives TWO
 * independent channels, each on its own pin with its own speed:
 *
 *   Channel A -> pin 2   fast pulses (25-150 ms per state)
 *   Channel B -> pin 3   slow pulses (200-1000 ms per state)
 *
 * To see a channel, wire an LED (with ~220 ohm resistor) from its
 * pin to GND, or clip on a scope probe. Tip for a no-wiring look:
 * set a channel's pin to 17 and the Pro Micro's onboard RX LED
 * will blink it (that LED lights when the pin is LOW, so the
 * pattern shows up inverted). On a Leonardo/Uno, pin 13 is the
 * onboard LED.
 *
 * Every toggle is also printed over serial so you can watch both
 * channels in the monitor:
 *
 *   arduino-cli monitor -p <your-port> --config baudrate=115200
 *
 * The "channel table" below is the whole routing story: each row
 * says which pin a signal goes to and how fast it runs. Change a
 * pin number to move that signal to a different pin; add a row to
 * add a channel.
 *
 * Each channel has its own deterministic PRNG (xorshift32), so the
 * same seed always reproduces the same pulse sequence.
 */

struct Channel {
  const char* name;         // label used in serial output
  int pin;                  // which board pin this channel drives
  unsigned long minMs;      // shortest time in one state (ms)
  unsigned long maxMs;      // longest time in one state (ms)
  uint32_t prng;            // PRNG state, initialized with the seed (nonzero!)
  bool state;               // current output level
  unsigned long nextToggle; // millis() time of the next flip
};

// ---- Channel table: pin routing + speed, one row per channel ----
Channel channels[] = {
  // name  pin  min   max   seed  state  nextToggle
  { "A",   2,   25,   150,  42,   LOW,   0 },
  { "B",   3,   200,  1000, 1337, LOW,   0 },
};
const int NUM_CHANNELS = sizeof(channels) / sizeof(channels[0]);

// xorshift32: tiny deterministic PRNG (same algorithm as sync_pulse_generator)
uint32_t prngNext(uint32_t &state) {
  state ^= state << 13;
  state ^= state >> 17;
  state ^= state << 5;
  return state;
}

// Random duration within the channel's range, in 5 ms increments
unsigned long randomDuration(Channel &ch) {
  if (ch.minMs >= ch.maxMs) return ch.minMs;
  uint32_t steps = (ch.maxMs - ch.minMs) / 5 + 1;
  return ch.minMs + (prngNext(ch.prng) % steps) * 5;
}

void setup() {
  for (int i = 0; i < NUM_CHANNELS; i++) {
    pinMode(channels[i].pin, OUTPUT);
    digitalWrite(channels[i].pin, LOW);
    channels[i].nextToggle = millis();
  }

  Serial.begin(115200);
  unsigned long waitStart = millis();
  while (!Serial && (millis() - waitStart < 3000)) {
    ;
  }

  Serial.println("Dual-channel pulse generator running");
  for (int i = 0; i < NUM_CHANNELS; i++) {
    Serial.print("  Channel ");
    Serial.print(channels[i].name);
    Serial.print(" -> pin ");
    Serial.print(channels[i].pin);
    Serial.print(", ");
    Serial.print(channels[i].minMs);
    Serial.print("-");
    Serial.print(channels[i].maxMs);
    Serial.println(" ms");
  }
}

void loop() {
  unsigned long now = millis();

  // Check every channel each pass; flip whichever ones are due.
  // No delay() anywhere, so a slow channel never blocks a fast one.
  for (int i = 0; i < NUM_CHANNELS; i++) {
    Channel &ch = channels[i];
    if (now >= ch.nextToggle) {
      ch.state = !ch.state;
      digitalWrite(ch.pin, ch.state);

      unsigned long duration = randomDuration(ch);
      ch.nextToggle = now + duration;

      Serial.print(ch.name);
      Serial.print(ch.state == HIGH ? " HIGH for " : " LOW  for ");
      Serial.print(duration);
      Serial.println(" ms");
    }
  }
}
