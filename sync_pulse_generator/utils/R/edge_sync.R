# edge_sync.R — edge-based delay measurement and EMG processing.
#
# Measures the delay between two or more recordings of the same square wave by
# locating the individual signal edges, rather than by cross-correlating the
# waveforms (which sync_align.R does). Edge timing is the better tool when one
# copy of the signal has been through an EMG amplifier, because the
# amplifier's high-pass turns each step into a transient spike: the waveforms
# no longer resemble each other, but their transition times still line up.
#
# Companion to sync_align.R. Use that one for whole-waveform correlation, this
# one when you have clean edges and want a per-transition answer with error
# bars. Mirrors utils/python/edge_sync.py and utils/matlab/*.m.
#
# Dependencies: base R + stats. signal package used for EMG filtering if
# present; process_emg() reports what it could not do rather than failing.

# ---------------------------------------------------------------------------
# Robust noise estimate
# ---------------------------------------------------------------------------

mad_noise <- function(x) 1.4826 * stats::median(abs(x - stats::median(x)))

# Onset location: the level, as a fraction of each spike's own height, at
# which the rising flank is timed. Measured against synthetic signals of
# known delay (1000 Hz, amplifier time constants 1-20 ms):
#
#   estimator      bias        varies with amplifier?
#   onset @ 0.25   +0.45 ms    no
#   onset @ 0.80   +1.00 ms    no
#   peak           +1.3..1.7   YES
#
# 0.25 gives the smallest bias and, more importantly, one that does not
# depend on the amplifier's response — so it cancels out of any comparison
# between two channels recorded through the same hardware. The cost is
# noise; raise it to trade bias back for precision, and report which you
# used.
ONSET_FRACTION <- 0.25

# find_channel(labels, pattern)
#   Indices of channels whose label contains `pattern`, case-insensitive.
#
#   Matches the label WITHOUT its device prefix first, falling back to the
#   full label only if that finds nothing. The prefix would otherwise swallow
#   short muscle abbreviations: Vicon writes channels as "Voltage.5-TA", and a
#   naive substring search for "TA" hits the "ta" in every "Voltage.",
#   returning the entire device.
find_channel <- function(labels, pattern, unique_only = FALSE) {
  bare <- sub("^.*\\.", "", labels)
  hits <- grep(pattern, bare, ignore.case = TRUE)
  if (length(hits) == 0)
    hits <- grep(pattern, labels, ignore.case = TRUE)
  if (unique_only) {
    if (length(hits) == 0)
      stop("No channel matching '", pattern, "'. Available: ",
           paste(labels, collapse = ", "))
    if (length(hits) > 1)
      stop("Pattern '", pattern, "' matched ", length(hits), " channels: ",
           paste(labels[hits], collapse = ", "))
  }
  hits
}

# ---------------------------------------------------------------------------
# detect_edges — square-wave transition times, to sub-sample precision
# ---------------------------------------------------------------------------
#
# Two acquisition paths need two detectors:
#
# mode = "level"
#   The square wave recorded directly. The signal holds its level between
#   transitions, so a Schmitt trigger with hysteresis finds the state changes,
#   and the crossing time is refined by linear interpolation across the
#   mid-level threshold.
#
# mode = "rectified"
#   The square wave after an EMG amplifier. The amplifier's high-pass removes
#   the DC level, so each step becomes a transient spike: a rising edge gives
#   a positive spike, a falling edge a negative one. The detector therefore
#   searches the SIGNED signal for positive and negative peaks separately, so
#   each detection carries a known polarity.
#
#   Working on the signed signal rather than a rectified copy is the whole
#   point: rectifying discards the sign, and without the sign a rising edge
#   can be paired with a falling one. See edge_delay().
#
# locate = "onset" | "peak"  (rectified mode)
#   Which feature of the spike marks the transition. Both estimators are
#   biased late; what separates them is whether the bias is CONSTANT.
#
#   The PEAK lags the true transition by the amplifier's rise time, so its
#   bias grows with the amplifier's time constant (+1.3 to +1.7 ms across
#   1-20 ms in testing). The ONSET is timed on the rising flank at a fixed
#   fraction of the spike's height, so its bias is the same whatever the
#   amplifier (+0.45 ms at the default fraction).
#
#   A constant bias cancels out of a comparison between two channels
#   recorded through the same hardware; a varying one does not. Onset is
#   therefore the default. Use "peak" to reproduce an older analysis, or
#   when the flank is too noisy for a stable onset — see ONSET_FRACTION.
#
# returns : list(time, polarity, amplitude, mode, fs, noise,
#                n_rising, n_falling)
detect_edges <- function(signal, fs, mode = "auto",
                         hysteresis = c(0.3, 0.7), threshold = 8,
                         refractory = 30, min_pulse = 5,
                         locate = "onset", onset_fraction = ONSET_FRACTION,
                         onset_floor = 2) {
  x <- as.numeric(signal)
  if (length(x) < 3) stop("Signal needs at least 3 samples.")
  if (fs <= 0) stop("fs must be positive.")

  noise <- mad_noise(x)

  if (mode == "auto") {
    rng <- max(x) - min(x)
    if (rng <= 0) {
      mode <- "level"
    } else {
      lo <- min(x)
      mid_frac <- mean(x > lo + 0.35 * rng & x < lo + 0.65 * rng)
      mode <- if (mid_frac < 0.10) "level" else "rectified"
    }
  }

  if (mode == "level") {
    e <- .level_edges(x, fs, hysteresis, min_pulse)
  } else if (mode == "rectified") {
    e <- .rectified_edges(x, fs, noise, threshold, refractory,
                          locate, onset_fraction, onset_floor)
  } else {
    stop("mode must be 'level', 'rectified', or 'auto'.")
  }

  list(time = e$time, polarity = e$polarity, amplitude = e$amplitude,
       mode = mode, fs = fs, noise = noise,
       n_rising = sum(e$polarity > 0), n_falling = sum(e$polarity < 0))
}

.level_edges <- function(x, fs, hysteresis, min_pulse) {
  lo <- min(x); hi <- max(x); rng <- hi - lo
  if (rng <= 0)
    return(list(time = numeric(0), polarity = numeric(0),
                amplitude = numeric(0)))

  fr <- sort(hysteresis)
  thr_lo <- lo + fr[1] * rng
  thr_hi <- lo + fr[2] * rng
  mid <- (hi + lo) / 2
  min_gap <- max(1, round(min_pulse * fs / 1000))

  times <- numeric(0); pols <- numeric(0)
  state <- x[1] > thr_hi
  last_idx <- -Inf

  for (i in 2:length(x)) {
    up <- (!state) && x[i] > thr_hi
    down <- state && x[i] < thr_lo
    if (!(up || down)) next
    state <- up

    j <- i
    while (j > 1 && ((up && x[j] > mid) || (!up && x[j] < mid))) j <- j - 1

    if (j < length(x)) {
      y0 <- x[j]; y1 <- x[j + 1]
      frac <- if (y1 != y0) (mid - y0) / (y1 - y0) else 0
      frac <- min(max(frac, 0), 1)
      t_cross <- (j - 1 + frac) / fs
    } else {
      t_cross <- (j - 1) / fs
    }

    if ((j - last_idx) < min_gap) next
    last_idx <- j

    times <- c(times, t_cross)
    pols <- c(pols, if (up) 1 else -1)
  }

  list(time = times, polarity = pols, amplitude = rep(rng, length(times)))
}

.rectified_edges <- function(x, fs, noise, threshold, refractory,
                             locate, onset_fraction, onset_floor) {
  if (noise <= 0)
    return(list(time = numeric(0), polarity = numeric(0),
                amplitude = numeric(0)))

  xc <- x - stats::median(x)
  thr <- threshold * noise
  floor_level <- onset_floor * noise

  pos <- .signed_peaks(xc, 1, thr, fs, refractory, locate,
                       onset_fraction, floor_level)
  neg <- .signed_peaks(xc, -1, thr, fs, refractory, locate,
                       onset_fraction, floor_level)

  t <- c(pos$time, neg$time)
  p <- c(rep(1, length(pos$time)), rep(-1, length(neg$time)))
  a <- c(pos$amp, neg$amp)
  o <- order(t)
  list(time = t[o], polarity = p[o], amplitude = a[o])
}

# Peaks of one polarity, held apart by a refractory period. When two
# candidates fall inside the window the LARGER wins, so ringing after a real
# transition cannot displace the transition itself.
.signed_peaks <- function(x, sgn, thr, fs, refractory_ms, locate,
                          onset_fraction, onset_floor) {
  s <- x * sgn
  n <- length(s)
  above <- s > thr
  if (!any(above)) return(list(time = numeric(0), amp = numeric(0)))

  d <- diff(c(FALSE, above, FALSE))
  starts <- which(d == 1)
  stops  <- which(d == -1) - 1

  cand_idx <- integer(0); cand_val <- numeric(0)
  for (k in seq_along(starts)) {
    a <- starts[k]; b <- stops[k]
    kk <- a + which.max(s[a:b]) - 1
    cand_idx <- c(cand_idx, kk); cand_val <- c(cand_val, s[kk])
  }

  refrac <- max(1, round(refractory_ms * fs / 1000))
  kept <- integer(0)
  for (q in order(-cand_val)) {
    ci <- cand_idx[q]
    if (all(abs(ci - kept) >= refrac)) kept <- c(kept, ci)
  }
  kept <- sort(kept)

  times <- numeric(length(kept)); amps <- numeric(length(kept))
  for (m in seq_along(kept)) {
    k <- kept[m]
    amps[m] <- s[k]

    if (locate == "onset") {
      # Walk back from the peak to where the rising flank crosses a level set
      # as a FRACTION OF THIS SPIKE'S OWN AMPLITUDE, then interpolate.
      #
      # An absolute threshold a few MADs up sits at the foot of the flank,
      # where the signal is nearly flat: which sample first exceeds it then
      # depends on noise, and the interpolated time snaps to one sample or
      # the next. On real data that split one population into two modes about
      # a sample apart. A fractional level sits on the steep part, where an
      # amplitude error barely moves the crossing time, and it scales with
      # spike size. The level lands a constant delay after the true
      # transition, but the same delay for every edge, so it cancels out of a
      # delay measurement.
      level <- max(onset_floor, onset_fraction * s[k])
      j <- k
      while (j > 1 && s[j] > level) j <- j - 1
      if (j < k) {
        y0 <- s[j]; y1 <- s[j + 1]
        frac <- if (y1 != y0) (level - y0) / (y1 - y0) else 0
        frac <- min(max(frac, 0), 1)
        times[m] <- (j - 1 + frac) / fs
      } else {
        times[m] <- (j - 1) / fs
      }
      next
    }

    if (k > 1 && k < n) {
      y0 <- s[k - 1]; y1 <- s[k]; y2 <- s[k + 1]
      den <- y0 - 2 * y1 + y2
      delta <- if (den != 0) 0.5 * (y0 - y2) / den else 0
      delta <- min(max(delta, -1), 1)
    } else {
      delta <- 0
    }
    times[m] <- (k - 1 + delta) / fs
  }

  list(time = times, amp = amps)
}

# ---------------------------------------------------------------------------
# edge_delay — delay between two edge trains
# ---------------------------------------------------------------------------
#
# A positive delay means the test signal arrives AFTER the reference.
#
# Matching rules, and why each one is there:
#
# 1. Polarity is respected. A rising edge is only ever matched to a rising
#    edge. Mixing polarities inflates the spread, because a rising and a
#    falling transition are different events separated by a pulse width.
#
# 2. Matching is causal. A candidate must fall within [min_delay, max_delay]
#    of the reference edge. The test signal cannot physically precede the
#    reference, so a negative-delay pairing is a detection artefact and is
#    excluded rather than averaged in.
#
# 3. Ties go to the largest peak. When several candidates sit inside the
#    window, the strongest wins. Spurious peaks are small; the real
#    transition is not.
#
# returns : list of statistics — see names() of the result
edge_delay <- function(edges_ref, edges_test, min_delay = -2,
                       max_delay = 100, outlier_mad = 5) {
  if (min_delay >= max_delay) stop("min_delay must be below max_delay.")
  if (length(edges_ref$time) == 0 || length(edges_test$time) == 0)
    stop(sprintf("Both inputs need edges (reference %d, test %d).",
                 length(edges_ref$time), length(edges_test$time)))

  amp <- if (length(edges_test$amplitude)) abs(edges_test$amplitude)
         else rep(1, length(edges_test$time))

  m_rise <- .match_pol(edges_ref, edges_test, amp, 1, min_delay, max_delay)
  m_fall <- .match_pol(edges_ref, edges_test, amp, -1, min_delay, max_delay)

  times <- c(m_rise$times, m_fall$times)
  deltas <- c(m_rise$deltas, m_fall$deltas)
  pols <- c(rep(1, length(m_rise$times)), rep(-1, length(m_fall$times)))

  if (length(deltas) == 0)
    stop(sprintf(paste0("No edges paired inside [%g, %g] ms. Check that both ",
                        "channels carry the same square wave, and widen ",
                        "max_delay if the true delay could exceed it."),
                 min_delay, max_delay))

  o <- order(times)
  times <- times[o]; deltas <- deltas[o]; pols <- pols[o]

  if (length(deltas) >= 3 && diff(range(times)) > 0) {
    fit <- stats::lm(deltas ~ times)
    slope <- unname(stats::coef(fit)[2])
    intercept <- unname(stats::coef(fit)[1])
    drift_total <- slope * diff(range(times))
  } else {
    slope <- 0; intercept <- stats::median(deltas); drift_total <- 0
  }

  med <- stats::median(deltas)
  mad_v <- 1.4826 * stats::median(abs(deltas - med))
  bad <- if (outlier_mad > 0 && mad_v > 0)
    abs(deltas - med) > outlier_mad * mad_v else rep(FALSE, length(deltas))

  qs <- stats::quantile(deltas, c(0.25, 0.75), names = FALSE)
  sd_v <- if (length(deltas) > 1) stats::sd(deltas) else 0

  res <- list(
    delay_ms = med,
    delay_mean_ms = mean(deltas),
    delay_std_ms = sd_v,
    delay_iqr_ms = qs[2] - qs[1],
    ci95_ms = if (length(deltas) > 1) 1.96 * sd_v / sqrt(length(deltas)) else 0,
    n_matched = length(deltas),
    n_reference = length(edges_ref$time),
    match_rate = length(deltas) / length(edges_ref$time),
    rising = .pol_stats(m_rise$deltas),
    falling = .pol_stats(m_fall$deltas),
    drift_ms_per_s = slope,
    drift_total_ms = drift_total,
    intercept_ms = intercept,
    times = times, deltas_ms = deltas, polarities = pols,
    n_outliers = sum(bad), outlier_idx = which(bad))

  res$warnings <- .delay_warnings(res, edges_ref, edges_test)
  res
}

.match_pol <- function(e_ref, e_test, amp, pol, min_delay, max_delay) {
  ref_t <- e_ref$time[e_ref$polarity == pol]
  sel <- e_test$polarity == pol
  tst_t <- e_test$time[sel]
  tst_a <- amp[sel]

  if (length(tst_t) == 0 || length(ref_t) == 0)
    return(list(times = numeric(0), deltas = numeric(0)))

  times <- numeric(0); deltas <- numeric(0)
  for (t0 in ref_t) {
    d_ms <- (tst_t - t0) * 1000
    inwin <- d_ms >= min_delay & d_ms <= max_delay
    if (!any(inwin)) next
    idx <- which(inwin)
    best <- idx[which.max(tst_a[idx])]
    times <- c(times, t0); deltas <- c(deltas, d_ms[best])
  }
  list(times = times, deltas = deltas)
}

.pol_stats <- function(d) {
  if (length(d) == 0)
    return(list(median_ms = NA_real_, mean_ms = NA_real_,
                std_ms = NA_real_, n = 0))
  list(median_ms = stats::median(d), mean_ms = mean(d),
       std_ms = if (length(d) > 1) stats::sd(d) else 0, n = length(d))
}

.delay_warnings <- function(r, e_ref, e_test) {
  w <- character(0)
  if (r$match_rate < 0.9)
    w <- c(w, sprintf(paste0("Only %.0f%% of reference edges matched (%d of ",
                             "%d). Check the detector settings on the test ",
                             "channel."),
                      100 * r$match_rate, r$n_matched, r$n_reference))
  if (r$n_outliers > 0)
    w <- c(w, sprintf(paste0("%d matched edges are more than 5 MADs from the ",
                             "median. Inspect them before trusting the mean."),
                      r$n_outliers))
  if (r$delay_std_ms > 2)
    w <- c(w, sprintf(paste0("Delay spread is %.2f ms (sd). A fixed hardware ",
                             "latency should be well under 1 ms; this suggests ",
                             "detection problems or a variable link."),
                      r$delay_std_ms))
  rm_ <- r$rising$median_ms; fm <- r$falling$median_ms
  if (is.finite(rm_) && is.finite(fm) && abs(rm_ - fm) > 1)
    w <- c(w, sprintf(paste0("Rising and falling edges disagree by %.2f ms ",
                             "(%.3f vs %.3f). Asymmetry this large usually ",
                             "means the detector is mis-locating one polarity."),
                      abs(rm_ - fm), rm_, fm))
  if (abs(r$drift_total_ms) > 1)
    w <- c(w, sprintf(paste0("Delay drifts %.2f ms across the trial. The two ",
                             "devices may run on independent clocks; a single ",
                             "offset will not align them properly."),
                      r$drift_total_ms))

  # Only compare edge counts when BOTH channels used the same detector.
  # A level detector reports one edge per transition; a rectified detector
  # reports a positive AND a negative peak at each one, so a correct
  # rectified detection legitimately carries about twice the reference count
  # and comparing across modes would call it spurious.
  n_ref <- length(e_ref$time); n_tst <- length(e_test$time)
  if (identical(e_ref$mode, e_test$mode) && n_ref > 0 && n_tst > 1.5 * n_ref)
    w <- c(w, sprintf(paste0("Test channel yielded %d edges against %d in the ",
                             "reference, using the same detector. Raise ",
                             "'threshold' or 'refractory' if spurious peaks ",
                             "are being detected."), n_tst, n_ref))
  w
}

# ---------------------------------------------------------------------------
# shift_timestamps — apply a measured delay
# ---------------------------------------------------------------------------
#
# Sign convention matches edge_delay: a positive delay means this recording
# arrived LATE, so its timestamps move EARLIER (the sample labelled t really
# happened at t - delay). Set invert = TRUE to reverse that.
#
# resample = FALSE (default) rewrites the time vector and leaves the samples
# untouched — nothing is interpolated, so no data is altered. resample = TRUE
# keeps the original time base and moves the DATA onto it by interpolation,
# which is lossy and therefore not the default.
shift_timestamps <- function(time, data, delay_ms, channels = NULL,
                             resample = FALSE, invert = FALSE) {
  d_ms <- if (is.list(delay_ms)) delay_ms$delay_ms else as.numeric(delay_ms)
  if (!is.finite(d_ms)) stop("delay_ms must be finite.")
  if (invert) d_ms <- -d_ms
  d_s <- d_ms / 1000

  data <- as.matrix(data)
  ch <- if (is.null(channels)) seq_len(ncol(data)) else channels

  if (!resample)
    return(list(time = time - d_s, data = data, shift_applied_ms = d_ms,
                shift_channels = ch, resampled = FALSE))

  src <- time - d_s
  out <- data
  for (c in ch) {
    v <- data[, c]
    good <- is.finite(v)
    if (!any(good)) next
    out[, c] <- stats::approx(src[good], v[good], xout = time,
                              rule = 1)$y
  }
  list(time = time, data = out, shift_applied_ms = d_ms,
       shift_channels = ch, resampled = TRUE)
}

# ---------------------------------------------------------------------------
# process_emg — standard surface-EMG chain
# ---------------------------------------------------------------------------
#
#   raw -> detrend -> bandpass -> (notch) -> rectify -> envelope
#
# The bandpass is applied forwards and backwards (zero phase), so it adds no
# lag — which matters here, since a lag would corrupt the very timing this
# file measures.
#
# The result also carries a quality block and plain-language warnings, which
# flag flat channels (nothing plugged in) and railed ones (a disconnected
# sensor floats to the supply limits and can look like a large signal).
process_emg <- function(signal, fs, band = c(20, 450), order = 4,
                        notch = NULL, envelope = 4, rms_window = 100,
                        mvc = NULL) {
  x <- as.numeric(signal)
  if (length(x) < 10) stop("Signal needs at least 10 samples.")
  nyq <- fs / 2

  out <- list(raw = x, fs = fs, time = (seq_along(x) - 1) / fs)
  out$quality <- .emg_quality(x, fs, notch)

  y <- x - mean(x)
  out$detrended <- y

  have_signal <- requireNamespace("signal", quietly = TRUE)

  if (!is.null(band) && length(band) == 2) {
    if (!have_signal) {
      warning("Package 'signal' is not installed; skipping the bandpass. ",
              "Install it for full EMG processing.")
    } else {
      lo <- band[1]; hi <- min(band[2], 0.99 * nyq)
      if (lo >= hi) stop(sprintf("Bandpass [%g %g] is invalid at fs=%g Hz.",
                                 band[1], band[2], fs))
      bf <- signal::butter(order, c(lo, hi) / nyq, type = "pass")
      y <- signal::filtfilt(bf, y)
    }
  }
  out$filtered <- y

  if (!is.null(notch) && notch > 0 && notch < nyq && have_signal) {
    bw <- notch / 30
    bf <- signal::butter(2, c(notch - bw, notch + bw) / nyq, type = "stop")
    y <- signal::filtfilt(bf, y)
    out$notched <- y
    out$filtered <- y
  }

  r <- abs(y)
  out$rectified <- r

  if (!is.null(envelope) && envelope > 0 && envelope < nyq && have_signal) {
    bf <- signal::butter(2, envelope / nyq, type = "low")
    out$envelope <- pmax(signal::filtfilt(bf, r), 0)
  } else {
    out$envelope <- r
  }

  w <- max(1, round(rms_window * fs / 1000))
  out$rms <- sqrt(.movmean(y^2, w))

  if (!is.null(mvc) && mvc > 0) out$mvc_percent <- 100 * out$envelope / mvc

  out$warnings <- .emg_warnings(out$quality)
  out
}

.movmean <- function(x, w) {
  if (w <= 1) return(x)
  n <- length(x)
  cs <- c(0, cumsum(x))
  half <- w %/% 2
  lo <- pmax(seq_len(n) - half, 1)
  hi <- pmin(seq_len(n) + half, n)
  (cs[hi + 1] - cs[lo]) / (hi - lo + 1)
}

.emg_quality <- function(x, fs, notch_hz) {
  n <- length(x)
  lo <- min(x); hi <- max(x); rng <- hi - lo
  q <- list(range = rng, std = stats::sd(x))
  q$flat <- rng < .Machine$double.eps || q$std < .Machine$double.eps

  q$frac_at_rail <- if (rng > 0) {
    tol <- 0.01 * rng
    mean(x >= hi - tol | x <= lo + tol)
  } else 1
  q$saturated <- q$frac_at_rail > 0.20

  e <- .movmean(abs(x - stats::median(x)), max(1, round(0.05 * fs)))
  es <- sort(e)
  baseline <- stats::median(es[1:max(1, n %/% 10)])
  peak <- stats::median(es[max(1, floor(0.9 * n)):n])
  q$snr_estimate <- if (baseline > 0) peak / baseline else Inf

  q$mains_ratio <- NA_real_
  f0 <- if (is.null(notch_hz) || notch_hz <= 0) 60 else notch_hz
  nyq <- fs / 2
  if (f0 < nyq && n >= 4) {
    nfft <- 2^ceiling(log2(min(n, round(4 * fs))))
    seg <- x[1:min(n, nfft)]
    seg <- seg - mean(seg)
    P <- Mod(stats::fft(c(seg, rep(0, nfft - length(seg)))))^2
    fax <- (0:(nfft - 1)) * fs / nfft
    bp <- function(a, b) { m <- fax >= a & fax < b
                           if (any(m)) mean(P[m]) else 0 }
    at <- bp(f0 - 1, f0 + 1)
    near <- bp(f0 - 10, f0 - 2) + bp(f0 + 2, f0 + 10)
    if (near > 0) q$mains_ratio <- at / (near / 2)
  }
  q
}

.emg_warnings <- function(q) {
  w <- character(0)
  if (q$flat)
    w <- c(w, "Channel is flat — nothing is connected, or the sensor is off.")
  if (q$saturated)
    w <- c(w, sprintf(paste0("Channel is railed: %.0f%% of samples sit at the ",
                             "extremes. A disconnected sensor floats to the ",
                             "supply limits and looks like a large signal. ",
                             "Verify the electrode."), 100 * q$frac_at_rail))
  if (!q$flat && !q$saturated && q$snr_estimate < 2)
    w <- c(w, sprintf(paste0("Low signal-to-noise (%.1fx over baseline). The ",
                             "channel may be picking up noise, not muscle ",
                             "activity."), q$snr_estimate))
  if (is.finite(q$mains_ratio) && q$mains_ratio > 10)
    w <- c(w, sprintf(paste0("Strong mains component (%.0fx its neighbours). ",
                             "Check the ground electrode, or set 'notch'."),
                      q$mains_ratio))
  w
}
