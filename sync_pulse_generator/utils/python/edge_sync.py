#!/usr/bin/env python3
"""
edge_sync.py - Edge-based delay measurement and EMG processing.

Measures the delay between two or more recordings of the same square wave by
locating the individual signal edges, rather than by cross-correlating the
waveforms (which sync_align.py does). Edge timing is the better tool when one
copy of the signal has been through an EMG amplifier, because the amplifier's
high-pass turns each step into a transient spike: the waveforms no longer
resemble each other, but their transition times still line up.

Companion to sync_align.py. Use that one for whole-waveform correlation, this
one when you have clean edges and want a per-transition answer with error bars.

Usage as a module:
    from edge_sync import load_c3d_analog, detect_edges, edge_delay, sync_report

    rec = load_c3d_analog('SquareWaveTest01.c3d')
    rep = sync_report(rec)
    print(rep.delays_ms)

Usage as a CLI:
    python edge_sync.py report SquareWaveTest01.c3d
    python edge_sync.py delay SquareWaveTest01.c3d --ref SquareDirect --test SquareWirelessEmg
    python edge_sync.py shift SquareWaveTest01.c3d --delay 22.99 -o corrected.csv

Dependencies: numpy. scipy is used for EMG filtering when available.
"""

from __future__ import annotations

import argparse
import os
import struct
import sys
from dataclasses import dataclass, field
from typing import Optional, Sequence, Union

import numpy as np

try:
    from scipy import signal as sp_signal
    HAVE_SCIPY = True
except ImportError:                                      # pragma: no cover
    HAVE_SCIPY = False


# Onset location: the level, as a fraction of each spike's own height, at
# which the rising flank is timed. Sitting partway up the flank rather than
# down in the noise makes the crossing insensitive to noise and to where the
# samples happen to fall; see _signed_peaks for why that matters.
#
# Choosing the value trades bias against spread, and both were measured
# against synthetic signals of known delay (1000 Hz, amplifier time constants
# 1-20 ms):
#
#   estimator      bias        varies with amplifier?
#   onset @ 0.25   +0.45 ms    no
#   onset @ 0.80   +1.00 ms    no
#   peak           +1.3..1.7   YES
#
# 0.25 gives the smallest bias, and - the property that matters most - a
# bias that does not depend on the amplifier's response. A fixed bias
# cancels out of any comparison between two channels recorded through the
# same hardware, whereas the peak's does not.
#
# The cost is noise: low on the flank the signal is still small, so on real
# recordings the spread is wider than the peak's, and raising the fraction
# trades bias back for precision. Report which you used.
ONSET_FRACTION = 0.25


# ---------------------------------------------------------------------------
# Containers
# ---------------------------------------------------------------------------

@dataclass
class AnalogRecording:
    """Analog channels from a C3D or CSV export."""
    fs: float
    labels: list
    data: np.ndarray                  # samples x channels
    units: list = field(default_factory=list)
    filename: str = ""

    @property
    def n_samples(self) -> int:
        return self.data.shape[0]

    @property
    def n_channels(self) -> int:
        return self.data.shape[1]

    @property
    def duration(self) -> float:
        return self.n_samples / self.fs

    @property
    def time(self) -> np.ndarray:
        return np.arange(self.n_samples) / self.fs

    def find(self, pattern: str, unique: bool = False):
        """Channel indices whose label contains `pattern`, case-insensitive."""
        pat = pattern.lower()
        hits = [i for i, l in enumerate(self.labels) if pat in l.lower()]
        if unique:
            if not hits:
                raise ValueError(
                    f"No channel matching {pattern!r}. "
                    f"Available: {', '.join(self.labels)}")
            if len(hits) > 1:
                names = ", ".join(self.labels[i] for i in hits)
                raise ValueError(
                    f"Pattern {pattern!r} matched {len(hits)} channels: {names}")
            return hits[0]
        return hits

    def channel(self, spec: Union[int, str]) -> np.ndarray:
        """One channel's samples, by index or name pattern."""
        idx = spec if isinstance(spec, (int, np.integer)) else self.find(spec, unique=True)
        return self.data[:, idx]


@dataclass
class Edges:
    """Detected transitions in a square wave."""
    time: np.ndarray          # seconds
    polarity: np.ndarray      # +1 rising, -1 falling
    amplitude: np.ndarray
    mode: str
    fs: float
    noise: float

    @property
    def n_rising(self) -> int:
        return int(np.sum(self.polarity > 0))

    @property
    def n_falling(self) -> int:
        return int(np.sum(self.polarity < 0))

    def __len__(self) -> int:
        return len(self.time)


@dataclass
class DelayResult:
    """Delay between two edge trains."""
    delay_ms: float
    delay_mean_ms: float
    delay_std_ms: float
    delay_iqr_ms: float
    ci95_ms: float
    n_matched: int
    n_reference: int
    match_rate: float
    rising: dict
    falling: dict
    drift_ms_per_s: float
    drift_total_ms: float
    intercept_ms: float
    times: np.ndarray
    deltas_ms: np.ndarray
    polarities: np.ndarray
    n_outliers: int
    outlier_idx: np.ndarray
    warnings: list

    def __str__(self) -> str:
        lines = [
            f"delay        {self.delay_ms:.3f} ms (median)",
            f"mean         {self.delay_mean_ms:.3f} +/- {self.ci95_ms:.3f} ms (95% CI)",
            f"spread       sd {self.delay_std_ms:.3f} ms, IQR {self.delay_iqr_ms:.3f} ms",
            f"matched      {self.n_matched}/{self.n_reference} edges "
            f"({100*self.match_rate:.0f}%)",
            f"rising       {self.rising['median_ms']:.3f} ms (n={self.rising['n']})",
            f"falling      {self.falling['median_ms']:.3f} ms (n={self.falling['n']})",
            f"drift        {self.drift_total_ms:+.3f} ms across the trial",
        ]
        if self.warnings:
            lines.append("warnings:")
            lines += [f"  - {w}" for w in self.warnings]
        return "\n".join(lines)


@dataclass
class SyncReport:
    """Delays of every sync channel against a reference."""
    reference: str
    ref_index: int
    channels: list
    ch_indices: list
    all_indices: list
    delays_ms: np.ndarray
    results: list
    edges: list
    pairwise_ms: np.ndarray
    pairwise_labels: list
    warnings: list

    def __str__(self) -> str:
        w = max([28] + [len(c) for c in self.channels])
        out = [f"Reference: {self.reference}", ""]
        out.append(f"{'Channel':<{w}} {'delay(ms)':>10} {'sd':>8} {'IQR':>8} {'n':>6}")
        for lab, r in zip(self.channels, self.results):
            out.append(f"{lab:<{w}} {r.delay_ms:>10.3f} {r.delay_std_ms:>8.3f} "
                       f"{r.delay_iqr_ms:>8.3f} {r.n_matched:>6d}")
        if self.warnings:
            out += ["", "Warnings:"] + [f"  - {x}" for x in self.warnings]
        return "\n".join(out)


# ---------------------------------------------------------------------------
# C3D reading
# ---------------------------------------------------------------------------

def load_c3d_analog(filename: str) -> AnalogRecording:
    """
    Read analog channels from a C3D file, with no external C3D library.

    Handles Intel/DEC/MIPS processor codes and both float and scaled-integer
    storage. Marker data is skipped; this reader is for analog channels.

    A .csv or .txt path is read as a Nexus ASCII export instead.
    """
    if not os.path.exists(filename):
        raise FileNotFoundError(filename)

    if filename.lower().endswith((".csv", ".txt")):
        return _load_csv(filename)

    with open(filename, "rb") as fh:
        raw = fh.read()

    if len(raw) < 512:
        raise ValueError(f"{filename} is too short to be a C3D file.")

    param_block = raw[0]
    key = raw[1]
    if key != 80:
        raise ValueError(
            f"{filename} is not a C3D file (header key {key}, expected 80).")

    proc = _processor_type(raw, param_block)
    endian = ">" if proc == 3 else "<"

    def u16(off):
        return struct.unpack_from(endian + "H", raw, off)[0]

    def real(off):
        if proc == 2:
            return _dec_to_ieee(raw[off:off + 4])
        return struct.unpack_from(endian + "f", raw, off)[0]

    n_points         = u16(2)
    analog_per_frame = u16(4)
    first_frame      = u16(6)
    last_frame       = u16(8)
    point_scale      = real(12)
    data_block       = u16(16)
    analog_subframes = u16(18)
    video_rate       = real(20)

    if analog_subframes == 0 or analog_per_frame == 0:
        raise ValueError(f"{filename} contains no analog channels.")

    n_frames = last_frame - first_frame + 1
    n_channels, rem = divmod(analog_per_frame, analog_subframes)
    if rem:
        raise ValueError("Analog channel count is not an integer.")

    params = _read_parameters(raw, param_block, proc, endian)

    fs = _param_scalar(params, "ANALOG", "RATE", video_rate * analog_subframes)
    if not fs or fs <= 0:
        fs = video_rate * analog_subframes

    used = int(_param_scalar(params, "ANALOG", "USED", n_channels) or n_channels)
    n_used = used if 0 < used <= n_channels else n_channels

    labels = _param_strings(params, "ANALOG", "LABELS", n_channels)
    units  = _param_strings(params, "ANALOG", "UNITS", n_channels)

    scale  = _fit(_param_vector(params, "ANALOG", "SCALE", [1.0]), n_channels, 1.0)
    offset = _fit(_param_vector(params, "ANALOG", "OFFSET", [0.0]), n_channels, 0.0)
    gen    = _param_scalar(params, "ANALOG", "GEN_SCALE", 1.0) or 1.0

    is_float = point_scale < 0
    start = (data_block - 1) * 512
    n_rows = n_frames * analog_subframes
    n_total = n_rows * n_channels

    if n_points == 0:
        dtype = np.dtype(endian + ("f4" if is_float else "i2"))
        need = n_total * dtype.itemsize
        if start + need > len(raw):
            raise ValueError(
                f"File ended early: expected {need} bytes of analog data, "
                f"found {len(raw) - start}.")
        block = np.frombuffer(raw, dtype=dtype, count=n_total, offset=start)
        values = block.reshape(n_rows, n_channels).astype(np.float64)
    else:
        # Point and analog data interleave frame by frame.
        dtype = np.dtype(endian + ("f4" if is_float else "i2"))
        per_frame_points = n_points * 4
        per_frame_analog = analog_subframes * n_channels
        stride = per_frame_points + per_frame_analog
        need = n_frames * stride * dtype.itemsize
        if start + need > len(raw):
            raise ValueError("File ended early while reading interleaved data.")
        block = np.frombuffer(raw, dtype=dtype,
                              count=n_frames * stride, offset=start)
        block = block.reshape(n_frames, stride)
        values = block[:, per_frame_points:].reshape(n_rows, n_channels).astype(np.float64)

    scale = np.asarray(scale, dtype=float)
    offset = np.asarray(offset, dtype=float)
    if is_float:
        if np.any(scale != 1) or np.any(offset != 0):
            values = (values - offset) * scale * gen
    else:
        values = (values - offset) * scale * gen

    return AnalogRecording(
        fs=float(fs),
        labels=list(labels[:n_used]),
        data=values[:, :n_used],
        units=list(units[:n_used]),
        filename=filename,
    )


def _processor_type(raw: bytes, param_block: int) -> int:
    off = (param_block - 1) * 512 + 3
    if off + 1 >= len(raw):
        return 1
    code = raw[off + 1]
    return {85: 2, 86: 3}.get(code, 1)


def _dec_to_ieee(b: bytes) -> float:
    if len(b) < 4 or not any(b):
        return 0.0
    swapped = bytes([b[2], b[3], b[0], b[1]])
    word = struct.unpack("<I", swapped)[0]
    sign = (word >> 31) & 1
    expo = (word >> 23) & 0xFF
    mant = word & 0x7FFFFF
    if expo == 0:
        return 0.0
    val = (1 + mant / 2**23) * 2.0 ** (expo - 129)
    return -val if sign else val


def _read_parameters(raw: bytes, param_block: int, proc: int, endian: str) -> dict:
    """Walk the parameter linked list into {GROUP: {PARAM: (type, dims, data)}}."""
    params: dict = {}
    groups: dict = {}
    base = (param_block - 1) * 512
    off = base + 4
    guard = 0

    while off + 2 <= len(raw):
        guard += 1
        if guard > 20000:
            break
        n_char = struct.unpack_from("b", raw, off)[0]
        if n_char == 0:
            break
        gid = struct.unpack_from("b", raw, off + 1)[0]
        name_end = off + 2 + abs(n_char)
        if name_end + 2 > len(raw):
            break
        name = raw[off + 2:name_end].decode("ascii", "replace").strip().upper()
        next_off = struct.unpack_from(endian + "h", raw, name_end)[0]
        cursor = name_end + 2

        if gid < 0:
            groups[abs(gid)] = name
        else:
            if cursor + 2 > len(raw):
                break
            dtype_code = struct.unpack_from("b", raw, cursor)[0]
            n_dims = raw[cursor + 1]
            dims = list(raw[cursor + 2:cursor + 2 + n_dims]) or [1]
            dstart = cursor + 2 + n_dims
            n_elem = int(np.prod(dims))

            if dtype_code == -1:
                data = raw[dstart:dstart + n_elem].decode("ascii", "replace")
            elif dtype_code == 1:
                data = list(struct.unpack_from(f"{endian}{n_elem}b", raw, dstart))
            elif dtype_code == 2:
                data = list(struct.unpack_from(f"{endian}{n_elem}h", raw, dstart))
            elif dtype_code == 4:
                if proc == 2:
                    data = [_dec_to_ieee(raw[dstart + 4*k:dstart + 4*k + 4])
                            for k in range(n_elem)]
                else:
                    data = list(struct.unpack_from(f"{endian}{n_elem}f", raw, dstart))
            else:
                data = []

            gname = groups.get(gid, f"GROUP{gid}")
            params.setdefault(gname, {})[name] = (dtype_code, dims, data)

        if next_off == 0:
            break
        new_off = name_end + next_off
        if new_off <= off:
            break
        off = new_off

    return params


def _param_scalar(params, group, name, default=None):
    rec = params.get(group, {}).get(name)
    if not rec or not len(rec[2]):
        return default
    return float(rec[2][0])


def _param_vector(params, group, name, default):
    rec = params.get(group, {}).get(name)
    if not rec or not len(rec[2]):
        return list(default)
    return [float(v) for v in rec[2]]


def _param_strings(params, group, name, n_expected):
    out = [f"Channel{i+1}" for i in range(n_expected)]
    rec = params.get(group, {}).get(name)
    if not rec or rec[0] != -1 or len(rec[1]) < 2:
        return out
    width, count = rec[1][0], rec[1][1]
    chars = rec[2]
    for i in range(min(count, n_expected)):
        s = chars[i*width:(i+1)*width].strip()
        if s:
            out[i] = s
    return out


def _fit(vals, n, fill):
    vals = list(vals)
    if len(vals) == 1:
        return vals * n
    if len(vals) < n:
        return vals + [fill] * (n - len(vals))
    return vals[:n]


def _load_csv(filename: str) -> AnalogRecording:
    """Read a Nexus ASCII export, or a plain CSV with a time column."""
    with open(filename, "r") as fh:
        head = [fh.readline().rstrip("\n") for _ in range(200)]

    dev_idx = next((i for i, l in enumerate(head)
                    if l.strip().lower() == "devices"), None)

    if dev_idx is not None and dev_idx + 3 < len(head):
        fs = float(head[dev_idx + 1].split(",")[0])
        labels = [c.strip() for c in head[dev_idx + 3].split(",")]
        arr = np.genfromtxt(filename, delimiter=",", skip_header=dev_idx + 4)
        data = arr[:, 2:]
        labels = labels[2:2 + data.shape[1]]
    else:
        arr = np.genfromtxt(filename, delimiter=",", names=True)
        labels = list(arr.dtype.names)
        data = np.column_stack([arr[n] for n in labels])
        fs = None
        for cand in ("time", "t", "Time"):
            if cand in labels:
                col = labels.index(cand)
                fs = 1.0 / float(np.median(np.diff(data[:, col])))
                data = np.delete(data, col, axis=1)
                labels.pop(col)
                break
        if fs is None:
            raise ValueError(
                f"Could not determine the sample rate from {filename}. "
                "Export with the Nexus rate header, or use a .c3d file.")

    while len(labels) < data.shape[1]:
        labels.append(f"Channel{len(labels)+1}")

    return AnalogRecording(fs=float(fs), labels=labels[:data.shape[1]],
                           data=data, units=[""] * data.shape[1],
                           filename=filename)


# ---------------------------------------------------------------------------
# Edge detection
# ---------------------------------------------------------------------------

def _mad(x: np.ndarray) -> float:
    """Median absolute deviation, scaled to match the sd for Gaussian data."""
    return float(1.4826 * np.median(np.abs(x - np.median(x))))


def detect_edges(signal: np.ndarray,
                 fs: float,
                 mode: str = "auto",
                 hysteresis: Sequence[float] = (0.3, 0.7),
                 threshold: float = 8.0,
                 refractory: float = 30.0,
                 min_pulse: float = 5.0,
                 locate: str = "onset",
                 onset_threshold: float = 2.0) -> Edges:
    """
    Find square-wave transition times to sub-sample precision.

    Two acquisition paths need two detectors:

    mode='level'
        The square wave recorded directly. The signal holds its level between
        transitions, so a Schmitt trigger with hysteresis finds the state
        changes, and the crossing time is refined by linear interpolation
        across the mid-level threshold.

    mode='rectified'
        The square wave after an EMG amplifier. The amplifier's high-pass
        removes the DC level, so each step becomes a transient spike: a rising
        edge gives a positive spike, a falling edge a negative one. The
        detector therefore searches the SIGNED signal for positive and
        negative peaks separately, so each detection carries a known polarity.
        Peak times are refined by fitting a parabola through the peak and its
        neighbours.

        Working on the signed signal rather than a rectified copy is the whole
        point: rectifying discards the sign, and without the sign a rising
        edge can be paired with a falling one. See edge_delay.

    mode='auto'
        Chooses by looking at how much time the signal spends near mid-range.

    Parameters
    ----------
    hysteresis : Schmitt thresholds as fractions of the signal range.
    threshold  : rectified mode, peak threshold in MAD units.
    refractory : rectified mode, minimum ms between peaks of one polarity.
                 Stops post-transition ringing counting as a second edge.
                 Must be shorter than the shortest pulse in the pattern.
    min_pulse  : level mode, minimum ms a level must hold.
    locate     : rectified mode, which feature of the spike marks the
                 transition. 'onset' (default) times the rising flank;
                 'peak' uses the spike maximum.

                 Both are biased late; what separates them is whether the
                 bias is CONSTANT. The PEAK lags by the amplifier's rise
                 time, so its bias grows with the amplifier's time constant
                 (+1.3 to +1.7 ms across 1-20 ms in testing). The ONSET is
                 timed at a fixed fraction of each spike's height, so its
                 bias is the same whatever the amplifier (+0.45 ms at the
                 default fraction).

                 A constant bias cancels out of a comparison between two
                 channels recorded through the same hardware; a varying one
                 does not. Onset is therefore the default. Use 'peak' to
                 reproduce an older analysis, or when the flank is too noisy
                 for a stable onset.
    onset_threshold : absolute floor for the onset level, in MAD units, so a
                 tiny spike cannot be timed inside the noise. The level
                 actually used is the larger of this and ONSET_FRACTION of
                 the spike's own height.
    """
    x = np.asarray(signal, dtype=float).ravel()
    if x.size < 3:
        raise ValueError("Signal needs at least 3 samples.")
    if fs <= 0:
        raise ValueError("fs must be positive.")

    noise = _mad(x)

    if mode == "auto":
        mode = _classify(x)

    if mode == "level":
        t, p, a = _level_edges(x, fs, hysteresis, min_pulse)
    elif mode == "rectified":
        t, p, a = _rectified_edges(x, fs, noise, threshold, refractory,
                                   locate, onset_threshold)
    else:
        raise ValueError("mode must be 'level', 'rectified', or 'auto'.")

    return Edges(time=t, polarity=p, amplitude=a, mode=mode, fs=fs, noise=noise)


def _classify(x: np.ndarray) -> str:
    """A directly recorded square wave is bimodal; a differentiated one is not."""
    lo, hi = float(np.min(x)), float(np.max(x))
    rng = hi - lo
    if rng <= 0:
        return "level"
    mid_frac = np.mean((x > lo + 0.35 * rng) & (x < lo + 0.65 * rng))
    return "level" if mid_frac < 0.10 else "rectified"


def _level_edges(x, fs, hysteresis, min_pulse):
    lo, hi = float(np.min(x)), float(np.max(x))
    rng = hi - lo
    if rng <= 0:
        return np.array([]), np.array([]), np.array([])

    f_lo, f_hi = sorted(hysteresis)
    thr_lo = lo + f_lo * rng
    thr_hi = lo + f_hi * rng
    mid = (hi + lo) / 2.0
    min_gap = max(1, int(round(min_pulse * fs / 1000.0)))

    times, pols = [], []
    state = x[0] > thr_hi
    last_idx = -np.inf

    for i in range(1, x.size):
        up = (not state) and x[i] > thr_hi
        down = state and x[i] < thr_lo
        if not (up or down):
            continue
        state = up

        j = i
        while j > 0 and ((x[j] > mid) if up else (x[j] < mid)):
            j -= 1

        if j < x.size - 1:
            y0, y1 = x[j], x[j + 1]
            frac = (mid - y0) / (y1 - y0) if y1 != y0 else 0.0
            frac = min(max(frac, 0.0), 1.0)
            t_cross = (j + frac) / fs
        else:
            t_cross = j / fs

        if (j - last_idx) < min_gap:
            continue
        last_idx = j

        times.append(t_cross)
        pols.append(1 if up else -1)

    times = np.asarray(times, dtype=float)
    pols = np.asarray(pols, dtype=int)
    return times, pols, np.full(times.shape, rng)


def _rectified_edges(x, fs, noise, threshold, refractory,
                     locate="onset", onset_threshold=2.0):
    if noise <= 0:
        return np.array([]), np.array([]), np.array([])

    xc = x - np.median(x)
    thr = threshold * noise

    tp, ap = _signed_peaks(xc, +1, thr, fs, refractory,
                           locate, onset_threshold * noise)
    tn, an = _signed_peaks(xc, -1, thr, fs, refractory,
                           locate, onset_threshold * noise)

    t = np.concatenate([tp, tn])
    p = np.concatenate([np.ones(tp.size, dtype=int), -np.ones(tn.size, dtype=int)])
    a = np.concatenate([ap, an])

    order = np.argsort(t)
    return t[order], p[order], a[order]


def _signed_peaks(x, sign, thr, fs, refractory_ms,
                  locate="onset", onset_level=None):
    """
    Peaks of one polarity, held apart by a refractory period.

    When two candidates fall inside the refractory window the LARGER wins, so
    ringing after a real transition cannot displace the transition itself.

    `locate` selects which feature of each spike is reported as the edge
    time: 'peak' for the maximum, 'onset' for a fixed fraction of the way up
    the rising flank. Both lag the true transition, but the onset's lag does
    not depend on the amplifier's response, so it cancels out of a delay
    measurement between two channels; the peak's does not.
    """
    s = x * sign
    n = s.size
    above = s > thr
    if not above.any():
        return np.array([]), np.array([])

    # One candidate per supra-threshold run.
    edges_ = np.diff(above.astype(np.int8))
    starts = np.flatnonzero(edges_ == 1) + 1
    stops = np.flatnonzero(edges_ == -1) + 1
    if above[0]:
        starts = np.r_[0, starts]
    if above[-1]:
        stops = np.r_[stops, n]

    cand_idx, cand_val = [], []
    for a, b in zip(starts, stops):
        k = a + int(np.argmax(s[a:b]))
        cand_idx.append(k)
        cand_val.append(s[k])

    cand_idx = np.asarray(cand_idx)
    cand_val = np.asarray(cand_val)

    # Greedy largest-first under the refractory constraint.
    refrac = max(1, int(round(refractory_ms * fs / 1000.0)))
    kept = []
    for q in np.argsort(-cand_val):
        ci = cand_idx[q]
        if all(abs(ci - k) >= refrac for k in kept):
            kept.append(ci)
    kept = np.sort(np.asarray(kept, dtype=int))

    times = np.empty(kept.size)
    amps = np.empty(kept.size)
    if onset_level is None:
        onset_level = thr / 4.0

    for m, k in enumerate(kept):
        amps[m] = s[k]

        if locate == "onset":
            # Walk back from the peak to where the rising flank crosses a
            # level set as a FRACTION OF THIS SPIKE'S OWN AMPLITUDE, then
            # interpolate that crossing.
            #
            # An absolute threshold (a few MADs) sits in the noise at the very
            # foot of the flank, where the signal is nearly flat: which sample
            # first exceeds it then depends on noise, and the interpolated
            # time snaps to one sample or the next. On real data that split a
            # single population into two modes ~1 sample apart. A fractional
            # level sits on the steep part of the flank, where a small
            # amplitude error moves the crossing time very little, and it
            # scales automatically with spike size.
            #
            # The level is still a fixed fraction of the rise, so it remains a
            # constant delay after the true transition rather than tracking
            # it exactly - but that delay is identical for every edge of a
            # given shape, so it cancels out of a delay measurement.
            level = max(onset_level, ONSET_FRACTION * s[k])
            j = k
            while j > 0 and s[j] > level:
                j -= 1
            if j < k:
                y0, y1 = s[j], s[j + 1]
                frac = (level - y0) / (y1 - y0) if y1 != y0 else 0.0
                frac = min(max(frac, 0.0), 1.0)
                times[m] = (j + frac) / fs
            else:
                times[m] = j / fs
            continue

        # locate == 'peak': parabolic interpolation through the maximum.
        if 0 < k < n - 1:
            y0, y1, y2 = s[k - 1], s[k], s[k + 1]
            den = y0 - 2 * y1 + y2
            delta = 0.5 * (y0 - y2) / den if den != 0 else 0.0
            delta = min(max(delta, -1.0), 1.0)
        else:
            delta = 0.0
        times[m] = (k + delta) / fs

    return times, amps


# ---------------------------------------------------------------------------
# Delay between two edge trains
# ---------------------------------------------------------------------------

def edge_delay(edges_ref: Edges,
               edges_test: Edges,
               min_delay: float = -2.0,
               max_delay: float = 100.0,
               outlier_mad: float = 5.0) -> DelayResult:
    """
    Delay between two recordings of the same square wave, from their edges.

    A positive delay means the test signal arrives AFTER the reference.

    Matching rules, and why each one is there:

    1. Polarity is respected. A rising edge is only ever matched to a rising
       edge. Mixing polarities inflates the spread, because a rising and a
       falling transition are different events separated by a pulse width.

    2. Matching is causal. A candidate must fall within
       [min_delay, max_delay] of the reference edge. The test signal cannot
       physically precede the reference, so a negative-delay pairing is a
       detection artefact and is excluded rather than averaged in.

    3. Ties go to the largest peak. When several candidates sit inside the
       window, the strongest wins. Spurious peaks are small; the real
       transition is not.

    Together these turn a nearest-neighbour match into one that will not
    silently pair a real edge with noise.
    """
    if min_delay >= max_delay:
        raise ValueError("min_delay must be below max_delay.")
    if len(edges_ref) == 0 or len(edges_test) == 0:
        raise ValueError(
            f"Both inputs need edges (reference {len(edges_ref)}, "
            f"test {len(edges_test)}).")

    amp = np.abs(edges_test.amplitude) if edges_test.amplitude.size \
        else np.ones(len(edges_test))

    tr, dr = _match(edges_ref, edges_test, amp, +1, min_delay, max_delay)
    tf, df = _match(edges_ref, edges_test, amp, -1, min_delay, max_delay)

    times = np.concatenate([tr, tf])
    deltas = np.concatenate([dr, df])
    pols = np.concatenate([np.ones(tr.size, dtype=int),
                           -np.ones(tf.size, dtype=int)])

    if deltas.size == 0:
        raise ValueError(
            f"No edges paired inside [{min_delay}, {max_delay}] ms. Check that "
            "both channels carry the same square wave, and widen max_delay if "
            "the true delay could exceed it.")

    order = np.argsort(times)
    times, deltas, pols = times[order], deltas[order], pols[order]

    if deltas.size >= 3 and np.ptp(times) > 0:
        slope, intercept = np.polyfit(times, deltas, 1)
        drift_total = slope * np.ptp(times)
    else:
        slope, intercept, drift_total = 0.0, float(np.median(deltas)), 0.0

    med = float(np.median(deltas))
    mad = 1.4826 * np.median(np.abs(deltas - med))
    if outlier_mad > 0 and mad > 0:
        bad = np.abs(deltas - med) > outlier_mad * mad
    else:
        bad = np.zeros(deltas.shape, dtype=bool)

    q75, q25 = np.percentile(deltas, [75, 25])

    result = DelayResult(
        delay_ms=med,
        delay_mean_ms=float(np.mean(deltas)),
        delay_std_ms=float(np.std(deltas, ddof=1)) if deltas.size > 1 else 0.0,
        delay_iqr_ms=float(q75 - q25),
        ci95_ms=float(1.96 * np.std(deltas, ddof=1) / np.sqrt(deltas.size))
        if deltas.size > 1 else 0.0,
        n_matched=int(deltas.size),
        n_reference=len(edges_ref),
        match_rate=float(deltas.size / len(edges_ref)),
        rising=_stats(dr),
        falling=_stats(df),
        drift_ms_per_s=float(slope),
        drift_total_ms=float(drift_total),
        intercept_ms=float(intercept),
        times=times,
        deltas_ms=deltas,
        polarities=pols,
        n_outliers=int(bad.sum()),
        outlier_idx=np.flatnonzero(bad),
        warnings=[],
    )
    result.warnings = _quality(result, edges_ref, edges_test)
    return result


def _match(e_ref, e_test, amp, pol, min_delay, max_delay):
    """Pair each reference edge with the strongest same-polarity test edge
    inside the causal window."""
    ref_t = e_ref.time[e_ref.polarity == pol]
    sel = e_test.polarity == pol
    tst_t = e_test.time[sel]
    tst_a = amp[sel]

    if tst_t.size == 0 or ref_t.size == 0:
        return np.array([]), np.array([])

    times, deltas = [], []
    for t0 in ref_t:
        d_ms = (tst_t - t0) * 1000.0
        inwin = (d_ms >= min_delay) & (d_ms <= max_delay)
        if not inwin.any():
            continue
        idx = np.flatnonzero(inwin)
        best = idx[int(np.argmax(tst_a[idx]))]
        times.append(t0)
        deltas.append(d_ms[best])

    return np.asarray(times), np.asarray(deltas)


def _stats(d):
    if d.size == 0:
        return {"median_ms": float("nan"), "mean_ms": float("nan"),
                "std_ms": float("nan"), "n": 0}
    return {
        "median_ms": float(np.median(d)),
        "mean_ms": float(np.mean(d)),
        "std_ms": float(np.std(d, ddof=1)) if d.size > 1 else 0.0,
        "n": int(d.size),
    }


def _quality(r: DelayResult, e_ref: Edges, e_test: Edges) -> list:
    """Turn the numbers into plain statements about whether to trust them."""
    w = []
    if r.match_rate < 0.9:
        w.append(f"Only {100*r.match_rate:.0f}% of reference edges matched "
                 f"({r.n_matched} of {r.n_reference}). Check the detector "
                 f"settings on the test channel.")
    if r.n_outliers:
        w.append(f"{r.n_outliers} matched edges are more than 5 MADs from the "
                 f"median. Inspect them before trusting the mean.")
    if r.delay_std_ms > 2:
        w.append(f"Delay spread is {r.delay_std_ms:.2f} ms (sd). A fixed "
                 f"hardware latency should be well under 1 ms; this suggests "
                 f"detection problems or a genuinely variable link.")
    rm, fm = r.rising["median_ms"], r.falling["median_ms"]
    if np.isfinite(rm) and np.isfinite(fm) and abs(rm - fm) > 1:
        w.append(f"Rising and falling edges disagree by {abs(rm-fm):.2f} ms "
                 f"({rm:.3f} vs {fm:.3f}). Asymmetry this large usually means "
                 f"the detector is mis-locating one polarity.")
    if abs(r.drift_total_ms) > 1:
        w.append(f"Delay drifts {r.drift_total_ms:.2f} ms across the trial. The "
                 f"two devices may run on independent clocks; a single offset "
                 f"will not align them properly.")
    # Only compare edge counts when BOTH channels used the same detector.
    #
    # A level detector reports one edge per transition. A rectified detector
    # reports a positive AND a negative peak at every transition, because the
    # amplifier's response overshoots on the way back: a step up gives a
    # positive spike followed by a negative one. So a correctly detected
    # rectified channel legitimately has about twice the reference's edges
    # in EVERY polarity, and flagging that ratio calls a good detection bad.
    #
    # The real check on whether the pairing worked is the match rate and the
    # rising/falling agreement, both already covered above.
    if e_ref.mode == e_test.mode and len(e_ref) and len(e_test) > 1.5 * len(e_ref):
        w.append(f"Test channel yielded {len(e_test)} edges against "
                 f"{len(e_ref)} in the reference, using the same detector. "
                 f"Raise 'threshold' or 'refractory' if spurious peaks are "
                 f"being detected.")
    return w


# ---------------------------------------------------------------------------
# Multi-channel report
# ---------------------------------------------------------------------------

def sync_report(rec: AnalogRecording,
                channels: Optional[Sequence] = None,
                reference: Optional[Union[int, str]] = None,
                max_delay: float = 100.0) -> SyncReport:
    """
    Measure the delay of every sync channel against a reference.

    The one-call entry point for: given a recording carrying the same square
    wave on two or more channels, how far apart are they? Handles any number
    of sync channels, not only two.

    With `channels` unset it auto-detects any channel whose label mentions
    'square', 'sync', or 'trig' and which actually contains transitions.
    Every non-reference channel is compared against the reference, so N sync
    channels give N-1 delays on a common baseline.
    """
    if channels is None:
        idx = _autodetect(rec)
        if len(idx) < 2:
            raise ValueError(
                f"Found {len(idx)} sync channel(s) automatically. Name them "
                f"explicitly with `channels`. Labels present: "
                f"{', '.join(rec.labels)}")
    else:
        idx = [c if isinstance(c, (int, np.integer)) else rec.find(c, unique=True)
               for c in channels]

    if reference is None:
        ref_ch = idx[0]
    else:
        ref_ch = reference if isinstance(reference, (int, np.integer)) \
            else rec.find(reference, unique=True)
        if ref_ch not in idx:
            idx = [ref_ch] + list(idx)

    others = [i for i in idx if i != ref_ch]
    all_idx = [ref_ch] + others

    edges = [detect_edges(rec.data[:, i], rec.fs) for i in all_idx]

    results, delays, warns = [], [], []
    for k, ch in enumerate(others):
        r = edge_delay(edges[0], edges[k + 1], max_delay=max_delay)
        results.append(r)
        delays.append(r.delay_ms)
        warns += [f"[{rec.labels[ch]}] {w}" for w in r.warnings]

    n = len(all_idx)
    M = np.full((n, n), np.nan)
    for a in range(n):
        M[a, a] = 0.0
        for b in range(a + 1, n):
            try:
                rab = edge_delay(edges[a], edges[b], max_delay=max_delay)
                M[a, b] = rab.delay_ms
                M[b, a] = -rab.delay_ms
            except ValueError:
                pass

    return SyncReport(
        reference=rec.labels[ref_ch],
        ref_index=ref_ch,
        channels=[rec.labels[i] for i in others],
        ch_indices=others,
        all_indices=all_idx,
        delays_ms=np.asarray(delays),
        results=results,
        edges=edges,
        pairwise_ms=M,
        pairwise_labels=[rec.labels[i] for i in all_idx],
        warnings=warns,
    )


def _autodetect(rec: AnalogRecording) -> list:
    """Channels whose label mentions a sync signal AND which carry edges."""
    idx = [i for i, l in enumerate(rec.labels)
           if any(k in l.lower() for k in ("square", "sync", "trig"))]
    keep = []
    for i in idx:
        x = rec.data[:, i]
        if np.std(x) > 0 and len(detect_edges(x, rec.fs)) >= 4:
            keep.append(i)
    return keep


# ---------------------------------------------------------------------------
# Timestamp correction
# ---------------------------------------------------------------------------

def shift_timestamps(rec: AnalogRecording,
                     delay_ms: Union[float, DelayResult],
                     channels: Optional[Sequence[int]] = None,
                     resample: bool = False,
                     invert: bool = False,
                     method: str = "linear"):
    """
    Correct a recording's timestamps by a measured delay.

    `delay_ms` may be a number or a DelayResult, whose .delay_ms is used.

    Sign convention matches edge_delay: a positive delay means this recording
    arrived LATE, so its timestamps move EARLIER (the sample labelled t really
    happened at t - delay). Pass invert=True to reverse that.

    Two styles:

    Timestamp shift (default)
        Rewrites the time vector, leaves the samples untouched. Nothing is
        interpolated, so no data is altered.

    Resample (resample=True)
        Keeps the original time base and moves the DATA onto it by
        interpolation. Use when something downstream insists every recording
        share one grid. Interpolation is lossy, hence not the default.

    Returns (time, data, info) where info records what was applied.
    """
    d_ms = delay_ms.delay_ms if isinstance(delay_ms, DelayResult) else float(delay_ms)
    if not np.isfinite(d_ms):
        raise ValueError("delay_ms must be finite.")
    if invert:
        d_ms = -d_ms
    d_s = d_ms / 1000.0

    t = rec.time
    data = rec.data
    ch = list(range(rec.n_channels)) if channels is None else list(channels)
    if any(c < 0 or c >= rec.n_channels for c in ch):
        raise ValueError(f"Channel indices must be in [0, {rec.n_channels-1}].")

    info = {"shift_applied_ms": d_ms, "shift_channels": ch,
            "resampled": resample, "original_time": t}

    if not resample:
        if len(ch) == rec.n_channels:
            return t - d_s, data, info
        info["shifted_time"] = t - d_s
        info["note"] = (f"Only {len(ch)} of {rec.n_channels} channels were "
                        f"shifted; their time base is in info['shifted_time'].")
        return t, data, info

    src = t - d_s
    out = data.copy()
    for c in ch:
        v = data[:, c].astype(float)
        good = np.isfinite(v)
        if not good.any():
            continue
        out[:, c] = np.interp(t, src[good], v[good], left=np.nan, right=np.nan)
    return t, out, info


# ---------------------------------------------------------------------------
# EMG processing
# ---------------------------------------------------------------------------

def process_emg(signal: np.ndarray,
                fs: float,
                band: Optional[Sequence[float]] = (20.0, 450.0),
                order: int = 4,
                notch: Optional[float] = None,
                notch_q: float = 30.0,
                envelope: Optional[float] = 4.0,
                rms_window: float = 100.0,
                mvc: Optional[float] = None) -> dict:
    """
    Standard surface-EMG processing chain, returning every intermediate stage.

        raw -> detrend -> bandpass -> (notch) -> rectify -> envelope

    The bandpass is a zero-phase Butterworth applied with filtfilt, so it adds
    no phase lag - which matters here, since a lag would corrupt the very
    timing this module measures.

    The returned dict also carries a 'quality' block and plain-language
    'warnings', which flag flat channels (nothing plugged in) and railed ones
    (a disconnected sensor floats to the supply limits and can look like a
    large signal unless checked).
    """
    x = np.asarray(signal, dtype=float).ravel()
    if x.size < 10:
        raise ValueError("Signal needs at least 10 samples.")
    nyq = fs / 2.0

    out = {"raw": x, "fs": fs, "time": np.arange(x.size) / fs}
    out["quality"] = _emg_quality(x, fs, notch)

    y = x - np.mean(x)
    out["detrended"] = y

    if band is not None and len(band) == 2:
        lo, hi = float(band[0]), min(float(band[1]), 0.99 * nyq)
        if lo >= hi:
            raise ValueError(f"Bandpass {band} is invalid at fs={fs} Hz.")
        if not HAVE_SCIPY:
            raise ImportError("scipy is required for EMG filtering.")
        b, a = sp_signal.butter(order, [lo / nyq, hi / nyq], btype="bandpass")
        y = sp_signal.filtfilt(b, a, y)
    out["filtered"] = y

    if notch and 0 < notch < nyq:
        if not HAVE_SCIPY:
            raise ImportError("scipy is required for the notch filter.")
        b, a = sp_signal.iirnotch(notch / nyq, notch_q)
        y = sp_signal.filtfilt(b, a, y)
        out["notched"] = y
        out["filtered"] = y

    r = np.abs(y)
    out["rectified"] = r

    if envelope and 0 < envelope < nyq:
        if not HAVE_SCIPY:
            raise ImportError("scipy is required for the envelope filter.")
        b, a = sp_signal.butter(2, envelope / nyq, btype="low")
        out["envelope"] = np.maximum(sp_signal.filtfilt(b, a, r), 0.0)
    else:
        out["envelope"] = r

    w = max(1, int(round(rms_window * fs / 1000.0)))
    out["rms"] = np.sqrt(_movmean(y ** 2, w))

    if mvc:
        out["mvc_percent"] = 100.0 * out["envelope"] / mvc

    out["warnings"] = _emg_warn(out["quality"])
    return out


def _movmean(x, w):
    if w <= 1:
        return x.copy()
    c = np.concatenate([[0.0], np.cumsum(x)])
    n = x.size
    half = w // 2
    lo = np.clip(np.arange(n) - half, 0, n)
    hi = np.clip(np.arange(n) + half + 1, 0, n)
    return (c[hi] - c[lo]) / (hi - lo)


def _emg_quality(x, fs, notch_hz):
    n = x.size
    lo, hi = float(np.min(x)), float(np.max(x))
    rng = hi - lo
    q = {"range": rng, "std": float(np.std(x))}
    q["flat"] = rng < np.finfo(float).eps or q["std"] < np.finfo(float).eps

    if rng > 0:
        tol = 0.01 * rng
        q["frac_at_rail"] = float(np.mean((x >= hi - tol) | (x <= lo + tol)))
    else:
        q["frac_at_rail"] = 1.0
    q["saturated"] = q["frac_at_rail"] > 0.20

    e = _movmean(np.abs(x - np.median(x)), max(1, int(round(0.05 * fs))))
    es = np.sort(e)
    baseline = np.median(es[:max(1, n // 10)])
    peak = np.median(es[max(1, int(0.9 * n)):])
    q["snr_estimate"] = float(peak / baseline) if baseline > 0 else float("inf")

    q["mains_ratio"] = float("nan")
    f0 = notch_hz if notch_hz else 60.0
    if f0 < fs / 2 and n >= 4:
        nfft = int(2 ** np.ceil(np.log2(min(n, int(4 * fs)))))
        seg = x[:min(n, nfft)]
        seg = seg - np.mean(seg)
        P = np.abs(np.fft.fft(seg, nfft)) ** 2
        fax = np.arange(nfft) * fs / nfft

        def band_power(a, b):
            m = (fax >= a) & (fax < b)
            return float(np.mean(P[m])) if m.any() else 0.0

        at = band_power(f0 - 1, f0 + 1)
        near = band_power(f0 - 10, f0 - 2) + band_power(f0 + 2, f0 + 10)
        if near > 0:
            q["mains_ratio"] = at / (near / 2)
    return q


def _emg_warn(q):
    w = []
    if q["flat"]:
        w.append("Channel is flat - nothing is connected, or the sensor is off.")
    if q["saturated"]:
        w.append(f"Channel is railed: {100*q['frac_at_rail']:.0f}% of samples sit "
                 f"at the extremes. A disconnected sensor floats to the supply "
                 f"limits and looks like a large signal. Verify the electrode.")
    if not q["flat"] and not q["saturated"] and q["snr_estimate"] < 2:
        w.append(f"Low signal-to-noise ({q['snr_estimate']:.1f}x over baseline). "
                 f"The channel may be picking up noise, not muscle activity.")
    if np.isfinite(q["mains_ratio"]) and q["mains_ratio"] > 10:
        w.append(f"Strong mains component ({q['mains_ratio']:.0f}x its "
                 f"neighbours). Check the ground electrode, or enable 'notch'.")
    return w


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _cli_report(args):
    rec = load_c3d_analog(args.file)
    print(f"\n{os.path.basename(rec.filename)}")
    print(f"{rec.fs:g} Hz, {rec.duration:.1f} s, {rec.n_channels} channels\n")
    rep = sync_report(rec, max_delay=args.max_delay)
    print(rep)
    print()
    for lab, r in zip(rep.channels, rep.results):
        print(f"{lab}")
        for line in str(r).splitlines():
            print(f"   {line}")
        print()
    return 0


def _cli_delay(args):
    rec = load_c3d_analog(args.file)
    ref = detect_edges(rec.channel(args.ref), rec.fs)
    tst = detect_edges(rec.channel(args.test), rec.fs)
    print(f"\nreference {args.ref}: {len(ref)} edges ({ref.mode} detector)")
    print(f"test      {args.test}: {len(tst)} edges ({tst.mode} detector)\n")
    print(edge_delay(ref, tst, max_delay=args.max_delay))
    print()
    return 0


def _cli_channels(args):
    rec = load_c3d_analog(args.file)
    print(f"\n{os.path.basename(rec.filename)}  "
          f"{rec.fs:g} Hz  {rec.duration:.1f} s\n")
    print(f"{'#':>3} {'label':<32} {'min':>10} {'max':>10} {'sd':>10}")
    for i, lab in enumerate(rec.labels):
        c = rec.data[:, i]
        print(f"{i:>3} {lab:<32} {c.min():>10.4f} {c.max():>10.4f} {c.std():>10.4f}")
    print()
    return 0


def _cli_shift(args):
    rec = load_c3d_analog(args.file)
    if args.delay is None:
        rep = sync_report(rec)
        delay = float(rep.delays_ms[0])
        print(f"Measured delay: {delay:.3f} ms ({rep.channels[0]})")
    else:
        delay = args.delay
    t, data, info = shift_timestamps(rec, delay, resample=args.resample)
    header = "time," + ",".join(rec.labels)
    np.savetxt(args.output, np.column_stack([t, data]),
               delimiter=",", header=header, comments="", fmt="%.6f")
    print(f"Wrote {args.output} with timestamps shifted by "
          f"{info['shift_applied_ms']:.3f} ms")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Edge-based sync delay measurement for square-wave channels.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("report", help="measure every sync channel against a reference")
    p.add_argument("file")
    p.add_argument("--max-delay", type=float, default=100.0, dest="max_delay")
    p.set_defaults(func=_cli_report)

    p = sub.add_parser("delay", help="delay between two named channels")
    p.add_argument("file")
    p.add_argument("--ref", required=True)
    p.add_argument("--test", required=True)
    p.add_argument("--max-delay", type=float, default=100.0, dest="max_delay")
    p.set_defaults(func=_cli_delay)

    p = sub.add_parser("channels", help="list the channels in a file")
    p.add_argument("file")
    p.set_defaults(func=_cli_channels)

    p = sub.add_parser("shift", help="write a copy with corrected timestamps")
    p.add_argument("file")
    p.add_argument("--delay", type=float, default=None,
                   help="ms; measured automatically when omitted")
    p.add_argument("--resample", action="store_true")
    p.add_argument("-o", "--output", required=True)
    p.set_defaults(func=_cli_shift)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
