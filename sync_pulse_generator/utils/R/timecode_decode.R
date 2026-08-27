# timecode_decode.R — decode timecode frames from the sync_pulse_generator's
# hybrid signal, and place a recording on the generator's own timeline.
# Companion to sync_align.R: frames give ABSOLUTE anchors (generator elapsed
# seconds), cross-correlation refines between them.
#
# Frame format: 3-pulse preamble (5 ms pulses, 10 ms gaps), then 52 bits as
# gaps (15 ms = 0, 25 ms = 1), MSB-first: [16-bit run ID][32-bit elapsed
# seconds][4-bit checksum = XOR of all nibbles of both fields]. See
# utils/python/timecode.py for the reference implementation and template
# generator, and utils/matlab/decode_timecode.m for the MATLAB port.
#
# ---------------------------------------------------------------------------
# WHAT A RUN IS, AND WHY IT MATTERS
#
# The generator's elapsed clock is not a wall clock. It counts from the start
# of the current RUN, and every run start increments the persistent run ID.
# A run starts when:
#
#   * the box boots in FREE RUN mode (output begins immediately);
#   * a trigger edge arrives on TRIG IN while in TRIG RUN mode (outputs are
#     held LOW until then, so elapsed 0 IS the trigger);
#   * the mode switch is moved to FREE RUN;
#   * a serial 'start' or 'restart' command is issued.
#
# So elapsed_s means "seconds since this run began", and what began the run
# depends on the mode. In FREE RUN, elapsed 0 is power-up. In TRIG RUN,
# elapsed 0 is the trigger pulse — the useful case for starting several
# devices together from one master pulse.
#
# Because the run ID changes at every one of those events, TWO RECORDINGS
# SHARE A TIMELINE ONLY IF THEIR RUN IDS MATCH. Comparing elapsed values
# across different run IDs is meaningless: they count from different zeros.
# align_to_timecode() treats a run ID change as a hard boundary.
# ---------------------------------------------------------------------------

TC_PULSE_MS        <- 5
TC_PREAMBLE_GAP_MS <- 10
TC_GAP_ZERO_MS     <- 15
TC_GAP_ONE_MS      <- 25

checksum4 <- function(v) {
  c <- 0
  for (i in 1:8) { c <- bitwXor(c, v %% 16); v <- v %/% 16 }
  c
}

# decode_timecode(edge_times, edge = "rising")
#   edge_times : sorted numeric vector of edge timestamps in SECONDS
#                (rising or falling — constant pulse width makes the
#                intervals identical; "falling" corrects anchors by the
#                pulse width so t_rec is always the pulse START)
#   returns    : data.frame(t_rec, run_id, elapsed_s, ok)
decode_timecode <- function(edge_times, edge = "rising", tol_ms = 3) {
  pulse <- TC_PULSE_MS / 1000
  pre <- (TC_PULSE_MS + TC_PREAMBLE_GAP_MS) / 1000
  b0  <- (TC_PULSE_MS + TC_GAP_ZERO_MS) / 1000
  b1  <- (TC_PULSE_MS + TC_GAP_ONE_MS) / 1000
  tol <- tol_ms / 1000
  e <- sort(edge_times)
  n <- length(e)
  res <- data.frame(t_rec = numeric(0), run_id = numeric(0),
                    elapsed_s = numeric(0), ok = logical(0))

  i <- 1
  while (i + 54 <= n) {
    d1 <- e[i + 1] - e[i]; d2 <- e[i + 2] - e[i + 1]
    if (abs(d1 - pre) < tol && abs(d2 - pre) < tol) {
      gaps <- diff(e[(i + 2):(i + 54)])
      bits <- ifelse(abs(gaps - b0) < tol, 0,
                     ifelse(abs(gaps - b1) < tol, 1, NA))
      if (!anyNA(bits)) {
        val <- 0
        for (b in bits) val <- val * 2 + b        # <= 2^52, exact in doubles
        run_id <- val %/% 2^36
        secs <- (val %/% 16) %% 2^32
        chk <- val %% 16
        anchor <- e[i] - if (edge == "falling") pulse else 0
        chk_ok <- bitwXor(checksum4(secs), checksum4(run_id)) == chk
        res <- rbind(res, data.frame(t_rec = anchor, run_id = run_id,
                                     elapsed_s = secs, ok = chk_ok))
        i <- i + 55
        next
      }
    }
    i <- i + 1
  }
  res
}

# split_runs(frames)
#   Group decoded frames by run ID, in order of first appearance. A run ID
#   change marks a generator restart (trigger, mode switch, or serial
#   restart). Recordings spanning a boundary must be split there before
#   alignment, because elapsed times on either side count from different
#   zeros.
#   returns : named list of data.frames, names are the run IDs
split_runs <- function(frames) {
  ids <- unique(frames$run_id)
  out <- lapply(ids, function(r) frames[frames$run_id == r, , drop = FALSE])
  names(out) <- as.character(ids)
  out
}

ANCHOR_TOL_MS <- 10   # frames start ON the tick; anchors agree to within the
                      # recorder's edge-timing resolution

# .anchor_fit(t, el)
#   Offset + drift from EXACT anchors. Every frame starts on the tick, so all
#   anchors carry equal weight: offset = mean(elapsed - t_rec), drift = the
#   least-squares slope of the offsets against recording time.
#   returns : list(offset_s, drift_ppm, resid_ms, resolvable). drift_ppm is 0
#   unless resolvable: the drift must both exceed the anchor tolerance over
#   the span observed and clear the slope's own noise floor by 3x.
.anchor_fit <- function(t, el) {
  n <- length(t)
  offs <- el - t
  offset <- mean(offs)
  span <- if (n > 0) diff(range(t)) else 0
  if (n < 3 || span <= 0) {
    resid <- if (n > 1) diff(range(offs)) * 1000 else 0
    return(list(offset_s = offset, drift_ppm = 0, resid_ms = resid,
                resolvable = FALSE))
  }
  mx <- mean(t)
  sxx <- sum((t - mx)^2)
  slope <- sum((t - mx) * (offs - offset)) / sxx
  intercept <- offset - slope * mx
  resid <- offs - (slope * t + intercept)
  resid_ms <- max(abs(resid)) * 1000
  drift_ppm <- slope * 1e6
  slope_noise_ppm <- (diff(range(resid)) / span) * 1e6
  resolvable <- (abs(drift_ppm) * span / 1000 > ANCHOR_TOL_MS) &&
                (abs(drift_ppm) > 3 * slope_noise_ppm)
  list(offset_s = offset, drift_ppm = if (resolvable) drift_ppm else 0,
       resid_ms = resid_ms, resolvable = resolvable)
}

# align_to_timecode(frames)
#   Place a recording on the generator's timeline.
#
#   ANCHOR ACCURACY
#
#   Frames start EXACTLY on the interval tick (the firmware cuts the random
#   segment short and holds LOW for a lead-in), so every anchor is exact:
#   t_rec of a frame IS elapsed_s of generator time, to the millisecond.
#   Offsets should agree across frames to within ANCHOR_TOL_MS; residuals
#   beyond that mean a mis-decoded frame or coarse recorder timing.
#
#   max_pulse_ms is accepted for backward compatibility and ignored (it
#   parameterised the emission jitter of firmware that emitted frames late).
#
#   returns : list(n_runs, run_ids, runs, primary, offset_s,
#                  to_generator, to_recording, warnings)
align_to_timecode <- function(frames, require_ok = TRUE, expect_run = NULL,
                              max_pulse_ms = NULL) {
  if (nrow(frames) == 0)
    stop("No timecode frames were decoded. Either the generator had timecode ",
         "disabled (DEFAULT_TC_ENABLED 0), the recording is shorter than one ",
         "frame interval, or the edge detector missed the frame pulses — ",
         "they are only ", TC_PULSE_MS, " ms wide.")

  if (require_ok) {
    frames <- frames[frames$ok, , drop = FALSE]
    if (nrow(frames) == 0)
      stop("Frames were found but every checksum failed. The frame timing ",
           "constants here may not match the firmware that produced the ",
           "recording — check TC_* in config.h.")
  }

  if (!is.null(expect_run)) {
    frames <- frames[frames$run_id == expect_run, , drop = FALSE]
    if (nrow(frames) == 0)
      stop("No frames carry run ID ", expect_run, ".")
  }

  warnings_out <- character(0)
  ids <- unique(frames$run_id)
  runs <- list()

  for (rid in ids) {
    sel <- frames[frames$run_id == rid, , drop = FALSE]
    t  <- sel$t_rec
    el <- sel$elapsed_s
    d <- .anchor_fit(t, el)
    runs[[as.character(rid)]] <- list(
      run_id = rid, n_frames = nrow(sel),
      t_rec_first = min(t), t_rec_last = max(t),
      elapsed_first = min(el), elapsed_last = max(el),
      offset_s = d$offset_s, drift_ppm = d$drift_ppm,
      drift_resolvable = d$resolvable, residual_ms = d$resid_ms)
  }

  primary <- runs[[which.max(vapply(runs, function(r) r$n_frames, numeric(1)))]]

  if (length(ids) > 1)
    warnings_out <- c(warnings_out, sprintf(
      paste0("%d different run IDs appear in this recording (%s). The ",
             "generator restarted mid-recording — a trigger arrived, the mode ",
             "switch moved, or it was restarted over serial. Each run counts ",
             "elapsed time from its own zero, so they CANNOT be placed on one ",
             "timeline. Run %d (%d frames) was used; split the recording at ",
             "the boundary to use the others."),
      length(ids), paste(ids, collapse = ", "),
      primary$run_id, primary$n_frames))

  if (primary$n_frames < 2)
    warnings_out <- c(warnings_out,
      paste0("Only one frame was decoded, so the offset rests on a single ",
             "anchor and no drift estimate is possible. Record for at least ",
             "two frame intervals for a checkable alignment."))

  span <- max(primary$t_rec_last - primary$t_rec_first, 1e-9)
  if (isTRUE(primary$drift_resolvable))
    warnings_out <- c(warnings_out, sprintf(
      paste0("Clock rate differs by %.0f ppm between the generator and the ",
             "recorder (%.1f ms per minute, %.0f ms over the %.0f s ",
             "observed). A constant offset will not hold across a long trial."),
      primary$drift_ppm, primary$drift_ppm * 60 / 1000,
      abs(primary$drift_ppm) * span / 1000, span))

  if (primary$residual_ms > ANCHOR_TOL_MS)
    warnings_out <- c(warnings_out, sprintf(
      paste0("Frame anchors scatter by up to %.0f ms about the fit, more ",
             "than the %.0f ms anchor tolerance. Frames start exactly on the ",
             "tick, so this means a frame was mis-decoded or the recorder's ",
             "edge timing is coarser than expected."),
      primary$residual_ms, ANCHOR_TOL_MS))

  offset <- primary$offset_s
  list(n_runs = length(ids), run_ids = ids, runs = runs, primary = primary,
       offset_s = offset,
       to_generator = function(t_rec) t_rec + offset,
       to_recording = function(t_gen) t_gen - offset,
       warnings = warnings_out)
}
