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
// These pins output the same signal simultaneously.
// Wire any pin + GND to a BNC cable for each device.
// Leonardo digital pins 2-13 are available.
#define OUTPUT_PIN_1  2
#define OUTPUT_PIN_2  3
#define OUTPUT_PIN_3  4
#define OUTPUT_PIN_4  5

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
