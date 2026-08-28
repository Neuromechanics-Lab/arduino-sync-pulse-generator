# test_align.R — self-tests for the R aligner.
#   Rscript test_align.R
#
# Mirrors utils/python/test_align.py and utils/matlab/test_align.m. Each case
# is one that broke an earlier implementation, so a regression shows up as a
# failure rather than a plausible-looking wrong number.

suppressWarnings(source("edge_sync.R"))
source("timecode_decode.R")
source("align.R")

.pass <- 0; .fail <- 0
check <- function(cond, msg) if (!isTRUE(cond)) stop(msg, call. = FALSE)
runtest <- function(name, f) {
  out <- tryCatch({ f(); TRUE }, error = function(e) { cat(sprintf("FAIL %s: %s\n", name, conditionMessage(e))); FALSE })
  if (out) { cat(sprintf("ok   %s\n", name)); .pass <<- .pass + 1 } else .fail <<- .fail + 1
}
jit <- function(x) x + rnorm(length(x), 0, 0.0008)


runtest("generator matches the firmware's shape", function() {
  g <- generate_sync_signal_tc(60, 137)
  check(abs(g$t_ms[1]) < 1e-9, "first toggle must be at t=0")
  check(g$level[1] == 1, "first toggle is LOW->HIGH")
  d <- diff(g$t_ms)
  check(all(d >= 0), "edge times must be non-decreasing")
  check(!any(d == 0), "zero-width pulses are not emittable by the firmware")
  check(any(abs(g$t_ms - 10000) < 1e-6), "a frame should start at 10 s")
})


runtest("pure offset recovered, run id read from the signal", function() {
  set.seed(1)
  tmpl <- align_template(300, 137)
  w <- tmpl$time > 20 & tmpl$time < 140
  f <- align_lock(source_from_edges("a", jit(tmpl$time[w] - 20),
                                    tmpl$polarity[w]), tmpl)
  check(f$ok, f$note)
  check(abs(f$offset_s - 20) < 0.01, sprintf("offset %.4f", f$offset_s))
  check(f$match_rate > 0.98, sprintf("matched %.2f", f$match_rate))
  check(identical(as.numeric(f$run_id), 137), "run id should come from the frames")
})


# The headline case: a device that reports only one edge polarity.
runtest("rising-only and falling-only both lock", function() {
  set.seed(2)
  tmpl <- align_template(300, 137)
  w <- tmpl$time > 20 & tmpl$time < 140
  for (spec in list(list("rising", tmpl$polarity > 0),
                    list("falling", tmpl$polarity < 0))) {
    sel <- w & spec[[2]]
    f <- align_lock(source_from_edges("x", jit(tmpl$time[sel] - 20),
                                      spec[[1]]), tmpl)
    check(f$ok, paste(spec[[1]], f$note))
    check(abs(f$offset_s - 20) < 0.01,
          sprintf("%s offset %.4f", spec[[1]], f$offset_s))
    check(f$match_rate > 0.98,
          sprintf("%s matched %.2f", spec[[1]], f$match_rate))
  }
})


# 300 ppm moves alignment ~57 ms over three minutes, far outside any fixed
# pairing window — which is what broke the first implementation.
runtest("300 ppm clock drift recovered", function() {
  set.seed(3)
  tmpl <- align_template(400, 137)
  w <- tmpl$time > 15 & tmpl$time < 215
  f <- align_lock(source_from_edges("d", jit((tmpl$time[w] - 15) / 1.0003),
                                    tmpl$polarity[w]), tmpl)
  check(f$ok, f$note)
  check(abs(f$offset_s - 15) < 0.02, sprintf("offset %.4f", f$offset_s))
  check(f$drift_ppm > 250 && f$drift_ppm < 350,
        sprintf("drift %.0f ppm", f$drift_ppm))
})


# A counter-based recorder that loses 250 ms labels everything after it early.
# That IS a step and must split the time map.
runtest("lost-count step split into segments", function() {
  set.seed(4)
  tmpl <- align_template(400, 137)
  w <- tmpl$time > 5 & tmpl$time < 180
  base <- tmpl$time[w] - 5; pol <- tmpl$polarity[w]
  alive <- base < 55 | base > 55.25
  tt <- base[alive]; pp <- pol[alive]
  loc <- tt; loc[tt > 55] <- loc[tt > 55] - 0.25
  f <- align_lock(source_from_edges("e", jit(loc), pp), tmpl)
  check(f$ok, f$note)
  check(!is.null(f$segments) && nrow(f$segments) == 2, "expected 2 segments")
  check(!is.null(f$drops) && nrow(f$drops) >= 1, "expected a drop")
  step <- f$drops[1, 2]
  check(step > 240 && step < 260, sprintf("step %.1f ms", step))
})


runtest("end-to-end lag across 1000/2000 Hz sources", function() {
  set.seed(5)
  tmpl <- align_template(400, 137); T <- tmpl$time
  build <- function(st, fs, dur)
    as.numeric(sapply(st + (0:(round(dur * fs) - 1)) / fs,
                      function(x) sum(T <= x)) %% 2)
  s1 <- source_from_continuous("vicon", build(12, 1000, 80) + rnorm(80000, 0, 0.01), 1000)
  s2 <- source_from_continuous("daq",   build(40, 2000, 50) + rnorm(100000, 0, 0.01), 2000)
  r <- align_recordings_tc(list(s1, s2), mode = "lags")
  check(all(vapply(r$fits, function(f) f$ok, logical(1))), "both should lock")
  lag <- r$fits[[2]]$offset_s - r$fits[[1]]$offset_s
  check(abs(lag - 28) < 0.01, sprintf("lag %.4f, want 28", lag))
})


# Downsampling without a low-pass is silent corruption: a 230 Hz tone taken
# from 2000 Hz to 100 Hz reappears at full amplitude disguised as 30 Hz.
runtest("decimation is anti-aliased", function() {
  if (!requireNamespace("signal", quietly = TRUE)) {
    cat("     (skipped: package 'signal' not installed)\n"); return(invisible())
  }
  fs_hi <- 2000; fs_lo <- 100
  t <- (0:(6 * fs_hi - 1)) / fs_hi
  dst <- (0:(6 * fs_lo - 1)) / fs_lo
  for (f0 in c(10, 30)) {
    out <- align_resample(t, sin(2 * pi * f0 * t), dst, "linear", NULL, fs_lo, fs_hi)
    check(max(abs(out[is.finite(out)])) > 0.7, sprintf("%g Hz should survive", f0))
  }
  for (f0 in c(70, 130, 230, 430)) {
    out <- align_resample(t, sin(2 * pi * f0 * t), dst, "linear", NULL, fs_lo, fs_hi)
    check(max(abs(out[is.finite(out)])) < 0.15, sprintf("%g Hz should be suppressed", f0))
  }
})


cat(sprintf("\n%d/%d passed\n\n", .pass, .pass + .fail))
if (.fail > 0) quit(status = 1)
