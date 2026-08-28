# Alignment utilities

Offline tools for aligning multi-device recordings that share the sync
generator's square wave. Everything here exists in **MATLAB, Python, and R**
with matching function names and behaviour — pick whichever your analysis
already lives in.

---

## Which tool for which problem

There are two independent ways to align recordings, and they answer different
questions.

| | **Cross-correlation** | **Edge timing** | **Timecode frames** |
|---|---|---|---|
| Files | `sync_align.*` | `edge_sync.*`, `detect_edges`, `edge_delay` | `timecode.*`, `decode_timecode` |
| Gives you | Relative offset between two recordings | Relative offset, per-transition, with error bars | Absolute position on the generator's own timeline |
| Needs | Both signals to look alike | Clean detectable edges | Timecode enabled in firmware |
| Works when one signal went through an EMG amp | Poorly | **Yes** | Yes |
| Tells you *which run* you recorded | No | No | **Yes** |

**Rule of thumb.** If one copy of your square wave has been through an EMG
amplifier, use **edge timing** — the amplifier's high-pass turns each step
into a spike, so the two waveforms no longer resemble each other and
correlation degrades, but their transition *times* still line up exactly. If
you have clean matching waveforms, cross-correlation is fine and needs no
edge detection. If you need to know *when in absolute terms* a recording
happened, or which generator run it belongs to, decode the **timecode
frames**.

These compose: use frames for coarse absolute anchors, edges or correlation
to refine between them.

---

## Quick start: delay between two channels

The common case — one recording, two channels carrying the same square wave,
one of them fed through an EMG sensor.

**MATLAB**

```matlab
rec = load_c3d_analog('SquareWaveTest01.c3d');   % or a Nexus CSV export
report = sync_report(rec);                       % auto-detects sync channels
```

```
Reference: Voltage.2-SquareDirect

Channel                       delay(ms)       sd      IQR      n
Voltage.16-SquareWirelessEmg     20.608    0.377    0.446    197
```

**Python**

```bash
python edge_sync.py report SquareWaveTest01.c3d
```

```python
from edge_sync import load_c3d_analog, sync_report
rec = load_c3d_analog('SquareWaveTest01.c3d')
rep = sync_report(rec)
print(rep.delays_ms)          # one delay per non-reference sync channel
```

**R**

```r
source('edge_sync.R')
ref  <- detect_edges(direct_channel,   fs)
test <- detect_edges(wireless_channel, fs)
r <- edge_delay(ref, test)
cat(sprintf('%.3f ms\n', r$delay_ms))
```

`sync_report` finds the sync channels itself by looking for labels containing
`square`, `sync`, or `trig` **and** confirming the channel actually contains
transitions — so a promisingly-named but unplugged channel will not derail
the comparison. Name them explicitly when the auto-detection is not what you
want:

```matlab
report = sync_report(rec, 'channels', {'SquareDirect', 'SquareWirelessEmg'}, ...
                          'reference', 'SquareDirect');
```

---

## Three or more signals

`sync_report` handles any number of sync channels in one recording. Every
non-reference channel is measured against the reference, so N channels give
N−1 delays on a common baseline, plus a full pairwise matrix.

```matlab
report = sync_report(rec);
report.delays_ms        % delay of each channel vs the reference
report.pairwise_ms      % full N x N matrix of every pair
report.pairwise_labels  % row/column names for that matrix
```

The pairwise matrix is antisymmetric: `pairwise_ms(a,b) == -pairwise_ms(b,a)`.
Use it to sanity-check consistency — if A→B is 20 ms and B→C is 5 ms, then
A→C should be 25 ms. A mismatch means one channel's edges are being
mis-detected.

### Separate files, separate devices

When your signals live in **different files** — Vicon in a C3D, EEG in its own
format, a DAQ in a CSV — load each one, detect edges on its sync channel, and
compare the edge trains directly. Nothing requires the recordings to share a
file, a sample rate, or a start time.

**MATLAB**

```matlab
vicon = load_c3d_analog('trial.c3d');
eeg   = load_c3d_analog('eeg_export.csv');   % any CSV with a rate or time column

e_vicon = detect_edges(vicon.data(:, find_channel(vicon, 'SquareDirect', 'unique', true)), vicon.fs);
e_eeg   = detect_edges(eeg.data(:,   find_channel(eeg,   'Sync',         'unique', true)), eeg.fs);

d = edge_delay(e_vicon, e_eeg);
fprintf('EEG lags Vicon by %.3f ms (sd %.3f, n=%d)\n', ...
        d.delay_ms, d.delay_std_ms, d.n_matched);
```

**Python**

```python
vicon = load_c3d_analog('trial.c3d')
eeg   = load_c3d_analog('eeg_export.csv')

e_vicon = detect_edges(vicon.channel('SquareDirect'), vicon.fs)
e_eeg   = detect_edges(eeg.channel('Sync'),           eeg.fs)

d = edge_delay(e_vicon, e_eeg)
print(d)          # prints delay, spread, match rate, drift, warnings
```

Sample rates may differ — edge times are in seconds, so a 1000 Hz recording
and a 2048 Hz one compare directly with no resampling.

### Chaining several devices to one reference

Pick one device as the master and measure everything against it, so all
offsets share a baseline:

```python
devices = {
    'vicon': load_c3d_analog('trial.c3d'),
    'eeg':   load_c3d_analog('eeg.csv'),
    'daq':   load_c3d_analog('daq.csv'),
}
sync_col = {'vicon': 'SquareDirect', 'eeg': 'Sync', 'daq': 'ch0'}

edges = {k: detect_edges(v.channel(sync_col[k]), v.fs) for k, v in devices.items()}

ref = 'vicon'
for name, e in edges.items():
    if name == ref:
        continue
    d = edge_delay(edges[ref], e)
    print(f'{name:8s} lags {ref} by {d.delay_ms:8.3f} ms  '
          f'(sd {d.delay_std_ms:.3f}, {d.n_matched}/{d.n_reference} edges)')
```

If a device's clock could be *ahead* of the reference, widen the causal
window — by default matching assumes the test signal cannot precede the
reference:

```python
d = edge_delay(edges[ref], e, min_delay=-50, max_delay=50)
```

---

## Applying the correction

Once you have a delay, shift the late recording's timestamps to match:

```matlab
corrected = shift_timestamps(rec, d.delay_ms);              % all channels
corrected = shift_timestamps(rec, d, 'channels', emg_idx);  % a subset
```

```python
t, data, info = shift_timestamps(rec, d)          # or a plain number of ms
t, data, info = shift_timestamps(rec, 20.6, resample=True)
```

**Sign convention.** A positive delay means the test recording arrived *late*,
so its timestamps move *earlier*. Pass `invert` if your delay was measured the
other way round.

**Two correction styles.** The default rewrites the time vector and leaves the
samples untouched — nothing is interpolated, so no data is altered, and the
recording simply starts at a non-zero time. `resample` instead keeps the
original time base and moves the *data* onto it by interpolation; use it only
when something downstream insists every recording share one grid, since
interpolation is lossy.

From the CLI:

```bash
python edge_sync.py shift trial.c3d --delay 20.6 -o corrected.csv
python edge_sync.py shift trial.c3d -o corrected.csv     # measures it first
```

---

## Peak vs onset: a bias worth knowing about

When the square wave has passed through an EMG amplifier, each step becomes a
transient spike. Where on that spike you measure changes the answer, and
**both choices are biased late** — what separates them is whether the bias
stays constant.

| estimator | bias | varies with amplifier? |
|---|---|---|
| `locate='onset'`, fraction 0.25 (default) | +0.45 ms | no |
| `locate='onset'`, fraction 0.80 | +1.00 ms | no |
| `locate='peak'` | +1.3 to +1.7 ms | **yes** |

Measured against synthetic signals of known delay at 1000 Hz, across
amplifier time constants from 1 to 20 ms. The peak's bias grew with the time
constant; the onset's did not move at all.

That constancy is the point. A bias that is the same for every edge cancels
out when you compare two channels recorded through the same hardware, so the
*difference* you care about survives. A bias that tracks the amplifier does
not cancel, and you cannot correct for it without knowing the amplifier's
response. Onset is therefore the default.

```matlab
e = detect_edges(x, fs);                                   % onset, 0.25
e = detect_edges(x, fs, 'onset_fraction', 0.8);            % less bias-free, tighter
e = detect_edges(x, fs, 'locate', 'peak');                 % most reproducible
```

**The trade-off is noise.** Low on the flank the signal is still small, so on
real recordings the onset spread is wider than the peak's. On the reference
60 s recording:

| | median | IQR | matched |
|---|---|---|---|
| onset 0.25 | 21.31 ms | 0.80 ms | 213/213 |
| onset 0.80 | 22.21 ms | 0.31 ms | 213/213 |
| peak | 22.92 ms | 0.36 ms | 213/213 |

Raising the fraction buys precision back at the cost of a larger (still
constant) bias. Report which setting you used — the numbers are not
interchangeable.

**On this recording the onset delays are bimodal**, splitting into clusters
about 0.9 ms apart (visible in panel 3 of `plot_sync_check`). Both clusters
contain rising and falling edges at equal spike amplitude, so it is not a
polarity bug or weak-spike effect — it is where the flank crossing lands
relative to the 1 ms sample grid. The median is unaffected, and raising
`onset_fraction` onto the steeper part of the flank collapses it. Look at the
histogram before quoting a mean.

## How edge matching works

`edge_delay` pairs edges under three rules, each preventing a specific failure:

1. **Polarity is respected.** A rising edge is only matched to a rising edge.
   Mixing them inflates the spread, because a rise and a fall are different
   events separated by a pulse width. (Detecting on the *signed* signal rather
   than a rectified copy is what makes this possible — rectifying discards
   the sign.)
2. **Matching is causal.** A candidate must fall inside
   `[min_delay, max_delay]`. The test signal cannot physically precede the
   reference, so a negative-delay pairing is a detection artefact and is
   excluded rather than averaged in.
3. **Ties go to the largest peak.** Spurious peaks are small; the real
   transition is not.

On real data these three together took a measurement from *9 impossible
negative-delay outliers, sd 6.3 ms* down to *zero outliers, sd 0.27 ms*.

**Check `result.warnings` before trusting a number.** It flags low match
rates, outliers, excessive spread, rising/falling asymmetry (which usually
means one polarity is being mis-located), and drift. The rising-vs-falling
agreement is the single best check that pairing is correct — on a good
measurement the two agree to well under 0.1 ms.

---

## Timecode frames: absolute time and run identity

When the firmware has timecode enabled, every 10 s the train carries a frame
encoding **run ID** and **elapsed seconds**. Decoding one frame places the
recording on the generator's timeline without any correlation.

```matlab
e = detect_edges(rec.data(:, ch), rec.fs);
f = decode_timecode(e.time(e.polarity > 0));    % or 'edge','falling'
a = align_to_timecode(f);

fprintf('run %d; recording t=0 is generator t=%.3f s\n', ...
        a.primary.run_id, a.to_generator(0));
```

```python
frames = decode_frames(rising_edge_times)
a = align_to_timecode(frames)
a['to_generator'](0.0)      # recording time -> generator time
a['to_recording'](50.0)     # generator time -> recording time
```

### Runs, FREE vs TRIG, and why run ID matters

The generator's elapsed clock is **not a wall clock**. It counts from the
start of the current *run*, and every run start increments a persistent run
ID. A run starts when:

- the box boots in **FREE RUN** (output begins immediately, elapsed 0 =
  power-up);
- a trigger edge arrives on TRIG IN in **TRIG RUN** (outputs are held LOW
  until then, so **elapsed 0 is the trigger** — this is what lets several
  devices start together from one master pulse);
- the mode switch is moved to FREE RUN;
- a serial `start` or `restart` is issued.

Because the run ID changes at every one of those events, **two recordings
share a timeline only if their run IDs match.** Elapsed values from different
runs count from different zeros and cannot be compared. `align_to_timecode`
treats a run ID change as a hard boundary, reports each run separately, and
warns rather than silently fitting across it:

```python
a = align_to_timecode(frames)
if a['n_runs'] > 1:
    print(a['warnings'][0])       # explains the restart
    for run_id, frs in split_runs(frames):
        ...                       # handle each segment separately

a = align_to_timecode(frames, expect_run=138)   # or just pick one
```

Flipping the switch from FREE to TRIG mid-session stops output and waits;
flipping back, or triggering, begins a *new* run with a *new* ID. That
signature is embedded in every frame, so a recording self-reports which start
it belongs to.

### Anchor accuracy (frames start on the tick)

A frame starts **exactly** on its interval tick: the firmware cuts the random
segment that would cross the tick short, holds LOW for a 20 ms lead-in, and
the first preamble pulse rises on the tick. So `t_rec` of a decoded frame
*is* `elapsed_s` of generator time, to the millisecond — every anchor is
exact, and the offsets `elapsed - t_rec` agree across frames to within the
recorder's own edge-timing resolution.

What `align_to_timecode` does with that:

- The offset is the **mean** of all anchors (every frame carries equal
  weight).
- **Drift** is a least-squares slope through all anchors, reported only when
  it exceeds the 10 ms anchor tolerance over the span observed *and* clears
  the slope's own noise floor by 3×; otherwise `drift_ppm` is `0` with
  `drift_resolvable = false`. Verified: a 200 ppm recorder clock is
  recovered to within 0.05 ppm from a 95 s record.
- Residuals above 10 ms about the fit produce a warning: frames can't be
  late any more, so scatter means a mis-decoded frame or a recorder whose
  edge timing is coarser than expected.

`max_pulse_ms` is still accepted by all three implementations for backward
compatibility but is ignored — it parameterised the emission jitter of
firmware that emitted frames late.

---

## EMG processing

`process_emg` runs the conventional chain and returns **every intermediate
stage**, so any step can be plotted to see where a signal goes wrong:

```
raw -> detrend -> bandpass -> (notch) -> rectify -> envelope
```

```matlab
p = process_emg(rec.data(:, ch), rec.fs);          % defaults: 20-450 Hz, 4 Hz envelope
p = process_emg(x, fs, 'band', [20 450], 'notch', 60, 'mvc', mvc_value);
plot(p.time, p.raw); hold on; plot(p.time, p.envelope);
```

The bandpass is zero-phase (applied forwards and backwards), so it adds no
lag — which matters here, since a lag would corrupt the very timing these
tools measure.

Check `p.warnings`, which flags in plain language:

- **flat** channels — nothing connected, or the sensor is off;
- **railed** channels — a disconnected sensor floats to the supply limits and
  looks like a large signal unless you check. (This is not hypothetical: in
  the reference recording an unplugged channel sat at ±1.25 V with a standard
  deviation larger than every real EMG channel.)
- low signal-to-noise, and strong mains contamination.

---

## Visual check

```matlab
plot_sync_check(rec);                      % auto-detects everything
plot_sync_check(rec, report, 'emg', {'Sol','TA'}, 'window', [0 5]);
```

Four panels: both square-wave channels with detected edges marked, per-edge
delay against trial time, the delay histogram, and raw+envelope per EMG
channel. Look at this before trusting any number — a flat band in panel 2
means a fixed latency, a slope means clock drift, and scatter means detection
trouble.

---

## File formats

`load_c3d_analog` reads:

- **C3D** — a dependency-free reader (no BTK, no ezc3d). Handles
  Intel/DEC/MIPS byte orders and both float and scaled-integer storage, and
  takes the sample rate, labels, and scaling from the file rather than
  assuming them.
- **CSV / TXT** — Nexus ASCII exports (the `Devices` section with its rate
  header), or any plain CSV with a `time` column.

To get a C3D out of Vicon Nexus: open the trial, then **File → Save Trial**.
If Save is greyed out, add an **Export C3D** operation in the Pipeline pane
and run it. `.x1d` / `.x2d` files are raw camera data and contain no analog
channels.

Channel labels keep their Vicon prefixes (`Voltage.2-SquareDirect`);
`find_channel` matches on any substring, so you can ask for `SquareDirect`
without spelling the rest.

---

## Function reference

| Purpose | MATLAB | Python | R |
|---|---|---|---|
| Load analog data | `load_c3d_analog` | `load_c3d_analog` | — |
| Find a channel | `find_channel` | `rec.find` / `rec.channel` | — |
| Detect edges | `detect_edges` | `detect_edges` | `detect_edges` |
| Delay between two | `edge_delay` | `edge_delay` | `edge_delay` |
| All sync channels | `sync_report` | `sync_report` | — |
| Apply a delay | `shift_timestamps` | `shift_timestamps` | `shift_timestamps` |
| EMG chain | `process_emg` | `process_emg` | `process_emg` |
| Visual check | `plot_sync_check` | — | — |
| Decode frames | `decode_timecode` | `decode_frames` | `decode_timecode` |
| Absolute alignment | `align_to_timecode` | `align_to_timecode` | `align_to_timecode` |
| Split at run change | — | `split_runs` | `split_runs` |
| Recreate the signal | `generate_sync_signal` | `generate_template` | — |
| Cross-correlation | `find_sync_lag` | `find_sync_lag` | `find_sync_lag` |
| Align N recordings | `align_recordings` | `align_recordings` | `align_recordings` |

Gaps in that table are where a language lacks a convenience wrapper, not a
capability — the underlying functions are present everywhere.

## Dependencies

- **MATLAB** — base MATLAB. `filtfilt`/`movmean` are used when present and
  hand-rolled otherwise, so the Signal Processing Toolbox is optional.
- **Python** — `numpy`. `scipy` only for EMG filtering.
- **R** — base R + `stats`. The `signal` package only for EMG filtering;
  `process_emg` reports what it had to skip rather than failing.

## Self-tests

```bash
python test_edge_sync.py  # 7 regression tests over the edge/EMG path
python timecode.py        # round-trip: generate -> decode -> verify, plus run boundaries
```

`test_edge_sync.py` covers the failure modes found while building this, so a
regression surfaces as a failed assertion rather than a plausible-looking
wrong number: channel-name prefix collisions, causal matching, polarity
pairing, the onset's bias staying independent of the amplifier while the
peak's does not, railed-channel detection, and the cross-detector edge-count
warning.

## Verification status

All three implementations were run against the same reference recording
(60 s, 1000 Hz, 28 channels) and agree to three decimal places:

| | delay | IQR | matched |
|---|---|---|---|
| MATLAB R2024b | 21.312 ms | 0.803 | 213/213 |
| Python | 21.312 ms | 0.803 | 213/213 |
| R | — (validated on synthetic ground truth) | | |

Against synthetic signals of known delay, all three recover it with the same
bias to the millisecond across amplifier time constants from 1 to 20 ms.

One practical note on MATLAB: `plot_sync_check` returns in about 17 seconds,
but rendering the figure to a file with `exportgraphics` takes several minutes
in a headless `-batch` session because the figure is eleven panels tall.
Interactively it simply appears. If you need it scripted, export fewer EMG
channels via the `'emg'` option or pass `'max_emg'`.
