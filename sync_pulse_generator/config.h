/*
 * config.h - Compile-time defaults for Sync Pulse Generator
 *
 * Edit these values to change the defaults that are loaded on
 * first boot or after an EEPROM reset. Once running, use Serial
 * commands to adjust at runtime, then 'save' to persist to EEPROM.
 *
 * Voltage: Arduino Leonardo outputs 5V HIGH, 0V LOW (hardware fixed).
 * If your equipment expects 3.3V, use a voltage divider or level shifter.
 * If your equipment expects TTL (>2.4V = HIGH), 5V works directly.
 */

#ifndef CONFIG_H
#define CONFIG_H

// ---- Identity: firmware, protocol, hardware -------------------------------
// THREE VERSIONS, because they change independently and for different reasons.
// Collapsing them into one number is what makes old recordings undecodable:
// you can no longer tell whether a firmware bump changed the signal or only
// fixed a typo in a serial message.
//
//   FW_VERSION        this build. Bump for any change at all.
//   PROTOCOL_VERSION  THE SIGNAL ON THE WIRE. Bump ONLY when a decoder written
//                     for the previous version would mis-read this one:
//                     timecode frame layout, symbol widths, the event marker
//                     shape, the PRNG or its draw order. Never for a serial
//                     message, a comment, or a default that is transmitted in
//                     the config anyway.
//   HW_VARIANT        which physical build this firmware is for. Determines
//                     pin counts and what is wired to what.
//
// The protocol version is the one analysis depends on. A recording is only
// interpretable if you know which protocol produced it, and since the box is
// often recorded by devices that never see the serial port, the protocol
// version is reported in the config AND is implicit in the timecode frame
// layout itself.
#define FW_VERSION        "1.1.0"
#define PROTOCOL_VERSION  2      // 1 = pre-event-channel; 2 = adds the event
                                 //     channel and its 8-bit marker payload
#define FW_DATE           __DATE__

#ifdef BOARD_PRO_MICRO
  #define HW_VARIANT      "promicro"
#else
  #define HW_VARIANT      "leonardo"
#endif



// ---- Output Pins ----
// Pin count differs by board; see the per-board section below.
// USB is handled internally by ATmega32U4 and doesn't consume any pins.
// All listed pins output the same signal simultaneously.
// Wire any pin + GND to a BNC cable for each device.
//
// Arduino Leonardo (default)
//   20 pins: 0-13, A0-A5 (18-23)
//   0,1  = also HW UART (Serial1) - safe as outputs
//   13   = also onboard LED (will mirror the signal)
//
// Pro Micro ATmega32U4 (Type-C)
//   18 pins: 0-10, 14-16, A0-A3 (18-21)
//   0,1  = also HW UART (Serial1) - safe as outputs
//   No pin 11, 12, 13 broken out on standard Pro Micro footprint.
//   A0-A3 = pins 18-21 in Arduino numbering.
//
// Select your board by passing -DBOARD_PRO_MICRO to the compiler, or
// uncomment the define below:
// #define BOARD_PRO_MICRO

#ifdef BOARD_PRO_MICRO
  #define NUM_OUTPUT_PINS 18
#else
  #define NUM_OUTPUT_PINS 20
#endif

// ---- Timing Defaults (milliseconds) ----
// HIGH duration range: how long the signal stays at 5V
#define DEFAULT_MIN_HIGH_MS  50
#define DEFAULT_MAX_HIGH_MS  500

// LOW duration range: how long the signal stays at 0V
#define DEFAULT_MIN_LOW_MS   50
#define DEFAULT_MAX_LOW_MS   500

// ---- PRNG Seed ----
// Fixed seed for reproducible patterns.
// Same seed = same sequence every power cycle.
// Change this to get a different pattern.
#define DEFAULT_PRNG_SEED    42

// ---- Timecode frames (hybrid absolute-time encoding) ----
// Every DEFAULT_TC_INTERVAL_S seconds of run time, the pseudo-random train
// is interrupted by one FRAME encoding elapsed seconds since PRNG start:
//
//   preamble:  3 pulses (TC_PULSE_MS high) separated by TC_PREAMBLE_GAP_MS
//   payload:   52 bits, one bit per gap between pulses (TC_GAP_ZERO_MS = 0,
//              TC_GAP_ONE_MS = 1), MSB first:
//                [16-bit run ID][32-bit elapsed seconds][4-bit checksum]
//              run ID = EEPROM boot counter, incremented on every PRNG
//              (re)start — (run ID, elapsed) uniquely identifies every
//              moment the box has ever emitted, across power cycles.
//              checksum = XOR of all nibbles of run ID and elapsed.
//
// The frame is fully deterministic and does NOT consume PRNG draws, so the
// complete hybrid signal is still reproducible from (seed, config) — see
// utils/python/timecode.py. RESERVED-GAP RULE: with timecode enabled, keep
// DEFAULT_MIN_HIGH_MS + DEFAULT_MIN_LOW_MS well above TC_PULSE_MS +
// TC_GAP_ONE_MS (defaults: 100 vs 30) so frame timing can never be imitated
// by the random section.
// FRAMES START EXACTLY ON THE INTERVAL TICK: the random segment that would
// cross (tick - TC_LEADIN_MS) is cut short there, the output holds LOW for
// the lead-in, and the first preamble pulse rises ON the tick. So a decoded
// frame's first edge marks exactly `elapsed` seconds of generator time.
// 20 ms (not 10) so a cut-short HIGH stub followed by the lead-in gives a
// 25 ms edge interval — neither a preamble (15) nor a bit (20/30).
#define DEFAULT_TC_ENABLED    1     // 1 = frames on, 0 = pure pseudo-random
#define DEFAULT_TC_INTERVAL_S 10    // seconds between frames (min 2)
#define TC_LEADIN_MS          20    // forced LOW before each frame tick
#define TC_PULSE_MS           5     // frame pulse width (constant)
#define TC_PREAMBLE_GAP_MS    10    // gap inside the 3-pulse preamble
#define TC_GAP_ZERO_MS        15    // bit gap meaning 0
#define TC_GAP_ONE_MS         25    // bit gap meaning 1

// ---- TRIG input / mode switch (PRE-Sync rear panel) ----
// SPDT toggle picks FREE RUN (output starts at boot) or TRIG RUN (outputs
// stay LOW until a rising edge arrives on the TRIG IN BNC — lets several
// boxes start in sync from one master pulse). Wire the switch common to
// MODE_SWITCH_PIN and the FREE-RUN throw to GND (internal pullup). TRIG IN:
// BNC center -> ~1k series resistor -> TRIG_IN_PIN (internal pullup; an
// idle master holding 0V arms it — the input must sit LOW for
// TRIG_ARM_LOW_MS before a rising edge counts, so an unconnected jack can
// never false-trigger). Both pins are excluded from the output set.
#define TRIG_FEATURE        1
#define TRIG_IN_PIN         2
#define MODE_SWITCH_PIN     3
// FREE RUN is the OPEN throw, not the closed one — deliberately, so the box
// free-runs when nothing is wired to MODE_SWITCH_PIN.
//
// The pin is INPUT_PULLUP, so an unwired or disconnected switch floats HIGH.
// With the old value (1 = closed-to-GND means FREE RUN) that read as TRIG RUN:
// the outputs were held LOW waiting for a trigger that never came, and a box
// with no switch fitted — or one whose wire came loose mid-session — sat
// silent with no indication anything was wrong. Silence is the worst failure
// this device has, because it is only discovered later, in analysis, when
// nothing aligns.
//
// Inverted, an unwired pin reads FREE RUN and the box emits. A switch that
// fails open now fails into working.
//
// WIRING: connect the switch so its FREE RUN throw leaves the pin OPEN and its
// TRIG RUN throw closes to GND. On a panel already legended for the old
// convention, rotate the toggle 180 degrees — the label then reads correctly
// again with no change to the wiring itself.
#define MODE_FREE_IS_LOW    0   // open throw = FREE RUN (see above)
#define TRIG_ARM_LOW_MS     20

// EEPROM address of the persistent 16-bit run counter (separate from the
// config block so 'save' never touches it; wraps at 65535).
#define EEPROM_RUNID_ADDR   64

// ---- Trigger behaviour (runtime-settable; these are only the defaults) ----
// What TRIG IN does, as a mode rather than a fixed behaviour, so one firmware
// serves several experimental designs and a host app can set it over serial
// without recompiling.
//
//   TRIG_EDGE_START  a rising edge starts a run; further edges are ignored
//                    until the mode switch is cycled. The original behaviour.
//   TRIG_EDGE_TOGGLE a rising edge starts a run, the NEXT edge stops it, and
//                    so on — trial start/stop from one line.
//   TRIG_LEVEL_GATE  output runs while TRIG IN is HIGH and stops when it goes
//                    LOW. The run clock restarts on each rising edge, so every
//                    gated segment is its own run with its own ID.
#define TRIG_MODE_EDGE_START   0
#define TRIG_MODE_EDGE_TOGGLE  1
#define TRIG_MODE_LEVEL_GATE   2
#define DEFAULT_TRIG_MODE      TRIG_MODE_EDGE_START

// ---- Lead-in marker pulse (runtime-settable) --------------------------------
// On a trigger, optionally emit ONE clean pulse, hold LOW for a fixed pause,
// and only then begin the pseudo-random train. A single unambiguous flash is
// far easier to find in video than a pseudo-random train is — a camera
// recording an LED can be aligned off that one event without decoding
// anything.
//
// The run clock starts at the LEADING EDGE OF THAT PULSE, so embedded
// timecode stays referenced to the trigger instant. The pause is a known
// constant, so analysis can place the train relative to the marker exactly.
#define DEFAULT_LEADIN_PULSE_ENABLED 0    // 1 = emit the marker pulse
#define DEFAULT_LEADIN_PULSE_MS      50   // marker pulse width
#define DEFAULT_LEADIN_PAUSE_MS      500  // LOW hold before the train starts

// ---- Event channel (PRE-Sync v1.1) -----------------------------------------
// One output is split off from the sync train and carries EVENTS instead:
// every trigger that arrives on TRIG IN emits a marker there. The remaining
// outputs carry the pseudo-random train untouched.
//
// WHY A SEPARATE CHANNEL. The train and an event marker want opposite things.
// The train is 50-500 ms pulses that any recorder, camera included, follows
// easily — but interrupting it to announce an event costs template lock for
// everyone who missed the interruption. The event marker wants to be long,
// unmistakable, and carry an identifier. Giving each its own BNC costs one
// output out of eighteen and lets both be right.
//
// WHAT THE MARKER IS. The mark pulse's LEADING EDGE is the event, at interrupt
// latency (~4 us). Everything after it is payload and does not affect timing,
// so the accuracy is identical no matter how much is encoded. The payload is
// an 8-bit event counter, so a camera that saw only this channel can still
// tell trigger 3 from trigger 7 — the one thing a plain event flag cannot do.
//
// WHY THESE WIDTHS. Sized for the slowest recorder that might see it. At 24
// fps a frame is 41.7 ms, and a pulse must exceed one full frame interval to
// be caught regardless of phase — with a short exposure, closer to twice it.
// 50 ms symbols clear that; the 200 ms mark is unmistakable at any rate.
//
// The whole marker is about 1250 ms. Triggers closer together than that abort
// the payload in progress: the MARK ALWAYS FIRES, the counter is best-effort.
// Event timing is never sacrificed to finish an identifier.
#define EVENT_CHANNEL_ENABLED 1
#define EVENT_CHANNEL_PIN     9    // excluded from the sync train when enabled
#define EVENT_MARK_MS         200  // the event itself; leading edge = timestamp
#define EVENT_GAP_MS          50   // between symbols
#define EVENT_BIT0_MS         50   // short symbol = 0
#define EVENT_BIT1_MS         100  // long symbol  = 1
#define EVENT_COUNTER_BITS    8    // 0-255, wraps

// ---- EEPROM ----
// Magic byte to detect if EEPROM has valid saved config.
// Change this value to force a reset to defaults on next boot.
// (0xA7 -> 0xA8 timecode fields; 0xA8 -> 0xA9 trigger mode + lead-in marker.)
#define EEPROM_MAGIC  0xA9

#endif
