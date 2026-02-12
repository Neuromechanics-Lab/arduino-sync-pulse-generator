# Arduino Sync Pulse Generator

A pseudo-random square wave generator for Arduino Leonardo, designed for temporal synchronization of multi-device experimental recordings.

## Purpose

When recording from multiple devices simultaneously (e.g., Vicon motion capture, EEG, eye tracking), each device has its own clock. By feeding the same pseudo-random sync signal into all devices, you can use **cross-correlation** in post-processing to precisely align all recordings temporally.

The pseudo-random pattern produces a sharp autocorrelation peak, making it far more robust for temporal alignment than a regular periodic signal.

## Hardware

- **Board**: Arduino Leonardo (ATmega32U4)
- **Output voltage**: 5V HIGH / 0V LOW (hardware fixed)
- **Output pins**: All 20 digital I/O pins (0-13, A0-A5) output the same signal simultaneously
- **Connection**: Wire any output pin + GND to a BNC cable for each device

If your equipment expects 3.3V logic, use a voltage divider or level shifter on the output.

## Setup

### Install Arduino CLI (macOS)

```bash
brew install arduino-cli
arduino-cli core update-index
arduino-cli core install arduino:avr
```

### Compile

```bash
arduino-cli compile --fqbn arduino:avr:leonardo sync_pulse_generator
```

### Upload

The Leonardo requires a double-tap of the reset button to enter bootloader mode before uploading:

1. Double-tap the reset button on the board
2. Immediately run:

```bash
arduino-cli upload --fqbn arduino:avr:leonardo -p /dev/cu.usbmodemXXXX sync_pulse_generator
```

Replace `/dev/cu.usbmodemXXXX` with the port shown by `arduino-cli board list`.

## Configuration

### Compile-time defaults

Edit `sync_pulse_generator/config.h` to change default timing ranges, PRNG seed, and pin assignments. These are loaded on first boot or after an EEPROM reset.

### Runtime commands

Connect via serial monitor at **115200 baud**:

| Command | Description |
|---------|-------------|
| `high <min> <max>` | Set HIGH duration range in ms (default: 50-500) |
| `low <min> <max>` | Set LOW duration range in ms (default: 50-500) |
| `seed <value>` | Set PRNG seed and restart pattern (default: 42) |
| `save` | Persist current settings to EEPROM |
| `reset` | Revert to config.h defaults |
| `start` | Start signal output |
| `stop` | Stop signal output (pins LOW) |
| `restart` | Re-seed PRNG and restart with same seed |
| `config` | Show current configuration |
| `help` | Show available commands |

### Persistence

Settings changed via serial commands are **not** saved automatically. Use `save` to write them to EEPROM so they survive power cycles. Use `reset` to revert to compile-time defaults.

## Reproducibility

The generator uses a deterministic xorshift32 PRNG. The same seed always produces the same sequence, so you can verify alignment across sessions or regenerate the expected pattern in analysis software.

## Alignment Utilities

Post-processing tools to cross-correlate the sync channel across recordings and compute temporal offsets. Located in `sync_pulse_generator/utils/`.

### Languages

| Language | Location | Dependencies |
|----------|----------|--------------|
| Python   | `utils/python/sync_align.py` | numpy, scipy, pandas |
| MATLAB   | `utils/matlab/` (3 functions) | built-in + Signal Processing Toolbox |
| R        | `utils/R/sync_align.R` | base R + stats (optional: R.matlab) |

### Functions

All three languages implement the same core functions:

- **`load_recording`** — Load data from CSV/TXT/MAT files or in-memory objects. Auto-detects format. Accepts time column or sampling rate.
- **`generate_sync_signal`** — Reproduce the exact Arduino PRNG sequence at any sample rate. Useful for aligning against the expected pattern without a reference device.
- **`find_sync_lag`** — Cross-correlate two sync channels (handles different sample rates). Returns lag in seconds/samples, peak correlation, and confidence.
- **`align_recordings`** — Align multiple recordings to a reference. Modes: `offset` (add aligned timestamps), `merge` (interpolate to common time base), `bundle` (correct timestamps, no interpolation).

### Python CLI

```bash
# Find lag between two recordings
python sync_align.py lag file1.csv file2.mat --sync-col sync --fs 1000

# Align multiple recordings, output merged CSV
python sync_align.py align file1.csv file2.mat file3.txt --sync-col sync --mode merge -o aligned.csv

# Generate expected sync signal to CSV
python sync_align.py generate --seed 42 --duration 60 --fs 1000 -o expected.csv
```

### Input Formats

Each function accepts file paths (CSV, TXT, MAT) or in-memory data (DataFrame, matrix, array). Sync channel specified by column name or index. Time info via `time_col` or `fs` parameter.

## Author

Nathan Baune — Emory University

## License

MIT License. See [LICENSE](LICENSE).
