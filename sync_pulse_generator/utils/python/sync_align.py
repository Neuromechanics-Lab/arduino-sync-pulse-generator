#!/usr/bin/env python3
"""
sync_align.py - Sync pulse cross-correlation alignment utilities.

Aligns multi-device recordings by cross-correlating the pseudo-random
square-wave sync signal produced by the Arduino Leonardo sync pulse generator.

Usage as module:
    from sync_align import generate_sync_signal, find_sync_lag, align_recordings

Usage as CLI:
    python sync_align.py lag file1.csv file2.mat --sync-col sync --fs 1000
    python sync_align.py align f1.csv f2.mat f3.txt --sync-col sync --mode merge -o aligned.csv
    python sync_align.py generate --seed 42 --duration 60 --fs 1000 -o expected.csv

Dependencies: numpy, scipy, pandas
"""

import argparse
import os
import sys
from dataclasses import dataclass, field
from typing import Optional, Union

import numpy as np
import pandas as pd
from scipy import signal as sp_signal
from scipy import interpolate, io as sio


# ---------------------------------------------------------------------------
# xorshift32 PRNG (matches Arduino implementation exactly)
# ---------------------------------------------------------------------------

class Xorshift32:
    """xorshift32 PRNG matching the Arduino sync pulse generator."""

    def __init__(self, seed: int = 42):
        self.state = np.uint32(seed if seed != 0 else 1)

    def next(self) -> int:
        s = int(self.state)
        s ^= (s << 13) & 0xFFFFFFFF
        s ^= (s >> 17) & 0xFFFFFFFF
        s ^= (s << 5) & 0xFFFFFFFF
        s &= 0xFFFFFFFF
        self.state = np.uint32(s)
        return s


def _random_duration(prng: Xorshift32, min_ms: int, max_ms: int) -> int:
    if min_ms >= max_ms:
        return min_ms
    steps = (max_ms - min_ms) // 5 + 1   # 5 ms increments
    return min_ms + (prng.next() % steps) * 5


# ---------------------------------------------------------------------------
# Recording data container
# ---------------------------------------------------------------------------

@dataclass
class Recording:
    """Standardised container for a loaded recording."""
    data: pd.DataFrame
    sync_signal: np.ndarray
    time_vector: np.ndarray
    fs: float
    source_name: str = ""


# ---------------------------------------------------------------------------
# load_recording
# ---------------------------------------------------------------------------

def load_recording(
    source: Union[str, pd.DataFrame, np.ndarray],
    sync_col: Union[str, int] = 0,
    time_col: Optional[Union[str, int]] = None,
    fs: Optional[float] = None,
    var_name: Optional[str] = None,
    source_name: Optional[str] = None,
) -> Recording:
    """Load a recording from a file path or in-memory object.

    Parameters
    ----------
    source : str, DataFrame, or ndarray
        File path (.csv, .txt, .mat) or in-memory data.
    sync_col : str or int
        Column name or index of the sync channel.
    time_col : str or int, optional
        Column name or index for timestamps.  Takes priority over *fs*.
    fs : float, optional
        Sampling rate in Hz.  Used when *time_col* is not provided.
    var_name : str, optional
        Variable name inside a .mat file.
    source_name : str, optional
        Human-readable label for this recording.
    """
    # --- resolve source to a DataFrame ---
    if isinstance(source, str):
        name = source_name or os.path.basename(source)
        ext = os.path.splitext(source)[1].lower()
        if ext == ".mat":
            mat = sio.loadmat(source, squeeze_me=True)
            if var_name is None:
                # pick first non-dunder variable
                keys = [k for k in mat if not k.startswith("__")]
                if not keys:
                    raise ValueError("No variables found in .mat file")
                var_name = keys[0]
            arr = np.asarray(mat[var_name])
            if arr.ndim == 1:
                df = pd.DataFrame({"sync": arr})
                sync_col = "sync" if isinstance(sync_col, str) else 0
            else:
                df = pd.DataFrame(arr)
        elif ext in (".csv", ".txt", ".tsv"):
            sep = "\t" if ext == ".tsv" else ","
            df = pd.read_csv(source, sep=sep)
        else:
            raise ValueError(f"Unsupported file extension: {ext}")
    elif isinstance(source, pd.DataFrame):
        df = source.copy()
        name = source_name or "DataFrame"
    elif isinstance(source, np.ndarray):
        if source.ndim == 1:
            df = pd.DataFrame({"sync": source})
            sync_col = "sync" if isinstance(sync_col, str) else 0
        else:
            df = pd.DataFrame(source)
        name = source_name or "ndarray"
    else:
        raise TypeError(f"Unsupported source type: {type(source)}")

    # --- extract sync signal ---
    if isinstance(sync_col, str):
        sync = df[sync_col].values.astype(np.float64)
    else:
        sync = df.iloc[:, sync_col].values.astype(np.float64)

    # --- build time vector ---
    if time_col is not None:
        if isinstance(time_col, str):
            t = df[time_col].values.astype(np.float64)
        else:
            t = df.iloc[:, time_col].values.astype(np.float64)
        computed_fs = 1.0 / np.median(np.diff(t))
    elif fs is not None:
        computed_fs = float(fs)
        t = np.arange(len(sync)) / computed_fs
    else:
        raise ValueError("Either time_col or fs must be provided")

    # --- handle NaNs by linear interpolation ---
    nans = np.isnan(sync)
    if nans.any():
        good = ~nans
        sync[nans] = np.interp(np.flatnonzero(nans), np.flatnonzero(good), sync[good])

    return Recording(
        data=df,
        sync_signal=sync,
        time_vector=t,
        fs=computed_fs,
        source_name=name,
    )


# ---------------------------------------------------------------------------
# generate_sync_signal
# ---------------------------------------------------------------------------

def generate_sync_signal(
    seed: int = 42,
    min_high_ms: int = 50,
    max_high_ms: int = 500,
    min_low_ms: int = 50,
    max_low_ms: int = 500,
    duration_sec: float = 60.0,
    sample_rate: float = 1000.0,
) -> np.ndarray:
    """Reproduce the Arduino PRNG square-wave at an arbitrary sample rate.

    The pattern starts LOW, matching the Arduino's ``outputState = LOW`` init.

    Returns
    -------
    signal : 1-D ndarray of 0.0 / 1.0
    """
    prng = Xorshift32(seed)
    total_ms = duration_sec * 1000.0
    total_samples = int(duration_sec * sample_rate)
    sig = np.zeros(total_samples, dtype=np.float64)

    elapsed_ms = 0.0
    is_high = False  # starts LOW

    while elapsed_ms < total_ms:
        if is_high:
            dur = _random_duration(prng, min_high_ms, max_high_ms)
        else:
            dur = _random_duration(prng, min_low_ms, max_low_ms)

        start_sample = int(elapsed_ms / 1000.0 * sample_rate)
        end_sample = int((elapsed_ms + dur) / 1000.0 * sample_rate)
        end_sample = min(end_sample, total_samples)

        if is_high and start_sample < total_samples:
            sig[start_sample:end_sample] = 1.0

        elapsed_ms += dur
        is_high = not is_high

    return sig


# ---------------------------------------------------------------------------
# find_sync_lag
# ---------------------------------------------------------------------------

def find_sync_lag(
    signal_a: np.ndarray,
    signal_b: np.ndarray,
    fs_a: float,
    fs_b: float,
) -> dict:
    """Cross-correlate two sync channels and return the temporal offset.

    If sampling rates differ, the lower-rate signal is resampled up to match.

    Returns
    -------
    dict with keys:
        lag_seconds, lag_samples (at the common fs), peak_correlation, confidence
    """
    # resample to common rate
    common_fs = max(fs_a, fs_b)
    if fs_a < common_fs:
        num = int(len(signal_a) * common_fs / fs_a)
        signal_a = sp_signal.resample(signal_a, num)
    if fs_b < common_fs:
        num = int(len(signal_b) * common_fs / fs_b)
        signal_b = sp_signal.resample(signal_b, num)

    # normalise (zero-mean, unit-variance)
    a = signal_a - np.mean(signal_a)
    b = signal_b - np.mean(signal_b)
    a_std = np.std(a)
    b_std = np.std(b)
    if a_std > 0:
        a /= a_std
    if b_std > 0:
        b /= b_std

    # cross-correlation via FFT
    corr = sp_signal.correlate(a, b, mode="full", method="fft")
    lags = sp_signal.correlation_lags(len(a), len(b), mode="full")

    peak_idx = int(np.argmax(np.abs(corr)))
    peak_lag = int(lags[peak_idx])
    peak_val = float(corr[peak_idx])

    # confidence: ratio of peak to next-highest non-adjacent peak
    abs_corr = np.abs(corr)
    adjacency = max(1, int(common_fs * 0.05))  # 50 ms guard
    mask = np.ones(len(abs_corr), dtype=bool)
    lo = max(0, peak_idx - adjacency)
    hi = min(len(abs_corr), peak_idx + adjacency + 1)
    mask[lo:hi] = False
    if mask.any():
        second_peak = float(np.max(abs_corr[mask]))
        confidence = float(abs_corr[peak_idx] / second_peak) if second_peak > 0 else float("inf")
    else:
        confidence = float("inf")

    return {
        "lag_seconds": peak_lag / common_fs,
        "lag_samples": peak_lag,
        "peak_correlation": peak_val,
        "confidence": confidence,
        "common_fs": common_fs,
    }


# ---------------------------------------------------------------------------
# align_recordings
# ---------------------------------------------------------------------------

def align_recordings(
    recordings: list[Recording],
    mode: str = "offset",
) -> Union[list[Recording], pd.DataFrame]:
    """Align multiple recordings using sync channel cross-correlation.

    Parameters
    ----------
    recordings : list of Recording
        First entry is the reference; all others are aligned to it.
    mode : {"offset", "merge", "bundle"}
        - ``"offset"`` : adds ``aligned_time`` column, no interpolation
        - ``"merge"``  : interpolates all onto a common time base
        - ``"bundle"`` : returns recordings with corrected timestamps

    Returns
    -------
    list[Recording] for offset/bundle, pd.DataFrame for merge.
    """
    if len(recordings) < 2:
        raise ValueError("Need at least 2 recordings to align")

    ref = recordings[0]
    offsets = [0.0]

    for rec in recordings[1:]:
        result = find_sync_lag(ref.sync_signal, rec.sync_signal, ref.fs, rec.fs)
        offsets.append(result["lag_seconds"])

    if mode == "offset":
        for rec, offset in zip(recordings, offsets):
            rec.data = rec.data.copy()
            rec.data["aligned_time"] = rec.time_vector + offset
        return recordings

    elif mode == "bundle":
        aligned = []
        for rec, offset in zip(recordings, offsets):
            new_rec = Recording(
                data=rec.data.copy(),
                sync_signal=rec.sync_signal.copy(),
                time_vector=rec.time_vector + offset,
                fs=rec.fs,
                source_name=rec.source_name,
            )
            new_rec.data["aligned_time"] = new_rec.time_vector
            aligned.append(new_rec)
        return aligned

    elif mode == "merge":
        # find overlapping time window
        starts = [rec.time_vector[0] + off for rec, off in zip(recordings, offsets)]
        ends = [rec.time_vector[-1] + off for rec, off in zip(recordings, offsets)]
        t_start = max(starts)
        t_end = min(ends)
        if t_start >= t_end:
            raise ValueError("No overlapping time range after alignment")

        common_fs = max(r.fs for r in recordings)
        common_t = np.arange(t_start, t_end, 1.0 / common_fs)
        merged = pd.DataFrame({"time": common_t})

        for i, (rec, offset) in enumerate(zip(recordings, offsets)):
            aligned_t = rec.time_vector + offset
            for col in rec.data.columns:
                vals = rec.data[col].values.astype(np.float64)
                nans = np.isnan(vals)
                if nans.all():
                    merged[f"{rec.source_name}_{col}"] = np.nan
                    continue
                if nans.any():
                    good = ~nans
                    vals[nans] = np.interp(
                        np.flatnonzero(nans), np.flatnonzero(good), vals[good]
                    )
                interp_fn = interpolate.interp1d(
                    aligned_t, vals, kind="linear",
                    bounds_error=False, fill_value=np.nan,
                )
                merged[f"{rec.source_name}_{col}"] = interp_fn(common_t)

        return merged

    else:
        raise ValueError(f"Unknown mode: {mode!r}. Use 'offset', 'merge', or 'bundle'.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _cli_lag(args):
    rec_a = load_recording(args.file_a, sync_col=args.sync_col, fs=args.fs,
                           var_name=args.var_name)
    rec_b = load_recording(args.file_b, sync_col=args.sync_col, fs=args.fs,
                           var_name=args.var_name)
    result = find_sync_lag(rec_a.sync_signal, rec_b.sync_signal, rec_a.fs, rec_b.fs)
    print(f"Lag:         {result['lag_seconds']:.6f} s  ({result['lag_samples']} samples @ {result['common_fs']} Hz)")
    print(f"Correlation: {result['peak_correlation']:.4f}")
    print(f"Confidence:  {result['confidence']:.2f}")


def _cli_align(args):
    recs = []
    for f in args.files:
        recs.append(load_recording(f, sync_col=args.sync_col, fs=args.fs,
                                   var_name=args.var_name))
    result = align_recordings(recs, mode=args.mode)

    if args.mode == "merge":
        if args.output:
            result.to_csv(args.output, index=False)
            print(f"Merged output written to {args.output}")
        else:
            print(result.to_csv(index=False))
    else:
        for rec in result:
            if args.output:
                base, ext = os.path.splitext(args.output)
                out = f"{base}_{rec.source_name}{ext}"
                rec.data.to_csv(out, index=False)
                print(f"Written: {out}")
            else:
                print(f"--- {rec.source_name} ---")
                print(rec.data.head(10).to_string())
                print()


def _cli_generate(args):
    sig = generate_sync_signal(
        seed=args.seed,
        min_high_ms=args.min_high,
        max_high_ms=args.max_high,
        min_low_ms=args.min_low,
        max_low_ms=args.max_low,
        duration_sec=args.duration,
        sample_rate=args.fs,
    )
    t = np.arange(len(sig)) / args.fs
    df = pd.DataFrame({"time": t, "sync": sig})
    if args.output:
        df.to_csv(args.output, index=False)
        print(f"Generated {args.duration}s sync signal ({len(sig)} samples) -> {args.output}")
    else:
        print(df.to_csv(index=False))


def main():
    parser = argparse.ArgumentParser(
        description="Sync pulse alignment utilities for Arduino sync pulse generator"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # -- lag --
    p_lag = sub.add_parser("lag", help="Find temporal lag between two recordings")
    p_lag.add_argument("file_a", help="First recording file")
    p_lag.add_argument("file_b", help="Second recording file")
    p_lag.add_argument("--sync-col", default="sync", help="Sync channel column name or index")
    p_lag.add_argument("--fs", type=float, default=1000, help="Sampling rate (Hz)")
    p_lag.add_argument("--var-name", help="Variable name for .mat files")

    # -- align --
    p_align = sub.add_parser("align", help="Align multiple recordings")
    p_align.add_argument("files", nargs="+", help="Recording files (first = reference)")
    p_align.add_argument("--sync-col", default="sync", help="Sync channel column name or index")
    p_align.add_argument("--fs", type=float, default=1000, help="Sampling rate (Hz)")
    p_align.add_argument("--mode", choices=["offset", "merge", "bundle"], default="offset")
    p_align.add_argument("--var-name", help="Variable name for .mat files")
    p_align.add_argument("-o", "--output", help="Output file path")

    # -- generate --
    p_gen = sub.add_parser("generate", help="Generate expected sync signal")
    p_gen.add_argument("--seed", type=int, default=42)
    p_gen.add_argument("--duration", type=float, default=60.0, help="Duration in seconds")
    p_gen.add_argument("--fs", type=float, default=1000.0, help="Sample rate (Hz)")
    p_gen.add_argument("--min-high", type=int, default=50)
    p_gen.add_argument("--max-high", type=int, default=500)
    p_gen.add_argument("--min-low", type=int, default=50)
    p_gen.add_argument("--max-low", type=int, default=500)
    p_gen.add_argument("-o", "--output", help="Output CSV path")

    args = parser.parse_args()

    if args.command == "lag":
        # try to parse sync_col as integer index
        try:
            args.sync_col = int(args.sync_col)
        except ValueError:
            pass
        _cli_lag(args)
    elif args.command == "align":
        try:
            args.sync_col = int(args.sync_col)
        except ValueError:
            pass
        _cli_align(args)
    elif args.command == "generate":
        _cli_generate(args)


if __name__ == "__main__":
    main()
