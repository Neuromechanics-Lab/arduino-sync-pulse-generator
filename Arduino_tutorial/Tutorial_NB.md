## 1. Install the toolchain (macOS)

Open a terminal and run:

```bash
# Install the Arduino command-line tool
brew install arduino-cli

# Download the board index
arduino-cli core update-index

# Install the compiler + tools for standard AVR boards (Uno, Leonardo, Micro, ...)
arduino-cli core install arduino:avr
```

Verify it works:

```bash
arduino-cli version
```

### VS Code setup

VS Code is just your editor here — all compiling/uploading happens in the terminal (use VS Code's built-in terminal: ``Ctrl+` ``).

- Install the **C/C++** extension (Microsoft) so `.ino` files get syntax highlighting and autocomplete.
- Optional: the **Arduino Community Edition** extension adds a serial monitor button, but you don't need it — everything below uses the terminal.

## 2. Know your board

Every board has an **FQBN** (Fully Qualified Board Name) that tells the compiler what chip it's building for. Common ones:

| Board | FQBN | Upload quirk |
|---|---|---|
| Arduino Uno | `arduino:avr:uno` | none, just upload |
| Arduino Leonardo | `arduino:avr:leonardo` | may need a reset double-tap, see section 5 |
| Pro Micro (ATmega32U4) | `arduino:avr:micro` | same, but no reset button (short RST to GND instead) |

Plug the board in over USB and find its port:

```bash
arduino-cli board list
```

You'll see something like `/dev/cu.usbmodem14101` (macOS) or `COM3` (Windows). That port name goes into every upload command below.

## 3. Project layout

`arduino-cli` requires the sketch folder name to match the `.ino` filename:

```
fsr_reader/
└── fsr_reader.ino
```

That's the whole project. Create it anywhere, open the folder in VS Code, and edit the `.ino` file.

---

## 4. The example: read a force sensing resistor

An FSR is a flat pad whose electrical resistance drops as you press on it (~1 MΩ untouched → a few kΩ pressed hard). The Arduino can't measure resistance directly, but it can measure **voltage** — so we build a **voltage divider**:

```
  5V ----[ FSR ]----+----[ 10 kΩ resistor ]---- GND
                    |
                    A0  (analog input)
```

**Wiring steps (3 wires + 1 resistor on a breadboard):**

1. One leg of the FSR → **5V** pin (labeled **VCC** on the Pro Micro)
2. Other leg of the FSR → a breadboard row; from that same row, a **10 kΩ resistor** → **GND** pin
3. A wire from that middle junction → **A0**

When you press the FSR, its resistance drops, so more of the 5V appears at A0. `analogRead(A0)` converts that voltage into a number: **0** (0V, no press) to **1023** (5V, hard press).

The complete sketch is in [`fsr_reader/fsr_reader.ino`](fsr_reader/fsr_reader.ino). The core of it:

```cpp
const int FSR_PIN = A0;

void setup() {
  // 115200 is the baud rate: how many bits per second flow over the
  // serial connection between the board and your computer. Both sides
  // have to agree on it, which is why the sketch says Serial.begin(115200)
  // and the monitor command says --config baudrate=115200. If they
  // disagree, the bytes get sliced at the wrong intervals and you
  // see garbage.
  Serial.begin(115200);
}

void loop() {
  int raw = analogRead(FSR_PIN);           // 0–1023
  float voltage = raw * (5.0 / 1023.0);    // convert to volts

  Serial.print(raw);
  Serial.print('\t');
  Serial.println(voltage, 2);

  delay(100);                    // 10 readings per second
}
```

---

## 5. Compile and upload from the terminal

From the directory *containing* the `fsr_reader` folder:

**Compile** (checks your code and builds the binary — catch errors here first):

```bash
arduino-cli compile --fqbn arduino:avr:micro fsr_reader
```

**Upload** (replace the port with what `arduino-cli board list` showed you):

```bash
arduino-cli upload --fqbn arduino:avr:micro -p /dev/cu.usbmodem14101 fsr_reader
```

These use the Pro Micro FQBN. Substitute `arduino:avr:uno`, `arduino:avr:leonardo`, etc. if you're on a different board.

> **Leonardo / Pro Micro quirk:** these boards have to be in "bootloader mode" to accept an upload. The upload command normally handles this for you (it pokes the port at 1200 baud, which reboots the board), so most of the time uploads just work. If an upload fails, or a buggy sketch has taken down the USB connection, you have to force it manually with a double-tap reset. On a Leonardo that means double-tapping the reset button. The Pro Micro has no reset button, so instead you briefly short the RST pin to GND twice in quick succession with a jumper wire. Either way the board then sits in bootloader mode for about 8 seconds, usually under a *different* port name, so run `arduino-cli board list` again right after and upload to whatever port it shows. An Uno has none of this, you just run upload.

**Typical loop while developing:** edit in VS Code → `compile` → fix errors → `upload` → watch serial output. Re-upload any time; the new program replaces the old one.

---

## 6. Watch the data: serial monitor

The board prints readings over USB. Open the monitor from the terminal (the baud rate must match the `Serial.begin()` value in the sketch):

```bash
arduino-cli monitor -p /dev/cu.usbmodem14101 --config baudrate=115200
```

Press the FSR and you'll see the numbers climb:

```
raw (0-1023)	voltage (V)
12	0.06
14	0.07
389	1.90      <- light press
801	3.91      <- firm press
```

`Ctrl+C` exits the monitor. **Note:** the serial port can only be held by one program at a time — close the monitor before uploading, or the upload will fail with a "port busy" error.

---

## 7. Adapting this to other sensors

The pattern above covers a huge range of lab sensors:

- **Anything resistive** (photoresistors, thermistors, flex sensors, other FSRs): same voltage-divider circuit, same `analogRead()`. Only the fixed resistor value and the interpretation of the number change.
- **Anything that outputs a voltage** (many accelerometers, EMG boards, potentiometers): wire its output straight to A0–A5 and `analogRead()` it — no divider needed, as long as its output stays within 0–5V.
- **Switches / buttons / TTL triggers**: use a digital pin with `digitalRead()`.
- **Smart sensors (I2C/SPI)** — IMUs, precision temperature, etc.: these need a library. Install with e.g. `arduino-cli lib search mpu6050` then `arduino-cli lib install "<library name>"`, and follow the library's example.

To log sensor data to a file for analysis, print comma-separated values in the sketch and capture the serial stream, e.g.:

```bash
arduino-cli monitor -p /dev/cu.usbmodem14101 --config baudrate=115200 | tee data.csv
```

---

## 8. Generating signals: pseudo-random pulses on two channels

So far we've read a pin. This example drives pins instead: it flips them HIGH and LOW at pseudo-random intervals, same idea as our sync pulse generator boxes, but stripped down to show how you pick which signal goes to which pin. It runs two channels at different speeds so you can see they're independent:

- channel A on pin 2, fast pulses (25–150 ms per state)
- channel B on pin 3, slow pulses (200–1000 ms per state)

To see a channel, wire an LED (with a ~220 Ω resistor) from its pin to GND, or clip a scope probe across pin and GND. If you want a no-wiring demo, temporarily set a channel's pin to 17: that's the Pro Micro's onboard RX LED, and it will blink the pattern (inverted, since that LED lights when the pin is LOW — fine for watching). On a Leonardo or Uno, pin 13 is the onboard LED.

Full sketch: [`dual_pulse/dual_pulse.ino`](dual_pulse/dual_pulse.ino).

### Picking which pin gets which signal

There is no special "channel" hardware. A channel is just a pin the code decides to write to. The sketch keeps that mapping in one table:

```cpp
struct Channel {
  const char* name;         // label used in serial output
  int pin;                  // which board pin this channel drives
  unsigned long minMs;      // shortest time in one state (ms)
  unsigned long maxMs;      // longest time in one state (ms)
  uint32_t prng;            // PRNG seed (nonzero)
  bool state;
  unsigned long nextToggle;
};

Channel channels[] = {
  // name  pin  min   max   seed
  { "A",   2,   25,   150,  42   },
  { "B",   3,   200,  1000, 1337 },
};
```

That table is the whole routing story. Want channel A on pin 7 instead? Change the 2 to a 7 and re-upload. Want a third channel on pin 5? Add a row. Each row carries its own timing range and its own random seed, which is what lets every channel run at its own speed with its own (reproducible) pattern. On the Pro Micro the usable pins are 0–10, 14–16, and A0–A3; there is no pin 11, 12, or 13.

Physically, "channel A" is then just pin 2 + GND: hook a scope probe, BNC, or an LED (with a ~220 Ω resistor to GND) across those two points.

### Why there's no delay() in this sketch

The obvious way to blink a pin is `delay(100)` between flips, but delay() puts the whole chip to sleep — while it waits, nothing else can happen, so two channels at different speeds would be impossible. Instead the sketch keeps a "when do I flip next" timestamp for each channel and checks the clock on every pass through loop():

```cpp
void loop() {
  unsigned long now = millis();   // ms since power-on
  for (int i = 0; i < NUM_CHANNELS; i++) {
    Channel &ch = channels[i];
    if (now >= ch.nextToggle) {                 // is this channel due?
      ch.state = !ch.state;
      digitalWrite(ch.pin, ch.state);           // flip the pin
      ch.nextToggle = now + randomDuration(ch); // schedule the next flip
    }
  }
}
```

loop() runs thousands of times per second, so each channel gets flipped within a fraction of a millisecond of its scheduled time, and a slow channel never blocks a fast one. This millis() pattern is the trick for doing several things at once on a microcontroller — the sync pulse generator uses the same one.

### Where the "random" comes from

Each channel runs a tiny pseudo-random number generator (PRNG). Feed the result back in and you get a stream of random-looking numbers. The whole thing is three lines:

```cpp
uint32_t prngNext(uint32_t &state) {
  state ^= state << 13;   // xorshift32: shift the bits, XOR them
  state ^= state >> 17;   //   back in, three times over
  state ^= state << 5;
  return state;
}
```

This part is cool. What is happening above is we are taking a 32 bit value (state), represented in binary. State might equal 10110000...n32 to start. We perform 3 XOR operations. Each one compares state to state shifted 13 bits to the left and those that fall off are replaced by 0's. State becomes a new binary value, where each bit that matched between the two becomes 0, and each that didn't become 1. You then do this shifting 17 to the right and then 5 to the left. Those specific shift values (13, 17, 5) are unique in that they allow you to shift through all 4,294,967,295 nonzero 32-bit values before repeating. 

The starting number (state) is the seed (the 42 and 1337 in the channel table). Because the scrambling is deterministic, the same seed always produces the exact same sequence of numbers, and therefore the exact same pulse pattern, every power cycle. That's what our sync boxes are doing and analysis code can regenerate the expected pattern from just the seed. Change the seed to get a different pattern; keep it to get the same one. We keep it set so that we could generate the pattern in Matlab or Python, if need be.

Each PRNG output is then squashed into the channel's min–max range, in 5 ms steps:

```cpp
unsigned long randomDuration(Channel &ch) {
  if (ch.minMs >= ch.maxMs) return ch.minMs;
  uint32_t steps = (ch.maxMs - ch.minMs) / 5 + 1;      // how many 5 ms slots fit
  return ch.minMs + (prngNext(ch.prng) % steps) * 5;   // pick one of them
}
```

**One caution: the seed must not be 0 — xorshift scrambles 0 into 0 forever, so a zero-seeded channel would never look random.**

### Upload and watch it

```bash
arduino-cli compile --fqbn arduino:avr:micro dual_pulse
arduino-cli upload --fqbn arduino:avr:micro -p /dev/cu.usbmodem101 dual_pulse
arduino-cli monitor -p /dev/cu.usbmodem101 --config baudrate=115200
```

The monitor narrates both channels:

```
Dual-channel pulse generator running
  Channel A -> pin 2, 25-150 ms
  Channel B -> pin 3, 200-1000 ms
A HIGH for 65 ms
A LOW  for 130 ms
B HIGH for 850 ms
A HIGH for 40 ms
...
```

Notice A toggles several times while B holds one state. Two speeds, two pins, one program.

### Running it without a computer

The uploaded program lives in the chip's flash memory and runs any time the board has power — the serial printing just goes nowhere if nothing is listening. Ways to power a deployed board:

- **USB**: any USB charger or power bank.
- **RAW pin**: unregulated DC in, roughly 5.5–12V. A 9V center-positive barrel adapter wired to RAW + GND works well (this is how our sync boxes are powered). The onboard regulator drops it to 5V.
- **VCC pin**: regulated 5V only. This bypasses the regulator, so never feed 9V here.

When reprogramming a box, unplug the barrel adapter and connect USB alone. Standard Pro Micros tolerate both at once, but not every clone includes the protection diode that makes that safe.

---

## 9. What if you have an ESP32 or another board?

The workflow (VS Code + `arduino-cli` + terminal) and the code API (`setup()`, `loop()`, `analogRead()`, `Serial`) are the same on virtually every hobby microcontroller. What changes:

**ESP32** — needs its own core (one-time setup), since it's not made by Arduino:

```bash
arduino-cli config init
arduino-cli config add board_manager.additional_urls https://espressif.github.io/arduino-esp32/package_esp32_index.json
arduino-cli core update-index
arduino-cli core install esp32:esp32
```

Then compile/upload with `--fqbn esp32:esp32:esp32` (run `arduino-cli board listall esp32` to find the exact FQBN for your specific board). No reset-button dance — uploads just work on most dev boards (a few require holding the **BOOT** button as the upload starts).

**Mac note:** ESP32 dev boards show up as `/dev/cu.usbserial-*`, `/dev/cu.wchusbserial*`, or `/dev/cu.SLAB_USBtoUART` rather than `usbmodem`. Recent macOS versions include the needed USB drivers; if `arduino-cli board list` shows nothing after plugging in, the board's USB chip (usually CH340 or CP210x) needs its driver installed — search "CH340 macOS driver" or "CP210x macOS driver". Also make sure you're using a **data** USB cable, not a charge-only one (the most common "board not detected" cause).

Two differences that **matter for the FSR circuit**:

1. **ESP32 is a 3.3V chip.** Power the voltage divider from the **3V3 pin, not 5V** — 5V on an analog pin can damage it.
2. **The ADC is 12-bit**: `analogRead()` returns **0–4095**, so the conversion is `raw * (3.3 / 4095.0)` and any thresholds scale up ~4×. Use a GPIO on ADC1 (**GPIO 32–39**) as the input — most ESP32 boards have no `A0` alias, and ADC2 pins stop working when WiFi is active.

**Other boards** (Nano 33, Raspberry Pi Pico, Teensy, …): same pattern — install that board's core, use its FQBN, and check its logic voltage. Classic AVR boards (Uno, Nano, Mega) are 5V and covered by `arduino:avr` already; almost everything newer is 3.3V.

