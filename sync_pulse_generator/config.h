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
// All 20 digital pins on Leonardo, output the same signal simultaneously.
// Wire any pin + GND to a BNC cable for each device.
// USB is handled internally by ATmega32U4 and doesn't use any pins.
//
// Pins 0-13:  Digital header pins
//   0,1 = also HW UART (Serial1) - safe as outputs
//   2,3 = also I2C (SDA/SCL) - safe as outputs
//   13  = also onboard LED (will mirror the signal)
//
// Pins A0-A5 (18-23): Analog header pins, usable as digital outputs
#define NUM_OUTPUT_PINS 20

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
