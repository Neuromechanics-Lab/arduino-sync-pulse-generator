# CLAUDE.md — sync pulse generator

Instructions for AI assistants working in this repository.

## What this is

An Arduino-based synchronisation signal generator and the offline analysis
tools that go with it. The box emits a pseudo-random square wave whose every
transition is determined by (seed, configuration), which makes the emitted
waveform reproducible offline and therefore usable as ground truth: each
recorded edge has a known true time, and the difference is the recorder's
error.

Licence: **MIT**. See LICENSE. This is the open, publishable form of the work.

## Commit notes — hard rules

`COMMIT_NOTES.md` at the repo root is the running log. Keep it current.

**Write in plain engineering prose about what changed and why.** State the
defect, the mechanism, and the fix. Past tense for what was wrong, present
for what it does now.

**Do not mention, in commit messages, commit notes, code comments, or
documentation:**

- Any other product, tool, or hardware line by name. This repository stands
  alone and its history must read as its own.
- AI assistance of any kind — no co-authorship trailers, no "generated with",
  no attribution lines, no references to a model or assistant.
- Session links, conversation URLs, or tooling identifiers.

This is not cosmetic. The repository is intended for publication and its
history should read as the work of its author, describing only itself.

**Line format** — trailing ISO timestamp, America/New_York:

```
- fix(analysis): one-sentence statement of the defect and the fix (2026-09-13T18:30:00-04:00)
```

Prefixes: `fix(area)`, `feat(area)`, `docs(area)`, `test(area)`,
`refactor(area)`.

## Working on the analysis code

`sync_pulse_generator/utils/` holds the analysis tools in three languages.

**Python is the reference implementation.** MATLAB and R carry the alignment
core with matching function names; several capabilities are Python-only and
the utils README marks them. If you add a capability, say plainly in the
README which languages have it — do not describe an absent capability as a
missing "convenience wrapper".

**Verify against real data before claiming a fix works.** The suites are:

```bash
cd sync_pulse_generator/utils/python
python3 test_align.py       # 16 tests, each a named past failure
python3 test_edge_sync.py   # 7, edge detection and EMG
python3 test_events.py      # 11, event channel decoder
python3 test_presync.py     # 9, invariants + real-data regression
python3 timecode.py         # round-trip self-test
```

All 43 must pass. `test_presync.py` pins real numbers from a session where
the answer is independently known, because a rewrite once produced the same
edge count with intervals differing by up to 307 ms — nothing raised, the
stream simply located against the wrong pattern. Counting is not verifying.

## The duration quantum — read before touching decoders

The generator emits only multiples of one quantum. Two exist:

- **5 ms** — the simple variant, a bare square wave with no timecode frames.
  Every recording made to date is this.
- **0.25 ms** — the full variant, which emits timecode frames.

Getting this wrong does not degrade a result, it **prevents a lock**: a
template built on the wrong quantum is a different waveform, and the failure
looks like corrupt data rather than a configuration mismatch. This cost real
debugging time.

`truth._resolve_step_ms()` resolves it from the recording — a decodable frame
means the full variant, no frame means the simple one — and an explicit
`step_ms=` always wins. **Every report states which quantum it used and why.**

Preserve that property. If you add a path that builds a template, it must
take its quantum from the same resolution, not from a module default.

**Synthetic fixtures must declare their own quantum.** A generated stream
carries no protocol and cannot be asked.

## Behaviour when something is off

Do not silently correct, auto-revert, or guess past a problem. **Say what was
assumed, warn when it looks wrong, and suggest the alternative.** A failed
lock should name the quantum tried, why it was chosen, and what to retry
with. This applies generally: surface the assumption, offer the option, let
the user decide.

## Things that have bitten before

- **`decode_frames` needs a single polarity.** An interleaved both-edges list
  halves every interval and matches no preamble. Try each polarity and keep
  whichever yields more valid frames.
- **Bare `except: pass` hides real failures.** Several existed and cost
  debugging time. Report the error.
- **The generator is usually already running when recording starts.** Two real
  recordings from one run sat 17.9 and 41.1 minutes in. Assuming a recording
  begins at the template's t=0 produces a confident, wholly wrong alignment
  rather than an obvious failure.
- **Offset, drift, jitter, gross errors and outages are separate quantities.**
  Lumping them let one recording report anywhere from 0.5 to 2.6 ms of
  "jitter" depending on how it was sliced. Each has a different cause and a
  different remedy. Keep them apart.
