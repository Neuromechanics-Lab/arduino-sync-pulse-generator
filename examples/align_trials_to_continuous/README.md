# Aligning epoched trials to a continuous recording

Finds where short epoched trials (Vicon/Nexus) sit inside a long continuous
recording (BrainVision EEG), using the sync square wave both systems captured.

MIT licensed — see `LICENSE` at the repository root.

## The problem

Nexus gives you trials. The EEG is one long file. Neither says where a trial
lives in the other.

The usual answers work until they don't: wall clocks drift and nobody writes
down the offset, trigger counts assume nothing was aborted or restarted, and
matching trial numbers assumes both systems agree about what counts as a
trial. Each fails silently — you get an alignment, it looks plausible, and the
error surfaces three analyses later as noise nobody can explain.

## The idea

The box emits a square wave whose HIGH and LOW durations are pseudo-random,
50 to 500 ms in 5 ms steps. Both systems record the same physical signal.

Pseudo-random means any short stretch is unique. Six consecutive intervals —
205, 135, 480, 80, 465, 175 ms — occur in that order exactly once. Find them in
the continuous file's copy and you have found the trial, to the sample.

Nothing about clocks enters into it. The EEG amplifier in the reference
dataset runs 96 ppm slow, which is 57 ms accumulated over ten minutes, and it
makes no difference: both systems recorded the same edges, so whatever either
clock did it did to both copies.

## Two answers, two questions

| column | answers | needs |
|---|---|---|
| `eeg_sample0` | which samples of the continuous file is this trial? | the two recordings |
| `box_time` | when did this happen, on a clock that never stopped? | the generator's seed and config |

The first is what you want for epoching. The second earns its place when a
recording was paused — the reference perception file concatenates three
segments with roughly 12 and 9 minutes missing at the joins, so sample 936501
reads as 936 s into the file and is really 2211 s after recording began. The
generator kept running through both breaks.

Each recording locates independently: the continuous file does not need the
trials to find itself, and a trial does not need the continuous file. Any two
recordings then relate through the generator without ever being compared,
which is what places trials either side of a pause at their true separation.

## Running it

```matlab
addpath('sync_pulse_generator/utils/matlab')
align_trials_to_continuous
```

Edit the config block to point at your own data. The example paths refer to an
Emory dataset that is not in this repository — it is participant data.

## Two things that vary between datasets

**Column names.** The script discovers them rather than hardcoding. In the
reference dataset `fitsData1` and `fitsData2` use `Square_Wave_1`/`atime_1`
while `fitsData3` uses `Square_Wave_2`/`atime_2` — the suffix is the
perturbation number, not the table number. The case to worry about is not an
error; it is a table where the name you assumed exists and holds a different
perturbation. The alignment then succeeds, confidently, against the wrong
event. Check the column names the script reports.

**Whether the wave is a channel or events.** This example assumes a continuous
analog channel — the wave plugged into an input and sampled. Some setups feed
it to a digital trigger input instead, and every transition arrives as an event
marker (a `.vmrk` entry rather than `.eeg` samples). The method is identical;
the code path is not.

Read marker sample positions directly instead of calling `detect_edges`. You
lose sub-sample interpolation, because a marker is already an integer sample —
1 ms at 1 kHz rather than the 0.1 ms here. Markers usually carry one polarity
where a detector reports both, so the two interval sequences differ by a factor
of two unless you compare like with like.

Count them before assuming. The reference dataset's `.vmrk` markers are
experiment events, 19 and 49 of them, against 2195 transitions of the actual
wave on the analog channel. A handful means events; thousands mean the wave.

## What it uses

- `detect_edges` — transition times interpolated between samples rather than
  snapped to the nearest one.
- `select_edges` — narrows a reference edge list to the window a trial
  overlaps. Without it `edge_delay` pairs three seconds of test against ten
  minutes of reference and reports "no edges paired", which reads as a data
  problem and is a windowing mistake.
- `edge_delay` — pairs two edge lists respecting polarity and causality, flags
  outliers, reports per-polarity agreement and drift.
- `align_template` with `'variant','simple'`, then `template_locate` — for
  `box_time`. The variant matters: choosing wrong does not degrade a lock, it
  prevents one.

## Results on the reference dataset

| table | condition | located | worst residual |
|---|---|---|---|
| fitsData1 | single, 1 perturbation | 17/17 | 0.207 ms |
| fitsData2 | perception, 1st perturbation | 47/47 | 0.262 ms |
| fitsData3 | perception, 2nd perturbation | 47/47 | 0.246 ms |

Residuals are measured over every edge in the trial, not only the six used to
match, so agreement on the rest is independent of how the position was found.

Three checks the matching does not enforce, and therefore worth reading. Every
match was unique. Trial order came out monotonic. And `fitsData2` and
`fitsData3` — the two perturbations of the same trials, located completely
independently — agree on their interval to 4.3 ms sd across all 47.

The EEG's own `S 15` markers land 1021 ms before the aligned perturbation, sd
9.8 ms, on all 17 single-condition trials. That spread is somewhere in the
marker-to-perturbation path: trigger dispatch, platform actuation, marker
timestamping, or deliberate jitter in the paradigm. This measurement cannot
say which, only that it is not in the alignment.
