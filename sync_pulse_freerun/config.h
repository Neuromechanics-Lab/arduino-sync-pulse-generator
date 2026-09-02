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

// ---- TRIG input / mode switch — DISABLED IN THIS BUILD ----
// This is the FREE-RUN-ONLY variant: identical to sync_pulse_generator in
// every other respect (same PRNG, same seed, same timecode frames, same run
// counter, same serial commands), but with no trigger input and no mode
// switch. Output begins at power-up and continues for as long as the board
// is powered.
//
// Why a separate build rather than just leaving the switch in FREE RUN:
//   * Nothing to set wrong. A box that can only free-run cannot be found
//     mid-session sitting in TRIG mode waiting for an edge that never comes.
//   * Two more output pins. TRIG_IN_PIN and MODE_SWITCH_PIN are excluded from
//     the output set in the full firmware; here they carry the signal like
//     any other pin.
//   * No panel hardware required. A build with no TRIG BNC and no toggle can
//     run this without leaving unread inputs floating.
//
// The emitted waveform is byte-identical to the full firmware in FREE RUN, so
// recordings made with either are interchangeable and align against the same
// template.
//
// To re-enable triggering, use ../sync_pulse_generator instead. Do not simply
// flip this back to 1 — the pin definitions below are gone.
#define TRIG_FEATURE        0

// EEPROM address of the persistent 16-bit run counter (separate from the
// config block so 'save' never touches it; wraps at 65535).
#define EEPROM_RUNID_ADDR   64

// ---- EEPROM ----
// Magic byte to detect if EEPROM has valid saved config.
// Change this value to force a reset to defaults on next boot.
// (0xA7 -> 0xA8 when the timecode fields were added to the layout.)
#define EEPROM_MAGIC  0xA8

#endif
