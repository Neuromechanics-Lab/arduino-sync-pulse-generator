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

// ---- EEPROM ----
// Magic byte to detect if EEPROM has valid saved config.
// Change this value to force a reset to defaults on next boot.
#define EEPROM_MAGIC  0xA7

#endif
