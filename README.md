# Arduino Sync Pulse Generator

A pseudo-random square wave generator for ATmega32U4-based Arduino boards, designed for temporal synchronization of multi-device experimental recordings.

## Purpose

When recording from multiple devices simultaneously (e.g., Vicon motion capture, EEG, eye tracking), each device has its own clock. By feeding the same pseudo-random sync signal into all devices, you can use **cross-correlation** in post-processing to precisely align all recordings temporally.

The pseudo-random pattern produces a sharp autocorrelation peak, making it far more robust for temporal alignment than a regular periodic signal.

## Hardware

Both supported boards use the ATmega32U4 at 5V/16MHz and are fully compatible.

| Board | Output pins | FQBN |
|---|---|---|
| Arduino Leonardo | 20 (0–13, A0–A5) | `arduino:avr:leonardo` |
| Pro Micro ATmega32U4 5V (e.g. Teyleten Type-C) | 18 (0–10, 14–16, A0–A3) | `arduino:avr:micro` |

- **Output voltage**: 5V HIGH / 0V LOW (hardware fixed by ATmega32U4)
- **Connection**: Wire any output pin + GND to a BNC cable for each device

If your equipment expects 3.3V logic, use a voltage divider or level shifter on the output.

> **Pro Micro note**: The standard Pro Micro footprint does not break out pins 11, 12, or 13.
> Use pins 0–10, 14–16, and A0–A3 for signal output (18 pins total).

## Setup

### Install Arduino CLI (macOS)

```bash
brew install arduino-cli
arduino-cli core update-index
arduino-cli core install arduino:avr
```

### Compile

**Arduino Leonardo:**
```bash
arduino-cli compile --fqbn arduino:avr:leonardo sync_pulse_generator
```

**Pro Micro ATmega32U4 5V:**
```bash
arduino-cli compile --fqbn arduino:avr:micro \
  --build-property "compiler.cpp.extra_flags=-DBOARD_PRO_MICRO" \
  sync_pulse_generator
```

### Upload

Both boards use the same upload command pattern. Find your port first:

```bash
arduino-cli board list
```

**Arduino Leonardo** — requires a double-tap of the reset button to enter bootloader mode:

1. Double-tap the reset button
2. Immediately run:

```bash
arduino-cli upload --fqbn arduino:avr:leonardo -p /dev/cu.usbmodemXXXX sync_pulse_generator
```

**Pro Micro ATmega32U4** — also requires a double-tap of the reset button. The port may change after the reset tap, so watch `board list` output and use the bootloader port (often a different address than the running port):

```bash
arduino-cli upload --fqbn arduino:avr:micro -p /dev/cu.usbmodemXXXX sync_pulse_generator
```

Replace `/dev/cu.usbmodemXXXX` with the port shown by `arduino-cli board list`.

## Configuration

### Compile-time defaults

Edit `sync_pulse_generator/config.h` to change default timing ranges and PRNG seed. These are loaded on first boot or after an EEPROM reset.

To target the Pro Micro pin layout, either uncomment `#define BOARD_PRO_MICRO` at the top of `config.h`, or pass `-DBOARD_PRO_MICRO` as a build flag (shown in the compile commands above).

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

Post-processing tools to align multi-device recordings using the sync channel. Located in `sync_pulse_generator/utils/` — see **[`utils/README.md`](sync_pulse_generator/utils/README.md)** for full documentation, worked examples for two and for many signals, and the complete function reference.

### Three ways to align

| Method | Use when | Files |
|---|---|---|
| **Cross-correlation** | Both copies of the signal look alike | `sync_align.*` |
| **Edge timing** | One copy went through an EMG amplifier, or you want per-transition error bars | `edge_sync.*`, `detect_edges`, `edge_delay` |
| **Timecode frames** | You need absolute time, or to know which generator run a recording belongs to | `timecode.*`, `decode_timecode`, `align_to_timecode` |

An EMG amplifier's high-pass turns each step into a transient spike, so the two waveforms stop resembling each other and correlation degrades — but their transition *times* still line up exactly, which is what edge timing measures.

### Languages

All three implement the same functions with the same names and behaviour.

| Language | Location | Dependencies |
|----------|----------|--------------|
| Python   | `utils/python/` | numpy (scipy only for EMG filtering) |
| MATLAB   | `utils/matlab/` | base MATLAB (Signal Processing Toolbox optional) |
| R        | `utils/R/` | base R + stats (`signal` only for EMG filtering) |

### Core functions

- **`load_c3d_analog`** — Dependency-free C3D reader (no BTK or ezc3d needed), plus Nexus CSV exports. Takes rate, labels, and scaling from the file.
- **`detect_edges`** — Square-wave transitions to sub-sample precision. Two detectors: a Schmitt trigger for directly recorded signals, and signed peak detection for EMG-passed ones. Reports onset rather than peak by default, avoiding a 1–2 ms bias.
- **`edge_delay`** — Delay between two edge trains, matched by polarity and causally. Returns median, spread, per-polarity agreement, drift, and plain-language quality warnings.
- **`sync_report`** — One call for every sync channel in a recording, with a full pairwise matrix.
- **`shift_timestamps`** — Apply a measured delay to any number of channels, by relabelling time (lossless) or resampling.
- **`process_emg`** — Standard EMG chain returning every intermediate stage, with flat/railed channel detection.
- **`decode_timecode` / `align_to_timecode`** — Absolute anchors and run identity; refuses to fit across a generator restart.
- **`find_sync_lag` / `align_recordings`** — Cross-correlation alignment (offset, merge, bundle modes).

### Python CLI

```bash
# Every sync channel in a file, measured against a reference
python edge_sync.py report SquareWaveTest01.c3d

# Two named channels
python edge_sync.py delay trial.c3d --ref SquareDirect --test SquareWirelessEmg

# List what a file contains
python edge_sync.py channels trial.c3d

# Write a copy with corrected timestamps
python edge_sync.py shift trial.c3d --delay 20.6 -o corrected.csv

# Cross-correlation (the older path)
python sync_align.py lag file1.csv file2.mat --sync-col sync --fs 1000
python sync_align.py generate --seed 42 --duration 60 --fs 1000 -o expected.csv
```

Recordings in separate files, from separate devices, at different sample rates all compare directly — edge times are in seconds, so no resampling is needed.

## Author

Nathan Baune — Emory University

## License

MIT License. See [LICENSE](LICENSE).
