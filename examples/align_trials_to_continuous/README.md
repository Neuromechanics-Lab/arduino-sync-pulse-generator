# Aligning epoched trials to a continuous recording

A worked example: find where short epoched trials (Vicon/Nexus) sit inside a
long continuous recording (BrainVision EEG), using the sync square wave both
systems recorded.

MIT licensed — see `LICENSE` at the repository root.

## The idea

The generator emits a square wave whose HIGH and LOW durations are
pseudo-random, drawn in 5 ms steps from 50–500 ms. Because the durations are
pseudo-random, any short stretch of the wave carries an interval pattern that
occurs nowhere else — a run of six intervals is effectively a fingerprint.
Find that pattern in the continuous recording's copy of the wave and you have
found exactly where the trial sits.

No clocks, no timestamps, no assumptions about sample rate, no trigger
counting.

## Two answers, two questions

| column | answers | needs |
|---|---|---|
| `eeg_sample0` | which samples of the continuous file is this trial? | nothing but the two recordings |
| `box_time` | when did this happen, on a clock that never stopped? | the generator's seed and config |

The first is what you want for epoching. The second matters when a recording
was paused: the generator kept running through the break, so two trials either
side of a pause come out correctly separated by real elapsed time — which file
position cannot express, because nothing was written during the gap.

Each recording locates **independently**. The continuous file does not need
the trials to find itself, and a trial does not need the continuous file. That
makes the alignment transitive: any two recordings relate through the
generator, with no reference device and no pairwise matrix.

## Running it

```matlab
addpath('sync_pulse_generator/utils/matlab')
align_trials_to_continuous
```

Edit the config block to point at your own data. The example paths refer to an
Emory dataset that is **not** in this repository — it is participant data.

## Two things that vary between datasets

**Column names.** The script discovers them rather than hardcoding. In the
reference dataset `fitsData1`/`fitsData2` use `Square_Wave_1`/`atime_1` while
`fitsData3` uses `Square_Wave_2`/`atime_2` — the suffix is the *perturbation*
number, not the table number. The dangerous case is not an error but a table
where the assumed name exists and holds a different perturbation; the script
then aligns confidently to the wrong event. Check the reported column names.

**Whether the wave is a channel or events.** This example assumes a
**continuous analog channel** — the wave plugged into an input and sampled.
Some setups feed it into a digital trigger input instead, so each transition
arrives as an **event marker** (a `.vmrk` entry rather than `.eeg` samples).
The method is unchanged but the code path differs:

- Read marker sample positions instead of calling `detect_edges`.
- No sub-sample interpolation — markers are whole samples, so timing is
  quantised to 1 ms at 1 kHz rather than the ~0.1 ms achieved here.
- Markers usually carry **one polarity** (rising only), while `detect_edges`
  returns both. The interval sequences then differ by a factor of two. Compare
  like with like.
- Check the count first. In the reference dataset the `.vmrk` markers are
  experiment events (19 and 49 of them), not the wave, which has 2195
  transitions on the analog channel. A handful means events; hundreds or
  thousands means the wave.

## What it uses

- `detect_edges` — transition times to sub-sample precision, interpolating
  across the threshold rather than taking the nearest sample. At 1 kHz that is
  the difference between 1 ms quantisation and ~0.1 ms.
- `select_edges` — narrows a reference edge list to the window a trial
  overlaps. Without it `edge_delay` pairs three seconds of test against ten
  minutes of reference and reports "no edges paired".
- `edge_delay` — pairs two edge lists respecting polarity and causality,
  flags outliers, and reports per-polarity agreement and drift.

## Results on the reference dataset

| table | condition | located | worst residual |
|---|---|---|---|
| fitsData1 | single, 1 perturbation | 17/17 | 0.207 ms |
| fitsData2 | perception, 1st perturbation | 47/47 | ~0.3 ms |
| fitsData3 | perception, 2nd perturbation | 47/47 | ~0.3 ms |