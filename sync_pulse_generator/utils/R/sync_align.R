# sync_align.R - Sync pulse cross-correlation alignment utilities for R
#
# Aligns multi-device recordings by cross-correlating the pseudo-random
# square-wave sync signal produced by the Arduino Leonardo sync pulse generator.
#
# Usage:
#   source("sync_align.R")
#   sig <- generate_sync_signal(seed = 42, duration_sec = 60, sample_rate = 1000)
#   result <- find_sync_lag(signal_a, signal_b, fs_a = 1000, fs_b = 500)
#
# Dependencies: base R + stats. Optional: R.matlab for .mat file support.


# ===========================================================================
# xorshift32 PRNG (matches Arduino implementation exactly)
# ===========================================================================
# R has no native uint32; we use doubles with manual 32-bit masking.

xorshift32_new <- function(seed = 42) {
  if (seed == 0) seed <- 1
  env <- new.env(parent = emptyenv())
  env$state <- bitwAnd(as.integer(seed), 0xFFFFFFFFL)
  env
}

xorshift32_next <- function(prng) {
  # Work in double to avoid R's signed-integer overflow issues
  s <- as.double(bitwAnd(prng$state, 0xFFFFFFFFL))

  s <- bitwXor(as.integer(s), bitwShiftL(as.integer(s), 13L))
  s <- as.double(bitwAnd(s, 0xFFFFFFFFL))

  s <- bitwXor(as.integer(s), bitwShiftR(as.integer(s), 17L))
  s <- as.double(bitwAnd(s, 0xFFFFFFFFL))

  s <- bitwXor(as.integer(s), bitwShiftL(as.integer(s), 5L))
  s <- as.double(bitwAnd(s, 0xFFFFFFFFL))

  # Handle R's signed integer: convert negative to unsigned equivalent
  if (s < 0) s <- s + 2^32

  prng$state <- as.integer(bitwAnd(as.integer(s), 0xFFFFFFFFL))
  s
}

random_duration <- function(prng, min_ms, max_ms) {
  if (min_ms >= max_ms) return(min_ms)
  rng <- max_ms - min_ms + 1
  rval <- xorshift32_next(prng)
  min_ms + (rval %% rng)
}


# ===========================================================================
# load_recording
# ===========================================================================

load_recording <- function(source, sync_col = 1, time_col = NULL, fs = NULL,
                           var_name = NULL, source_name = NULL) {
  # Load from file or accept in-memory data
  if (is.character(source)) {
    name <- if (!is.null(source_name)) source_name else basename(source)
    ext <- tolower(tools::file_ext(source))

    if (ext == "mat") {
      if (!requireNamespace("R.matlab", quietly = TRUE)) {
        stop("R.matlab package required for .mat files: install.packages('R.matlab')")
      }
      mat <- R.matlab::readMat(source)
      if (is.null(var_name)) {
        var_name <- names(mat)[1]
      }
      arr <- as.matrix(mat[[var_name]])
      df <- as.data.frame(arr)
    } else if (ext %in% c("csv", "txt")) {
      df <- read.csv(source, stringsAsFactors = FALSE)
    } else if (ext == "tsv") {
      df <- read.delim(source, stringsAsFactors = FALSE)
    } else {
      stop(paste("Unsupported file extension:", ext))
    }
  } else if (is.data.frame(source)) {
    df <- source
    name <- if (!is.null(source_name)) source_name else "data.frame"
  } else if (is.matrix(source) || is.numeric(source)) {
    if (is.null(dim(source))) {
      df <- data.frame(sync = source)
      if (is.character(sync_col)) sync_col <- "sync"
    } else {
      df <- as.data.frame(source)
    }
    name <- if (!is.null(source_name)) source_name else "matrix"
  } else {
    stop(paste("Unsupported source type:", class(source)))
  }

  # Extract sync signal
  if (is.character(sync_col)) {
    sync <- as.numeric(df[[sync_col]])
  } else {
    sync <- as.numeric(df[[sync_col]])
  }

  # Build time vector
  if (!is.null(time_col)) {
    if (is.character(time_col)) {
      t_vec <- as.numeric(df[[time_col]])
    } else {
      t_vec <- as.numeric(df[[time_col]])
    }
    computed_fs <- 1.0 / median(diff(t_vec))
  } else if (!is.null(fs)) {
    computed_fs <- fs
    t_vec <- (seq_along(sync) - 1) / computed_fs
  } else {
    stop("Either time_col or fs must be provided")
  }

  # Handle NaN by linear interpolation
  na_idx <- which(is.na(sync))
  if (length(na_idx) > 0) {
    good_idx <- which(!is.na(sync))
    sync[na_idx] <- approx(good_idx, sync[good_idx], xout = na_idx, rule = 2)$y
  }

  list(
    data        = df,
    sync_signal = sync,
    time_vector = t_vec,
    fs          = computed_fs,
    source_name = name
  )
}


# ===========================================================================
# generate_sync_signal
# ===========================================================================

generate_sync_signal <- function(seed = 42, min_high_ms = 50, max_high_ms = 500,
                                  min_low_ms = 50, max_low_ms = 500,
                                  duration_sec = 60, sample_rate = 1000) {
  prng <- xorshift32_new(seed)
  total_ms <- duration_sec * 1000
  total_samples <- floor(duration_sec * sample_rate)
  sig <- rep(0, total_samples)

  elapsed_ms <- 0
  is_high <- FALSE  # starts LOW, matching Arduino

  while (elapsed_ms < total_ms) {
    if (is_high) {
      dur <- random_duration(prng, min_high_ms, max_high_ms)
    } else {
      dur <- random_duration(prng, min_low_ms, max_low_ms)
    }

    start_sample <- floor(elapsed_ms / 1000 * sample_rate) + 1
    end_sample <- min(floor((elapsed_ms + dur) / 1000 * sample_rate), total_samples)

    if (is_high && start_sample <= total_samples) {
      sig[start_sample:end_sample] <- 1
    }

    elapsed_ms <- elapsed_ms + dur
    is_high <- !is_high
  }

  t <- (seq_len(total_samples) - 1) / sample_rate
  list(signal = sig, time = t)
}


# ===========================================================================
# find_sync_lag
# ===========================================================================

find_sync_lag <- function(signal_a, signal_b, fs_a, fs_b) {
  common_fs <- max(fs_a, fs_b)

  # Resample lower-rate signal using linear interpolation
  if (fs_a < common_fs) {
    t_old <- (seq_along(signal_a) - 1) / fs_a
    n_new <- round(length(signal_a) * common_fs / fs_a)
    t_new <- (seq_len(n_new) - 1) / common_fs
    signal_a <- approx(t_old, signal_a, xout = t_new, rule = 2)$y
  }
  if (fs_b < common_fs) {
    t_old <- (seq_along(signal_b) - 1) / fs_b
    n_new <- round(length(signal_b) * common_fs / fs_b)
    t_new <- (seq_len(n_new) - 1) / common_fs
    signal_b <- approx(t_old, signal_b, xout = t_new, rule = 2)$y
  }

  # Normalise (zero-mean, unit-variance)
  a <- signal_a - mean(signal_a)
  b <- signal_b - mean(signal_b)
  sa <- sd(a); if (sa > 0) a <- a / sa
  sb <- sd(b); if (sb > 0) b <- b / sb

  # Cross-correlation via ccf (stats package)
  max_lag <- length(a) + length(b) - 1
  # Use convolve for full cross-correlation (more efficient than ccf for large signals)
  # convolve(a, rev(b)) gives cross-correlation
  corr <- convolve(a, rev(b), type = "open")
  n_corr <- length(corr)
  lags <- seq(-(length(b) - 1), length(a) - 1)

  abs_corr <- abs(corr)
  peak_idx <- which.max(abs_corr)
  peak_lag <- lags[peak_idx]
  peak_val <- corr[peak_idx]

  # Confidence: ratio of peak to next-highest non-adjacent peak
  adjacency <- max(1, round(common_fs * 0.05))  # 50 ms guard
  lo <- max(1, peak_idx - adjacency)
  hi <- min(n_corr, peak_idx + adjacency)
  mask <- rep(TRUE, n_corr)
  mask[lo:hi] <- FALSE

  if (any(mask)) {
    second_peak <- max(abs_corr[mask])
    if (second_peak > 0) {
      confidence <- abs_corr[peak_idx] / second_peak
    } else {
      confidence <- Inf
    }
  } else {
    confidence <- Inf
  }

  list(
    lag_seconds      = peak_lag / common_fs,
    lag_samples      = peak_lag,
    peak_correlation = peak_val,
    confidence       = confidence,
    common_fs        = common_fs
  )
}


# ===========================================================================
# align_recordings
# ===========================================================================

align_recordings <- function(recordings, mode = "offset") {
  n <- length(recordings)
  if (n < 2) stop("Need at least 2 recordings to align")

  ref <- recordings[[1]]
  offsets <- numeric(n)

  for (i in 2:n) {
    res <- find_sync_lag(ref$sync_signal, recordings[[i]]$sync_signal,
                         ref$fs, recordings[[i]]$fs)
    offsets[i] <- res$lag_seconds
  }

  if (mode == "offset") {
    for (i in seq_len(n)) {
      recordings[[i]]$data$aligned_time <- recordings[[i]]$time_vector + offsets[i]
    }
    return(recordings)

  } else if (mode == "bundle") {
    for (i in seq_len(n)) {
      recordings[[i]]$time_vector <- recordings[[i]]$time_vector + offsets[i]
      recordings[[i]]$data$aligned_time <- recordings[[i]]$time_vector
    }
    return(recordings)

  } else if (mode == "merge") {
    # Find overlapping window
    starts <- sapply(seq_len(n), function(i) recordings[[i]]$time_vector[1] + offsets[i])
    ends   <- sapply(seq_len(n), function(i) tail(recordings[[i]]$time_vector, 1) + offsets[i])
    t_start <- max(starts)
    t_end   <- min(ends)
    if (t_start >= t_end) stop("No overlapping time range after alignment")

    common_fs <- max(sapply(recordings, function(r) r$fs))
    common_t  <- seq(t_start, t_end, by = 1.0 / common_fs)
    merged    <- data.frame(time = common_t)

    for (i in seq_len(n)) {
      rec <- recordings[[i]]
      aligned_t <- rec$time_vector + offsets[i]
      prefix <- if (!is.null(rec$source_name)) rec$source_name else paste0("rec", i)

      for (col_name in names(rec$data)) {
        vals <- as.numeric(rec$data[[col_name]])

        # Interpolate NaNs
        na_idx <- which(is.na(vals))
        if (length(na_idx) > 0 && length(na_idx) < length(vals)) {
          good_idx <- which(!is.na(vals))
          vals[na_idx] <- approx(good_idx, vals[good_idx], xout = na_idx, rule = 2)$y
        }

        interped <- approx(aligned_t, vals, xout = common_t, rule = 2)$y
        merged[[paste0(prefix, "_", col_name)]] <- interped
      }
    }
    return(merged)

  } else {
    stop(paste("Unknown mode:", mode, ". Use 'offset', 'merge', or 'bundle'."))
  }
}
