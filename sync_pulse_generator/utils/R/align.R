# align.R — align any number of recordings onto one timeline.
#
# Several devices record the same experiment, each with its own clock, its own
# start time, its own sample rate, and its own way of reporting the sync
# signal — one gives a continuous analog waveform, another only the timestamps
# of rising edges, a third only falling edges. Some drop frames. None agree on
# when zero was.
#
# The approach is NOT to align recordings to each other. The generator's
# output is fully determined by (seed, config), so the intended waveform can be
# regenerated from code. Every recording is locked INDEPENDENTLY to that
# template, which makes alignment transitive: any two recordings are related
# through the template, with no reference device, no pairwise matrix, and no
# accumulated error. Recordings that never overlap in wall-clock time still
# land on one timeline.
#
# Edge-only inputs work natively because the template is itself just a list of
# transition times, and so is a rising-edge-only recording. A continuous signal
# passes through detect_edges() first to become one.
#
# Mirrors utils/python/align.py and utils/matlab/align_sources.m.
#
# Dependencies: base R + stats. signal package only for anti-aliased
# decimation; align_resample() warns rather than aliasing quietly without it.

source_file <- function(f) {
  p <- file.path(dirname(sys.frame(1)$ofile %||% "."), f)
  if (file.exists(p)) source(p)
}
`%||%` <- function(a, b) if (is.null(a)) b else a

# ---- firmware defaults (config.h) -----------------------------------------
SEED           <- 42
MIN_HIGH_MS    <- 50
MAX_HIGH_MS    <- 500
MIN_LOW_MS     <- 50
MAX_LOW_MS     <- 500
TC_ENABLED     <- TRUE
TC_INTERVAL_S  <- 10
TC_LEADIN_MS   <- 20
TC_PULSE_MS_G  <- 5
TC_PRE_GAP_G   <- 10
TC_ZERO_G      <- 15
TC_ONE_G       <- 25
STEP_MS        <- 1    # config.h DURATION_STEP_MS (protocol 3; was 5)

# Intervals shorter than this belong to a timecode frame, not the
# pseudo-random train, and are excluded from fingerprint matching.
#
# This threshold is load-bearing. Frame internals are 5/15/25 ms pulses drawn
# from a tiny alphabet and are ~77% of all transitions in an hour. Including
# them makes roughly 75% of fingerprint windows match somewhere else;
# excluding them, a window of only 4 intervals is unique across a full hour.
# The pseudo-random minimum is 50 ms, so 45 ms separates the two populations.
PR_MIN_INTERVAL_S <- 0.045

# Fingerprint window length, in pseudo-random intervals. Longer is NOT better:
# a longer window is more likely to span a dropped edge, and one bad interval
# kills it.
FINGERPRINT_K <- 4
INTERVAL_TOL_S <- 0.006
MIN_VOTES <- 3

ANCHOR_WINDOW_EDGES <- 60
ANCHOR_STRIDE_EDGES <- 30
ANCHOR_MIN_CONF <- 0.85
STEP_THRESHOLD_S <- 0.010

# ---------------------------------------------------------------------------
# Template
# ---------------------------------------------------------------------------

# generate_sync_signal_tc(duration_s, run_id)
#   Recreate the firmware's hybrid output as EDGE TIMES, including the
#   timecode frames. generate_sync_signal() in sync_align.R predates timecode
#   and emits only the pseudo-random train at a fixed sample rate, so it
#   cannot serve as a template.
#
#   Mirrors sync_pulse_generator.ino: output starts LOW with the first toggle
#   (to HIGH) at t=0; every pseudo-random segment draws from the PRNG and is
#   then clamped to end at (tick - lead-in) if it would cross it; the output
#   holds LOW through the lead-in so the frame's first pulse rises ON the tick.
#
#   returns : data.frame(t_ms, level)
generate_sync_signal_tc <- function(duration_s, run_id = 1, seed = SEED,
                                    tc_enabled = TC_ENABLED,
                                    tc_interval_s = TC_INTERVAL_S,
                                    tc_leadin_ms = TC_LEADIN_MS) {
  total_ms <- duration_s * 1000
  cap <- ceiling(duration_s * 60) + 4096
  tms <- numeric(cap); lvl <- numeric(cap); n <- 0

  # xorshift32 on DOUBLES. R's integers are signed 32-bit, so 0xFFFFFFFF
  # overflows and bitwAnd/bitwShiftL cannot carry the unsigned state the
  # firmware uses. Doubles hold 2^53 exactly, which is ample for 32 bits.
  M32 <- 4294967296            # 2^32
  state <- seed %% M32
  if (state == 0) state <- 1

  xor32 <- function(a, b) {
    # bitwXor on the two 16-bit halves, so neither exceeds integer range.
    hi <- bitwXor(a %/% 65536, b %/% 65536)
    lo <- bitwXor(a %% 65536, b %% 65536)
    hi * 65536 + lo
  }
  xorshift <- function(s) {
    s <- xor32(s, (s * 8192) %% M32)          # s << 13
    s <- xor32(s, floor(s / 131072))          # s >> 17
    s <- xor32(s, (s * 32) %% M32)            # s << 5
    s %% M32
  }
  bits_of <- function(v, nb) {
    b <- integer(nb)
    for (i in nb:1) { b[i] <- v %% 2; v <- v %/% 2 }
    b
  }
  cks4 <- function(v) { c <- 0; for (i in 1:8) { c <- bitwXor(c, v %% 16); v <- v %/% 16 }; c }

  now <- 0; level <- 0
  next_tick <- tc_interval_s * 1000

  # The firmware's first toggle (LOW -> HIGH) happens at t=0, before any draw.
  level <- 1; n <- n + 1; tms[n] <- 0; lvl[n] <- 1

  while (now <= total_ms) {
    if (tc_enabled && now >= next_tick - tc_leadin_ms) {
      elapsed_s <- floor(next_tick / 1000)
      chk <- bitwXor(cks4(elapsed_s), cks4(run_id))
      bits <- c(bits_of(run_id, 16), bits_of(elapsed_s, 32), bits_of(chk, 4))

      now <- next_tick
      for (k in 1:3) {                       # 3-pulse preamble
        n <- n + 1; tms[n] <- now; lvl[n] <- 1
        now <- now + TC_PULSE_MS_G
        n <- n + 1; tms[n] <- now; lvl[n] <- 0
        if (k < 3) now <- now + TC_PRE_GAP_G
      }
      for (b in bits) {                      # 52 payload bits
        now <- now + if (b == 1) TC_ONE_G else TC_ZERO_G
        n <- n + 1; tms[n] <- now; lvl[n] <- 1
        now <- now + TC_PULSE_MS_G
        n <- n + 1; tms[n] <- now; lvl[n] <- 0
      }
      level <- 0
      next_tick <- next_tick + tc_interval_s * 1000
      next
    }

    state <- xorshift(state)
    lo <- if (level == 1) MIN_HIGH_MS else MIN_LOW_MS
    hi <- if (level == 1) MAX_HIGH_MS else MAX_LOW_MS
    dur <- if (lo >= hi) lo else lo + (state %% ((hi - lo) / STEP_MS + 1)) * STEP_MS

    clamped <- FALSE
    if (tc_enabled) {
      remaining <- (next_tick - tc_leadin_ms) - now
      if (remaining <= 0) {
        # Already at the lead-in: hold LOW to the tick. The draw above still
        # happened, which is what keeps the sequence reproducible.
        if (level != 0) {
          level <- 0; n <- n + 1
          tms[n] <- next_tick - tc_leadin_ms; lvl[n] <- 0
        }
        now <- next_tick
        next
      } else if (dur > remaining) {
        dur <- remaining
        clamped <- TRUE
      }
    }

    now <- now + dur
    if (clamped) {
      # Emit a toggle only if the output is HIGH and must come down. Toggling
      # first and correcting afterwards produced a zero-width pulse (HIGH and
      # LOW at one timestamp), which the firmware cannot emit.
      if (level != 0) {
        level <- 0; n <- n + 1; tms[n] <- now; lvl[n] <- 0
      }
      now <- next_tick
      next
    }

    level <- 1 - level
    n <- n + 1
    if (n > length(tms)) { tms <- c(tms, numeric(cap)); lvl <- c(lvl, numeric(cap)) }
    tms[n] <- now; lvl[n] <- level
  }

  data.frame(t_ms = tms[1:n], level = lvl[1:n])
}


# align_template(duration_s, run_id)
#   Edge sets for matching, with frame internals excluded from the
#   fingerprint intervals (see PR_MIN_INTERVAL_S).
align_template <- function(duration_s, run_id = 1) {
  g <- generate_sync_signal_tc(duration_s, run_id)
  t <- g$t_ms / 1000
  pol <- ifelse(g$level == 1, 1, -1)

  mk <- function(sel) {
    et <- t[sel]
    iv <- diff(et)
    keep <- iv >= PR_MIN_INTERVAL_S
    list(edges = et, iv = iv[keep], pos = which(keep))
  }
  list(time = t, polarity = pol, run_id = run_id,
       both = mk(rep(TRUE, length(t))),
       rising = mk(pol > 0),
       falling = mk(pol < 0))
}


# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------

# source_from_edges(name, edge_times, polarity)
#   A recording that reports transition TIMESTAMPS. A rising-only or
#   falling-only stream aligns just as well as a full one: the fingerprint is
#   built from the gaps between the edges you did record, and those gaps are
#   still drawn from the pseudo-random sequence.
source_from_edges <- function(name, edge_times, polarity = "both",
                              fs = NULL, data = NULL, labels = NULL,
                              time = NULL) {
  t <- sort(as.numeric(edge_times))
  if (is.character(polarity)) {
    pol <- switch(polarity,
                  rising  = rep(1, length(t)),
                  falling = rep(-1, length(t)),
                  both    = NULL,
                  stop("polarity must be 'rising', 'falling', 'both', or a vector"))
  } else {
    pol <- as.numeric(polarity)
    if (length(pol) != length(t)) stop("polarity must match edge_times length")
  }
  list(name = name, edges = t, polarity = pol, fs = fs,
       data = data, labels = labels, time = time)
}


# source_from_continuous(name, signal, fs)
#   A recording that captured the square wave as an analog waveform. Reduces
#   it to transition times, which is the same object an edge-only recording
#   provides — after this the two are handled identically.
source_from_continuous <- function(name, signal, fs, data = NULL,
                                   labels = NULL, time = NULL, ...) {
  e <- detect_edges(signal, fs, ...)
  if (is.null(data)) data <- matrix(as.numeric(signal), ncol = 1)
  if (is.null(labels)) labels <- "sync"
  list(name = name, edges = e$time, polarity = e$polarity, fs = fs,
       data = data, labels = labels, time = time)
}


# ---------------------------------------------------------------------------
# Locking
# ---------------------------------------------------------------------------

.pr_intervals <- function(edges) {
  if (length(edges) < 2) return(list(iv = numeric(0), pos = integer(0)))
  d <- diff(edges)
  keep <- d >= PR_MIN_INTERVAL_S
  list(iv = d[keep], pos = which(keep))
}


# align_frames(src)
#   Read the binary timecode frames a recording carries.
#
#   A frame is 52 bits of pulse timing: [16-bit run ID][32-bit elapsed
#   seconds][4-bit checksum]. Where one survives it beats any fingerprint — it
#   states the position outright, checksum-verified, and it is the ONLY thing
#   identifying WHICH RUN was recorded, since a fixed seed makes every run's
#   waveform identical apart from the frame payload.
#
#   The decoder needs a SINGLE-POLARITY stream: frame pulses have constant
#   width, so rising-only and falling-only both decode, but an interleaved
#   both-edges list halves every interval and decodes nothing.
align_frames <- function(src) {
  empty <- list(frames = NULL, run_id = NULL)
  if (length(src$edges) < 55) return(empty)

  tries <- list()
  if (is.null(src$polarity)) {
    tries <- list(list(src$edges, "rising"), list(src$edges, "falling"))
  } else {
    if (any(src$polarity > 0)) tries <- c(tries, list(list(src$edges[src$polarity > 0], "rising")))
    if (any(src$polarity < 0)) tries <- c(tries, list(list(src$edges[src$polarity < 0], "falling")))
  }

  best <- NULL
  for (tr in tries) {
    e <- sort(tr[[1]])
    if (length(e) < 55) next
    got <- tryCatch(decode_timecode(e, edge = tr[[2]]), error = function(...) NULL)
    if (is.null(got) || nrow(got) == 0) next
    ok <- got[got$ok, , drop = FALSE]
    if (is.null(best) || nrow(ok) > nrow(best)) best <- ok
  }
  if (is.null(best) || nrow(best) == 0) return(empty)

  ids <- best$run_id
  u <- unique(ids)
  rid <- u[which.max(vapply(u, function(x) sum(ids == x), numeric(1)))]
  list(frames = best, run_id = rid)
}


# .vote_lock(piv, ppos, sub)
#   Coarse alignment by voting across many short interval windows. The true
#   offset is proposed by every clean window; a window spanning a dropped edge
#   proposes noise, so the plurality tolerates a substantial bad fraction
#   (measured: 100% lock up to 20% dropped edges).
.vote_lock <- function(piv, ppos, sub, tol = INTERVAL_TOL_S, k = FINGERPRINT_K) {
  n <- length(sub$iv)
  if (n < k || length(piv) < k) return(list(shift = NULL, score = 0, total = 0))

  nwin <- n - k + 1
  W <- matrix(0, nwin, k)
  for (j in seq_len(k)) W[, j] <- sub$iv[j:(j + nwin - 1)]

  votes <- new.env(hash = TRUE, parent = emptyenv())
  for (w in seq_len(length(piv) - k + 1)) {
    probe <- piv[w:(w + k - 1)]
    d <- apply(abs(sweep(W, 2, probe, "-")), 1, max)
    for (h in which(d < tol)) {
      key <- as.character(sub$pos[h] - ppos[w])
      cur <- if (exists(key, envir = votes, inherits = FALSE)) get(key, envir = votes) else 0
      assign(key, cur + 1, envir = votes)
    }
  }
  ks <- ls(votes)
  if (length(ks) == 0) return(list(shift = NULL, score = 0, total = 0))
  vs <- vapply(ks, function(k2) get(k2, envir = votes), numeric(1))
  i <- which.max(vs)
  list(shift = as.numeric(ks[i]), score = vs[i], total = sum(vs))
}


.pair_at <- function(src_edges, predicted, tmpl_edges, tol_s) {
  ps <- numeric(0); pt <- numeric(0)
  for (i in seq_along(src_edges)) {
    j <- which.min(abs(tmpl_edges - predicted[i]))
    if (abs(tmpl_edges[j] - predicted[i]) <= tol_s) {
      ps <- c(ps, src_edges[i]); pt <- c(pt, tmpl_edges[j])
    }
  }
  list(ps = ps, pt = pt)
}


# align_lock(src, tmpl, tol_s)
#   Place one recording on the template timeline. Frames first (they state
#   position outright and identify the run), gap fingerprint as fallback — a
#   device that low-passes the signal may smear the 5/15/25 ms frame intervals
#   past decoding while its 50-500 ms pseudo-random edges stay clean.
align_lock <- function(src, tmpl, tol_s = INTERVAL_TOL_S) {
  fit <- list(name = src$name, ok = FALSE, offset_s = NA, rate = NA,
              drift_ppm = NA, n_edges = length(src$edges), n_matched = 0,
              match_rate = 0, rms_ms = NA, confidence = 0, run_id = NULL,
              source_of_lock = "", segments = NULL, drops = NULL,
              frame_gaps = NULL, anchors = NULL, nonlinear = FALSE, note = "")

  e <- src$edges
  if (length(e) < FINGERPRINT_K + 1) {
    fit$note <- sprintf("only %d edges; need at least %d",
                        length(e), FINGERPRINT_K + 1)
    return(fit)
  }

  stream <- "both"
  if (!is.null(src$polarity)) {
    if (all(src$polarity > 0)) stream <- "rising"
    else if (all(src$polarity < 0)) stream <- "falling"
  }
  sub <- tmpl[[stream]]

  fr <- align_frames(src)
  fit$run_id <- fr$run_id
  A <- NULL

  if (!is.null(fr$frames) && nrow(fr$frames) >= 2) {
    A <- cbind(fr$frames$t_rec, as.numeric(fr$frames$elapsed_s), 1)
    fit$source_of_lock <- "timecode"

    # Frames arrive on a known cadence, so a gap in the sequence says both
    # that data is missing and which window it is missing from — a much
    # tighter bound on where to cut than a fitted residual gives.
    d <- diff(as.numeric(fr$frames$elapsed_s))
    interval <- if (length(d)) stats::median(d[d > 0]) else NA
    if (is.finite(interval) && interval > 0) {
      gaps <- NULL
      for (k in 2:nrow(fr$frames)) {
        de <- fr$frames$elapsed_s[k] - fr$frames$elapsed_s[k - 1]
        if (de > 1.5 * interval)
          gaps <- rbind(gaps, c(fr$frames$t_rec[k - 1], fr$frames$t_rec[k],
                                floor(de / interval) - 1))
      }
      fit$frame_gaps <- gaps
    }
  }

  if (is.null(A) || nrow(A) < 2) {
    pr <- .pr_intervals(e)
    if (length(pr$iv) < FINGERPRINT_K) {
      fit$note <- sprintf(paste0("only %d pseudo-random intervals (>= %.0f ms); ",
                                 "the recording may be too short, or all its ",
                                 "edges fall inside timecode frames"),
                          length(pr$iv), PR_MIN_INTERVAL_S * 1000)
      return(fit)
    }
    A <- NULL
    w <- 1
    while (w + ANCHOR_WINDOW_EDGES - 1 <= length(pr$iv)) {
      sl <- w:(w + ANCHOR_WINDOW_EDGES - 1)
      v <- .vote_lock(pr$iv[sl], pr$pos[sl], sub, tol_s)
      if (!is.null(v$shift) && v$score >= MIN_VOTES && v$total > 0) {
        i <- pr$pos[w]; j <- i + v$shift
        if (i >= 1 && i <= length(e) && j >= 1 && j <= length(sub$edges))
          A <- rbind(A, c(e[i], sub$edges[j], v$score / v$total))
      }
      w <- w + ANCHOR_STRIDE_EDGES
    }
    if (is.null(A)) {
      v <- .vote_lock(pr$iv, pr$pos, sub, tol_s)
      if (!is.null(v$shift) && v$score >= MIN_VOTES) {
        i <- pr$pos[1]; j <- i + v$shift
        if (j >= 1 && j <= length(sub$edges))
          A <- rbind(A, c(e[i], sub$edges[j], v$score / max(v$total, 1)))
      }
    }
    fit$source_of_lock <- "fingerprint"
  }

  if (is.null(A) || nrow(A) == 0) {
    fit$note <- paste0("could not lock to the template. Check that the seed ",
                       "and timing config match the firmware that produced ",
                       "this recording, and that the sync channel is right.")
    return(fit)
  }

  fit$confidence <- stats::median(A[, 3])
  good <- A[A[, 3] >= ANCHOR_MIN_CONF, , drop = FALSE]
  if (nrow(good) == 0)
    good <- A[A[, 3] >= max(0.5, max(A[, 3]) * 0.9), , drop = FALSE]
  if (nrow(good) == 0) {
    fit$note <- "locked only weakly; no window reached usable confidence"
    return(fit)
  }

  tl <- good[, 1]; tg <- good[, 2]
  fit$anchors <- cbind(tl, tg)

  # A straight-line clock leaves residuals at the anchor noise floor; a
  # wandering one curves away from it.
  if (length(tl) >= 4) {
    cf <- stats::coef(stats::lm(tg ~ tl))
    r <- tg - (cf[2] * tl + cf[1])
    fit$nonlinear <- max(abs(r)) > 0.004
  }

  offs <- tg - tl
  segs <- NULL; drops <- NULL
  if (length(tl) >= 2) {
    jumps <- which(abs(diff(offs)) > STEP_THRESHOLD_S)
    bounds <- c(1, jumps + 1, length(tl) + 1)
    for (b in seq_len(length(bounds) - 1)) {
      a1 <- bounds[b]; a2 <- bounds[b + 1] - 1
      if (a2 < a1) next
      if (a2 - a1 >= 1) {
        cf <- stats::coef(stats::lm(tg[a1:a2] ~ tl[a1:a2]))
        rate <- unname(cf[2])
      } else rate <- 1
      offset <- stats::median(tg[a1:a2] - rate * tl[a1:a2])
      t_end <- if (b == length(bounds) - 1) e[length(e)] else tl[a2]
      segs <- rbind(segs, c(tl[a1], t_end, offset, rate))
    }
    for (k in seq_along(jumps))
      if (k + 1 <= nrow(segs))
        drops <- rbind(drops, c(tl[jumps[k] + 1],
                                (segs[k + 1, 3] - segs[k, 3]) * 1000))
  }
  if (is.null(segs)) segs <- matrix(c(e[1], e[length(e)],
                                      stats::median(offs), 1), nrow = 1)

  fit$segments <- if (nrow(segs) > 1) segs else NULL
  fit$offset_s <- segs[1, 3]
  fit$rate <- segs[1, 4]
  fit$drift_ppm <- (fit$rate - 1) * 1e6
  fit$drops <- drops

  pred <- align_apply(fit, e)
  pr2 <- .pair_at(e, pred, sub$edges, tol_s)
  fit$n_matched <- length(pr2$ps)
  fit$match_rate <- length(pr2$ps) / max(1, length(e))
  if (length(pr2$ps)) {
    resid <- pr2$pt - align_apply(fit, pr2$ps)
    fit$rms_ms <- sqrt(mean(resid^2)) * 1000
  }
  fit$ok <- TRUE
  fit
}


# align_apply(fit, t_local)
#   Map a recording's own clock onto global (template) time.
#
#   Uses a SLIDING window over the timecode anchors when the anchors show the
#   clock actually changing. The window is centred so each point sits between
#   anchors on both sides rather than at a segment edge, and adjacent windows
#   overlap — so a correction blends across a cut instead of stepping at it.
#   On a steady recorder a single line is exact, and local fits would only
#   inject anchor noise, so sliding is skipped.
align_apply <- function(fit, t_local) {
  t <- as.numeric(t_local)

  if (isTRUE(fit$nonlinear) && !is.null(fit$anchors) && nrow(fit$anchors) >= 4) {
    ta <- fit$anchors[, 1]; ga <- fit$anchors[, 2]; n <- length(ta)
    out <- numeric(length(t))
    for (i in seq_along(t)) {
      k <- sum(ta <= t[i])
      lo <- max(1, min(k, n - 3)); hi <- min(n, lo + 3); lo <- max(1, hi - 3)
      if (hi - lo >= 1) {
        cf <- stats::coef(stats::lm(ga[lo:hi] ~ ta[lo:hi]))
        out[i] <- unname(cf[2]) * t[i] + unname(cf[1])
      } else out[i] <- t[i] + (ga[lo] - ta[lo])
    }
    return(out)
  }

  if (!is.null(fit$segments)) {
    segs <- fit$segments
    out <- numeric(length(t))
    for (i in seq_along(t)) {
      k <- max(1, min(sum(segs[, 1] <= t[i]), nrow(segs)))
      out[i] <- segs[k, 3] + segs[k, 4] * t[i]
    }
    return(out)
  }

  fit$offset_s + fit$rate * t
}


# ---------------------------------------------------------------------------
# Resampling
# ---------------------------------------------------------------------------

# align_resample(src_t, src_v, dst_t, how, gap_s, target_fs, src_fs)
#   Never interpolates across a gap: where the source has no samples within
#   gap_s, the output is NA. Inventing values across a dropped chunk would
#   silently manufacture data.
#
#   Downsampling without a low-pass is silent corruption, not merely
#   inaccuracy: a 230 Hz tone taken from 2000 Hz to 100 Hz reappears at FULL
#   amplitude disguised as 30 Hz. 'nearest' is exempt — it exists to keep
#   marker values intact, and filtering them would invent levels that were
#   never recorded.
align_resample <- function(src_t, src_v, dst_t, how = "linear", gap_s = NULL,
                           target_fs = NULL, src_fs = NULL) {
  good <- is.finite(src_t) & is.finite(src_v)
  if (sum(good) < 2) return(rep(NA_real_, length(dst_t)))
  st <- src_t[good]; sv <- as.numeric(src_v[good])

  if (how != "nearest" && !is.null(target_fs)) {
    sv <- .antialias(st, sv, target_fs, src_fs)
  }

  out <- stats::approx(st, sv, xout = dst_t,
                       method = if (how == "nearest") "constant" else "linear",
                       rule = 1, f = 0.5)$y
  out[dst_t < st[1] | dst_t > st[length(st)]] <- NA_real_

  if (!is.null(gap_s) && length(st) > 1) {
    d <- diff(st)
    for (i in which(d > gap_s))
      out[dst_t > st[i] & dst_t < st[i + 1]] <- NA_real_
  }
  out
}


.antialias <- function(t, v, target_fs, src_fs) {
  if (is.null(src_fs)) {
    d <- diff(t); d <- d[is.finite(d) & d > 0]
    if (!length(d)) return(v)
    src_fs <- 1 / stats::median(d)
  }
  if (target_fs >= src_fs * 0.98) return(v)     # not decimating
  if (!requireNamespace("signal", quietly = TRUE)) {
    warning(sprintf(paste0("Decimating %g Hz to %g Hz without the 'signal' ",
                           "package, so no anti-alias filter was applied. ",
                           "Content above %g Hz will fold back into the ",
                           "result at full amplitude."),
                    src_fs, target_fs, target_fs / 2))
    return(v)
  }
  wn <- (0.45 * target_fs) / (src_fs / 2)
  if (wn <= 0 || wn >= 1) return(v)
  bf <- signal::butter(4, wn, type = "low")

  # Reflect-pad before filtering. R's filtfilt does not extend the signal at
  # its ends, so the first and last samples ring: a 70 Hz tone that the
  # filter suppresses to 0.0008 mid-signal still showed 0.27 at the edges,
  # which is the kind of artifact that looks like real data. scipy's filtfilt
  # pads by default, which is why the Python side did not need this.
  n <- length(v)
  pad <- min(3 * length(bf$a), n %/% 2)
  if (pad < 2) return(signal::filtfilt(bf, v))
  head_ <- 2 * v[1] - v[(pad + 1):2]
  tail_ <- 2 * v[n] - v[(n - 1):(n - pad)]
  y <- signal::filtfilt(bf, c(head_, v, tail_))
  y[(pad + 1):(pad + n)]
}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

# align_recordings_tc(sources, mode)
#   mode: 'lags' | 'global_time' | 'stitch'
#
#   Named to avoid colliding with align_recordings() in sync_align.R, which is
#   the older cross-correlation aligner.
align_recordings_tc <- function(sources, mode = "global_time",
                                resample = "linear", target_fs = NULL,
                                duration_s = NULL, run_id = NULL,
                                tol_s = INTERVAL_TOL_S, gap_factor = 3) {
  if (!mode %in% c("lags", "global_time", "stitch"))
    stop("mode must be 'lags', 'global_time', or 'stitch'")
  if (!length(sources)) stop("no sources given")

  span <- max(vapply(sources, function(s)
    if (length(s$edges)) max(s$edges) else 0, numeric(1)))
  if (is.null(duration_s)) duration_s <- max(60, span * 1.5 + 60)

  # Discover the run BEFORE building the template. Frame payloads encode the
  # run ID, so a template built for the wrong run has the right pseudo-random
  # train but different frame bits: offsets still come out right (the frames
  # supply them) while a large fraction of edges fail to pair.
  if (is.null(run_id)) {
    votes <- unlist(lapply(sources, function(s) align_frames(s)$run_id))
    run_id <- if (length(votes)) {
      u <- unique(votes)
      u[which.max(vapply(u, function(x) sum(votes == x), numeric(1)))]
    } else 1
  }

  tmpl <- align_template(duration_s, run_id)
  fits <- lapply(sources, function(s) align_lock(s, tmpl, tol_s))
  warns <- character(0)

  ids <- unlist(lapply(fits, function(f) f$run_id))
  if (length(unique(ids)) > 1) {
    parts <- vapply(sort(unique(ids)), function(r) {
      nm <- vapply(fits[vapply(fits, function(f) isTRUE(f$run_id == r), logical(1))],
                   function(f) f$name, character(1))
      sprintf("run %d: %s", r, paste(nm, collapse = ", "))
    }, character(1))
    warns <- c(warns, sprintf(paste0("Recordings come from %d DIFFERENT ",
      "generator runs (%s). Each run restarts the elapsed clock from its own ",
      "zero, so these cannot be placed on one timeline. Split them by run and ",
      "align each group separately."),
      length(unique(ids)), paste(parts, collapse = "; ")))
  }

  for (f in fits) {
    if (!f$ok) { warns <- c(warns, sprintf("%s: %s", f$name, f$note)); next }
    if (f$match_rate < 0.5)
      warns <- c(warns, sprintf("%s: only %.0f%% of its edges matched the template.",
                                f$name, 100 * f$match_rate))
    if (abs(f$drift_ppm) > 1000)
      warns <- c(warns, sprintf("%s: clock differs by %+.0f ppm (%.0f ms/hour).",
                                f$name, f$drift_ppm, f$drift_ppm * 3.6))
    if (!is.null(f$drops))
      for (k in seq_len(nrow(f$drops)))
        warns <- c(warns, sprintf(paste0("%s: timeline steps by %+.1f ms at ",
                                         "t=%.2f s - the recorder lost count."),
                                  f$name, f$drops[k, 2], f$drops[k, 1]))
  }

  res <- list(mode = mode, run_id = run_id, fits = fits,
              warnings = warns, global_time = list())
  if (mode == "lags") return(res)

  for (i in seq_along(sources)) {
    if (!fits[[i]]$ok) next
    s <- sources[[i]]
    st <- if (!is.null(s$time)) s$time
          else if (!is.null(s$data) && !is.null(s$fs)) (seq_len(nrow(as.matrix(s$data))) - 1) / s$fs
          else s$edges
    res$global_time[[s$name]] <- align_apply(fits[[i]], st)
  }
  if (mode == "global_time") return(res)

  use <- which(vapply(seq_along(sources), function(i)
    fits[[i]]$ok && !is.null(sources[[i]]$data), logical(1)))
  if (!length(use))
    stop("stitch needs at least one source with data that locked")

  if (is.null(target_fs)) {
    rates <- unlist(lapply(sources[use], function(s) s$fs))
    target_fs <- if (length(rates)) max(rates) else 1000
  }

  t0 <- min(vapply(use, function(i) res$global_time[[sources[[i]]$name]][1], numeric(1)))
  t1 <- max(vapply(use, function(i) {
    g <- res$global_time[[sources[[i]]$name]]; g[length(g)] }, numeric(1)))
  common <- seq(t0, t1, by = 1 / target_fs)

  cols <- list()
  for (i in use) {
    s <- sources[[i]]
    g <- res$global_time[[s$name]]
    d <- as.matrix(s$data)
    labs <- s$labels
    if (is.null(labs)) labs <- paste0("ch", seq_len(ncol(d)))
    gap_s <- if (!is.null(s$fs)) gap_factor / s$fs else NULL
    for (c in seq_len(ncol(d)))
      cols[[paste0(s$name, ".", labs[c])]] <-
        align_resample(g, d[, c], common, resample, gap_s, target_fs, s$fs)
  }
  res$table <- list(time = common, columns = cols, fs = target_fs,
                    n = length(common))
  res
}
