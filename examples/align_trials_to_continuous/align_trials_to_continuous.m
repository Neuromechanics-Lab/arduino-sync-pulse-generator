%% Aligning epoched trials to a continuous recording — PRE-Sync worked example
%
% Locates short epoched trials (Vicon/Nexus) inside a long continuous
% recording (BrainVision EEG) by fingerprinting the sync square wave both
% systems recorded.
%
% ---------------------------------------------------------------------------
% THE PROBLEM
% ---------------------------------------------------------------------------
% Nexus hands us short epoched trials. The EEG is one long continuous file.
% Nothing in either says where a trial sits inside the EEG. The usual fixes —
% trusting wall clocks, counting trigger markers, matching trial counts — all
% fail quietly the moment anything is dropped, restarted, or started late.
%
% ---------------------------------------------------------------------------
% THE IDEA
% ---------------------------------------------------------------------------
% A box emits a square wave whose HIGH and LOW durations are pseudo-random,
% drawn in 5 ms steps from 50-500 ms. Both systems record that same physical
% signal on an analog channel.
%
% Because the durations are pseudo-random, any short stretch of the wave has
% an interval pattern that occurs nowhere else. A run of six intervals —
% 205, 135, 480, 80, 465, 175 ms — is effectively a fingerprint. Find that
% pattern in the EEG's copy of the wave and you have found exactly where the
% trial sits, to the sample.
%
% That is the whole method. No clocks, no timestamps, no assumptions about
% sample rate, no trigger counting.
%
% ---------------------------------------------------------------------------
% WHAT THIS USES
% ---------------------------------------------------------------------------
% The PRE-Sync MATLAB toolkit, in ../../sync_pulse_generator/utils/matlab:
%
%   DETECT_EDGES  transition times to sub-sample precision. Interpolates
%                 across the threshold rather than taking the nearest sample,
%                 which matters: at 1 kHz a whole-sample edge is a 1 ms
%                 quantisation. It also has a 'rectified' mode for a channel
%                 that went through an EMG amplifier, where the high-pass
%                 turns each step into a spike — not needed here, but that is
%                 the function to reach for if your sync channel looks wrong.
%
%   EDGE_DELAY    pairs two edge lists and reports the delay between them,
%                 respecting polarity (a rising edge is only matched to a
%                 rising edge), requiring the match to be causal, and
%                 flagging outliers. It returns per-polarity agreement and a
%                 drift estimate, which are the checks worth reading.
%
% MIT licensed, as is the rest of this repository. See LICENSE at the root.
%
% ---------------------------------------------------------------------------
% GETTING THE TOOLKIT
% ---------------------------------------------------------------------------
%   git clone https://github.com/Neuromechanics-Lab/arduino-sync-pulse-generator.git
%   cd arduino-sync-pulse-generator
%
% (also mirrored at gitlab.com/neurotrophy-git/arduino-sync-pulse-generator)
%
% Then in MATLAB:
%   addpath('sync_pulse_generator/utils/matlab')
%
% This script is examples/align_trials_to_continuous/, so it finds the toolkit
% relative to itself — run it from anywhere in the clone.
%
% Equivalents exist in Python (sync_pulse_generator/utils/python) and R. The
% align/lock functions carry the same names across all three.
%
% ---------------------------------------------------------------------------
% ADAPTING IT TO YOUR DATA
% ---------------------------------------------------------------------------
% Edit the config block below: point DATA at your files, list your trial
% tables and the continuous file each belongs to in JOBS, and set SYNC_NAME to
% whatever your sync channel is called. The script discovers the trial table's
% column names rather than assuming them.
%
% The paths here point at one Emory dataset that is NOT in this repository —
% it is participant data. Substitute your own.
%
% ---------------------------------------------------------------------------
% TWO THINGS THAT VARY BETWEEN DATASETS
% ---------------------------------------------------------------------------
% 1. COLUMN NAMES. This script discovers them (any column matching 'square'
%    and 'atime') rather than hardcoding, because they are not stable: in this
%    dataset fitsData1 and fitsData2 use Square_Wave_1 / atime_1 while
%    fitsData3 uses Square_Wave_2 / atime_2 — the suffix is the PERTURBATION
%    number, not the table number. The dangerous case is not an error, it is a
%    table where the name you assumed exists but holds a different
%    perturbation: the script then aligns confidently to the wrong event. If
%    your tables name things differently again, widen the search patterns
%    below, and check the reported column names in the output.
%
% 2. HOW THE SQUARE WAVE WAS RECORDED. This script assumes a CONTINUOUS
%    ANALOG CHANNEL — the wave plugged into an input and sampled like any
%    other signal (here Ch65 'SquareWave' in the BrainVision file, and the
%    Square_Wave column in the Vicon table).
%
%    Some setups instead feed the wave into a DIGITAL TRIGGER INPUT, so each
%    transition arrives as an EVENT MARKER — in BrainVision, entries in the
%    .vmrk file rather than samples in the .eeg. That still works, and the
%    method is unchanged, but the code path differs:
%
%      - Read the marker positions instead of calling detect_edges. A .vmrk
%        line is 'Mk<n>=<type>,<desc>,<sample>,<size>,<chan>'; the third field
%        is the sample index, so edge times are sample/fs directly.
%      - You get NO sub-sample interpolation. Marker positions are whole
%        samples, so timing is quantised to one sample (1 ms at 1 kHz) rather
%        than the ~0.1 ms this script achieves. Fine for most purposes; worth
%        knowing before quoting a precision.
%      - Markers usually carry ONE polarity — typically rising edges only.
%        detect_edges reports both, so the interval sequence differs by a
%        factor of two between a marker list and a sampled channel. Compare
%        like with like: if one side is rising-only, take the rising edges
%        from the other with select_edges or by filtering on polarity.
%      - Check the marker count before assuming. In this dataset the .vmrk
%        markers are experiment events (S 15 / S 11 pairs, 19 and 49 of them)
%        and NOT the square wave, which has 2195 transitions on Ch65. A
%        handful of markers means events; hundreds or thousands means the
%        wave.
%
% ---------------------------------------------------------------------------
% WHY CLOCK DRIFT DOES NOT MATTER HERE
% ---------------------------------------------------------------------------
% Worth stating, because it is the usual objection. The EEG amplifier's clock
% in this dataset runs about 96 ppm slow — 57 ms of accumulated error over the
% 10-minute file. That sounds fatal and is irrelevant, because we never use
% either system's clock to place a trial. Both recorded the same physical
% edges; we match the recorded patterns directly. Whatever the clocks did,
% they did to both copies, and the match absorbs it.
%
% (Regenerating the wave from its seed IS useful — for absolute position, for
% relating files that never overlap, and for auditing a recorder against
% ground truth. None of that is needed to answer "where is this trial", so
% this demo does not do it.)
%
% ---------------------------------------------------------------------------
% WHAT COMES OUT
% ---------------------------------------------------------------------------
%   T.eeg_time   per-sample EEG time for every trial sample  [nTrials x 3001]
%   T.eeg_t0     EEG time at which each trial begins         [nTrials x 1]
%
% Nothing is merged and nothing is resampled. Each dataset keeps its own
% samples; the trials gain a column saying where they live in the EEG.
%
% ---------------------------------------------------------------------------
% USING THE OUTPUT
% ---------------------------------------------------------------------------
% The answer is a SAMPLE INDEX, because that is the question: which EEG
% samples correspond to this trial. To pull them:
%
%     s0 = T.eeg_sample0(i);
%     eeg_epoch = eeg_data(:, s0 : s0 + nSamplesInTrial - 1);
%
% No rounding, no unit conversion, no off-by-one to reason about.
%
% The perturbation sits at trial time 0, which is offset into the epoch by
% however much pre-trigger the epoch carries:
%
%     s_pert = s0 + T.eeg_pert_offset(i);
%
% Skip trials that did not locate — eeg_sample0 is NaN for those:
%
%     for i = find(~isnan(T.eeg_sample0))'
%
% eeg_t0_sec is provided for plotting, and it is FILE POSITION, not elapsed
% time. The perception recording was stopped and restarted twice, so the file
% concatenates three segments with roughly 12 and 9 minutes of real time
% missing at the joins. Sample 936501 reads as 936 s into the file and is
% really about 2211 s after recording began. For indexing samples this makes
% no difference at all; for interpreting a number as "seconds since start" it
% makes a large one.
%
% resid_ms is the confidence measure — how far the two recordings disagree
% about the wave once placed. Sub-millisecond means better than one sample.
%
% ---------------------------------------------------------------------------
% RESULT ON THIS DATA
% ---------------------------------------------------------------------------
%   fitsData1  single,      1 pert    17/17   worst residual 0.261 ms
%   fitsData2  perception,  1st pert  47/47   worst residual 0.298 ms
%   fitsData3  perception,  2nd pert  47/47   worst residual 0.301 ms
%
% A consistency check worth showing people: fitsData2 and fitsData3 are the
% two perturbations of the SAME trials, located completely independently with
% no knowledge of each other. Measured across all 47:
%
%     inter-perturbation gap   mean 3.976 s, sd 4.3 ms, full range 18.1 ms
%
% Nothing in the matching enforces that, or even knows the two tables are
% related. Two independent sets of 47 fingerprint searches landing on a
% constant interval is about as good an argument as you get that the
% alignment is real. The 4.3 ms spread is the experiment's own timing
% variability, not ours — our residuals are ten times smaller.

clear; clc; close all;

%% ------------------------------------------------------------------ config
HERE  = fileparts(mfilename('fullpath'));
UTILS = fullfile(HERE, '..', '..', 'sync_pulse_generator', 'utils', 'matlab');
assert(isfolder(UTILS), ['PRE-Sync MATLAB toolkit not found at ' UTILS]);
addpath(UTILS);

% Point this at your own data. Nothing under it is in the repository.
DATA      = fullfile(HERE, '..', '..', 'testdata');
VICON_MAT = fullfile(DATA, 'PD026_OFF_RawDataTable.mat');
SYNC_NAME = 'SquareWave';

% One entry per Vicon table and the EEG file it belongs to. Note that the
% perception condition delivers TWO perturbations per trial, split across two
% tables — and that fitsData3 names its columns Square_Wave_2 / atime_2, not
% _1. The suffix is the perturbation number, so the script DISCOVERS the
% column names rather than assuming them.
JOBS = { ...
  'fitsData1', 'PD026_off_single.eeg',     'single, 1 perturbation'      ; ...
  'fitsData2', 'PD026_off_perception.eeg', 'perception, 1st perturbation'; ...
  'fitsData3', 'PD026_off_perception.eeg', 'perception, 2nd perturbation'};

% The box's own settings, from sync_pulse_simple.ino. Compile-time constants;
% there is no way to configure the box to anything else.
SEED = 42; MIN_MS = 50; MAX_MS = 500; STEP_MS = 5;
BOX_HOURS = 8;   % template span. Must exceed however long the box had been
                 % running when recording started — 4.2 h in this session, and
                 % a 4 h template found nothing, which reads as corrupt data.

K   = 6;    % intervals in the fingerprint. Trials here carry 10-13 edges, so
            % 6 is about the practical maximum. More is safer, if you have
            % the edges to spare.
TOL = 3;    % ms an interval may differ and still count as a match. Absorbs
            % edge-detection noise without being loose enough to false-match.

%% ============================================================= run each job
% ALIGN_TEMPLATE with 'variant','simple' — sync_pulse_simple.ino emits no
% timecode frames, and the default 'full' variant would build a template the
% recordings match nothing in.
fprintf('Regenerating the box''s output (seed %d, %d h, simple variant)\n', ...
        SEED, BOX_HOURS);
box_tmpl = align_template(BOX_HOURS*3600, [], 'variant', 'simple', 'seed', SEED);
fprintf('  %d transitions over %.1f h\n', numel(box_tmpl.time), ...
        box_tmpl.time(end)/3600);

aligned = struct();          % everything that will be saved
summary = {};                % one row per job, for the closing table

for job = 1:size(JOBS, 1)
    TABLE_NAME = JOBS{job,1};
    EEG_FILE   = fullfile(DATA, JOBS{job,2});
    EEG_VHDR   = fullfile(DATA, 'hdr', strrep(JOBS{job,2}, '.eeg', '.vhdr'));

    fprintf('\n===== %s — %s =====\n', TABLE_NAME, JOBS{job,3});

    % ------------------------------------------------ the EEG's copy of the wave
    % Cached: perception's two tables share one 400 MB EEG file, and reading it
    % twice is pure waste.
    persistent_key = JOBS{job,2};
    if ~exist('eeg_cache','var') || ~isfield(eeg_cache,'key') || ...
       ~strcmp(eeg_cache.key, persistent_key)
        hdr = read_bv_header(EEG_VHDR);
        ch  = find(strcmpi(hdr.chan_names, SYNC_NAME), 1);
        assert(~isempty(ch), 'no "%s" channel in %s', SYNC_NAME, EEG_VHDR);

        fid = fopen(EEG_FILE,'r'); raw = fread(fid, Inf, 'single=>double'); fclose(fid);
        n_samp = floor(numel(raw) / hdr.n_chan);
        sync   = raw(ch : hdr.n_chan : n_samp*hdr.n_chan);
        clear raw;

        eeg_cache.key   = persistent_key;
        eeg_cache.hdr   = hdr;
        eeg_cache.sync  = sync;
        eeg_cache.n     = n_samp;
        eeg_cache.time  = (0:n_samp-1)' / hdr.fs;
        eeg_cache.edges = detect_edges(sync, hdr.fs);      % PRE-Sync
        eeg_cache.et    = eeg_cache.edges.time(:);
        eeg_cache.iv    = diff(eeg_cache.et) * 1000;

        eeg_cache.box_t0 = template_locate(eeg_cache.et, box_tmpl, ...
                                'k', K, 'tol_ms', TOL, 'step_ms', STEP_MS);
        fprintf('  EEG %s: %.1f s, %d transitions\n', JOBS{job,2}, ...
                n_samp/hdr.fs, numel(eeg_cache.et));
        if ~isnan(eeg_cache.box_t0)
            fprintf('    sample 1 = box time %.3f s (box had run %.2f h)\n', ...
                    eeg_cache.box_t0, eeg_cache.box_t0/3600);
        else
            fprintf('    did not locate on the box clock — raise BOX_HOURS\n');
        end
    else
        fprintf('  EEG %s: reusing (already read)\n', JOBS{job,2});
    end
    hdr = eeg_cache.hdr; eeg_sync = eeg_cache.sync; eeg_time = eeg_cache.time;
    eeg_et = eeg_cache.et; eeg_iv = eeg_cache.iv; n_samp = eeg_cache.n;
    eeg_edges = eeg_cache.edges;

    % ------------------------------------------------------------- the trials
    S = load(VICON_MAT, TABLE_NAME);
    T = S.(TABLE_NAME);
    n_trials = height(T);

    % Discover the column names. fitsData3 uses Square_Wave_2 / atime_2 — the
    % suffix is the perturbation number, not the table number, so assuming _1
    % silently reads the wrong perturbation or errors outright.
    vn    = T.Properties.VariableNames;
    sq_col = vn{find(contains(lower(vn), 'square'), 1)};
    at_col = vn{find(contains(lower(vn), 'atime'), 1)};
    fprintf('  %s: %d trials, columns %s / %s\n\n', ...
            TABLE_NAME, n_trials, sq_col, at_col);

    % ------------------------------------------------------------- the match
    fprintf('  %-7s %6s %9s %12s %6s %9s\n', ...
            'trial','edges','eegEdge','eeg_sample0','cand','resid(ms)');
    fprintf('  %s\n', repmat('-', 1, 58));

    eeg_t0   = nan(n_trials,1);  resid_ms = nan(n_trials,1);
    n_cand   = zeros(n_trials,1); first_edge = nan(n_trials,1);
    detail_n = nan(n_trials,1);  detail_sd = nan(n_trials,1);
    inverted = false(n_trials,1); box_t0 = nan(n_trials,1);

    for i = 1:n_trials
        v  = T.(sq_col)(i,:)';
        a  = T.(at_col)(i,:)';
        % detect_edges works in sample time; shift onto the trial's own clock.
        te  = detect_edges(v, 1/(a(2)-a(1)));              % PRE-Sync
        vt  = te.time(:) + a(1);
        viv = diff(vt) * 1000;

        if numel(viv) < K
            fprintf('  %-7d %6d   too few edges (need %d intervals)\n', i, numel(vt), K);
            continue;
        end

        % Slide the trial's first K intervals along the EEG's interval list;
        % keep every position where all K agree within TOL.
        pat = viv(1:K); hits = [];
        for j = 1:(numel(eeg_iv) - K + 1)
            if all(abs(eeg_iv(j:j+K-1) - pat) < TOL), hits(end+1) = j; end %#ok<AGROW>
        end
        if isempty(hits)
            fprintf('  %-7d %6d   NO MATCH\n', i, numel(vt));
            continue;
        end

        j0 = hits(1);
        eeg_t0(i)   = eeg_et(j0) - vt(1);
        n_cand(i)   = numel(hits);
        first_edge(i) = j0;

        % Quality, via EDGE_DELAY on EVERY edge — not just the K matched, so
        % this is independent evidence rather than circular.
        %
        % Two things to get right when calling it. First, shift the trial onto
        % EEG time, so a correct placement leaves a delay of ~0. Second, hand
        % it only the EEG edges that OVERLAP the trial: edge_delay pairs every
        % reference edge it is given, and a 10-minute reference against a
        % 3-second test leaves almost everything unpaired.
        % INVERTED CHANNEL. In this dataset the Vicon square wave is inverted
        % relative to the EEG's: where one reads a rising edge the other reads
        % a falling one, at the same instant to within 0.1 ms. Probably a
        % differential input wired the other way round, or an inverting
        % buffer. edge_delay is right to refuse a rising-to-falling pairing,
        % so the fix is to state the inversion, not to loosen the matching.
        %
        % Detected rather than assumed: if the two disagree on polarity at the
        % matched position, flip the trial's.
        % Box time, located INDEPENDENTLY — this trial against the template,
        % with no reference to the EEG or to any other trial. It is what makes
        % trials either side of a recording break correctly separated by real
        % elapsed time, which file position cannot express because nothing was
        % written during the break.
        box_t0(i) = template_locate(vt, box_tmpl, ...
                                'k', K, 'tol_ms', TOL, 'step_ms', STEP_MS);

        te_shift = te;  te_shift.time = vt + eeg_t0(i);
        flip = te.polarity(1) ~= eeg_edges.polarity(j0);
        if flip, te_shift.polarity = -te.polarity; inverted(i) = true; end

        % SELECT_EDGES narrows the reference to the stretch this trial
        % overlaps, carrying .mode and .fs through so edge_delay's quality
        % checks still work. Without it, edge_delay pairs 3 s of test against
        % 10 min of reference and reports "no edges paired".
        ref = select_edges(eeg_edges, te_shift.time(1), te_shift.time(end), ...
                           'pad', 0.05);
        dl = edge_delay(ref, te_shift, 'min_delay', -20, 'max_delay', 20);
        resid_ms(i)  = abs(dl.delay_ms) + dl.delay_std_ms;
        detail_n(i)  = dl.n_matched;
        detail_sd(i) = dl.delay_std_ms;

        if n_trials <= 20 || mod(i,10) == 1 || i == n_trials
            fprintf('  %-7d %6d %9d %12d %6d %9.3f\n', ...
                    i, numel(vt), j0, round(eeg_t0(i)*hdr.fs)+1, ...
                    numel(hits), resid_ms(i));
        end
    end

    ok = ~isnan(eeg_t0);
    if n_trials > 20, fprintf('  ... (%d rows, showing every 10th)\n', n_trials); end
    fprintf('\n  %d of %d located, worst residual %.3f ms\n', ...
            sum(ok), n_trials, max(resid_ms(ok)));
    if any(inverted)
        fprintf(['  NOTE: the trial square wave is INVERTED relative to the ' ...
                 'EEG''s (%d/%d trials).\n        Times agree; only the sign ' ...
                 'differs. Worth knowing about your wiring.\n'], ...
                 sum(inverted), sum(ok));
    end

    uniq = all(n_cand(ok) == 1);
    mono = issorted(eeg_t0(ok));
    if uniq, fprintf('  Every match unique.\n');
    else,    warning('%d trial(s) matched more than one position.', sum(n_cand(ok)>1)); end
    if mono, fprintf('  Trial order preserved.\n');
    else,    warning('Trial times are NOT monotonic — at least one match is wrong.'); end

    % ------------------------------------------------- write the column back
    s0   = nan(n_trials,1);   pert = nan(n_trials,1);
    for i = find(ok)'
        s0(i)   = round(eeg_t0(i) * hdr.fs) + 1;        % EEG sample of trial start
        pert(i) = round(-T.(at_col)(i,1) * hdr.fs);     % offset to trial time 0
    end
    T.eeg_sample0     = s0;      % <- the answer: which EEG sample the trial starts at
    T.eeg_pert_offset = pert;    % add to eeg_sample0 for the perturbation sample
    T.eeg_t0_sec      = eeg_t0;  % file position in seconds, for plotting only
    T.box_time        = box_t0;  % when it happened on the box's clock
    aligned.(TABLE_NAME) = T;

    summary(end+1,:) = {TABLE_NAME, JOBS{job,3}, sum(ok), n_trials, ...
                        max(resid_ms(ok)), uniq, mono}; %#ok<SAGROW>

    % keep the first job's pieces for the explanatory figure
    if job == 1
        fig = struct('T',T,'sq_col',sq_col,'at_col',at_col,'ok',ok, ...
                     'eeg_t0',eeg_t0,'resid_ms',resid_ms,'first_edge',first_edge, ...
                     'eeg_sync',eeg_sync,'eeg_time',eeg_time,'eeg_iv',eeg_iv, ...
                     'edges',eeg_edges,'n_samp',n_samp,'fs',hdr.fs);
    end
end

%% ---------------------------------------------------------------- summary
fprintf('\n\n===== summary =====\n');
fprintf('%-11s %-30s %8s %10s %7s %7s\n', ...
        'table','condition','located','worst(ms)','uniq','order');
fprintf('%s\n', repmat('-', 1, 78));
for r = 1:size(summary,1)
    fprintf('%-11s %-30s %4d/%-3d %10.3f %7s %7s\n', summary{r,1}, summary{r,2}, ...
            summary{r,3}, summary{r,4}, summary{r,5}, ...
            yn(summary{r,6}), yn(summary{r,7}));
end

out = fullfile(DATA, 'PD026_OFF_aligned.mat');
save(out, '-struct', 'aligned', '-v7.3');
fprintf('\nSaved %s\n', out);
fprintf(['  T.eeg_sample0      the answer: which sample of the continuous\n' ...
         '                     file each trial starts at\n' ...
         '  T.eeg_pert_offset  add to eeg_sample0 for the perturbation sample\n' ...
         '  T.box_time         when it happened on the generator''s clock,\n' ...
         '                     which keeps running through recording breaks\n' ...
         '  T.eeg_t0_sec       file position in seconds, for plotting only\n' ...
         '  NaN marks a trial that did not locate.\n']);

%% ------------------------------------------------------------ explain it
plot_explanation(fig, K, SYNC_NAME);

%% ===================================================================== utils

function s = yn(b)
    if b, s = 'yes'; else, s = 'NO'; end
end

function plot_explanation(f, K, sync_name)
% Six panels, each answering a question a sceptical reader should ask.
    figure('Name','How the alignment works','Position',[60 40 1150 820]);
    k = find(f.ok, 1);

    subplot(3,2,1);
    histogram(f.eeg_iv, 20, 'FaceColor',[.35 .35 .35], 'EdgeColor','none');
    xlabel('interval (ms)'); ylabel('count');
    title({'(a) Durations are pseudo-random', ...
           sprintf('%d intervals, 50-500 ms in 5 ms steps', numel(f.eeg_iv))});

    subplot(3,2,2);
    a_k = f.T.(f.at_col)(k,:)';
    te_k = detect_edges(f.T.(f.sq_col)(k,:)', 1/(a_k(2)-a_k(1)));
    vt = te_k.time(:) + a_k(1);
    j0 = f.first_edge(k);
    stem(1:K, diff(vt(1:K+1))*1000, 'filled', 'Color',[.75 .2 .2]); hold on;
    stem(1:K, f.eeg_iv(j0:j0+K-1), 'o', 'Color',[.2 .2 .2]);
    xlabel('interval #'); ylabel('ms'); xlim([0 K+1]);
    legend('trial','EEG at match','Location','best');
    title(sprintf('(b) Trial %d fingerprint vs the EEG where it matched', k));

    subplot(3,2,3);
    % detect_edges returns a time, which lands BETWEEN samples. Showing that
    % is the point of this panel: the red line sits off-grid.
    t_edge = f.edges.time(1);
    s_edge = t_edge * f.fs + 1;                 % fractional sample position
    w  = max(1,floor(s_edge)-3):min(f.n_samp,floor(s_edge)+4);
    plot(w, f.eeg_sync(w), 'ko-', 'MarkerFaceColor','k'); hold on;
    xline(s_edge, 'r', 'LineWidth',1.5);
    xlabel('sample'); ylabel('raw value');
    legend('samples','detect\_edges result','Location','best');
    title({'(c) Edges fall BETWEEN samples', ...
           sprintf('this one at sample %.2f, not %d', s_edge, round(s_edge))});

    subplot(3,2,4);
    a = f.T.(f.at_col)(k,:)';
    w = f.eeg_time >= f.eeg_t0(k)+a(1) & f.eeg_time <= f.eeg_t0(k)+a(end);
    e = f.eeg_sync(w); e = (e-min(e))/(max(e)-min(e));
    plot(f.eeg_time(w)-f.eeg_t0(k), e, 'k', 'LineWidth',1.4); hold on;
    v = f.T.(f.sq_col)(k,:)'; v = (v-min(v))/(max(v)-min(v));
    plot(a, v, 'r--', 'LineWidth',1.4);
    xlabel('trial time (s)'); ylabel('normalised');
    legend('EEG','trial','Location','southeast');
    title(sprintf('(d) Trial %d overlaid at its recovered position', k));

    subplot(3,2,5);
    plot(f.eeg_time, f.eeg_sync, 'Color',[.75 .75 .75]); hold on;
    for i = find(f.ok)', xline(f.eeg_t0(i), 'r'); end
    xlabel('EEG time (s)'); ylabel(sync_name); xlim([0 f.n_samp/f.fs]);
    title(sprintf('(e) All %d trials placed in the EEG', sum(f.ok)));

    subplot(3,2,6);
    bar(find(f.ok), f.resid_ms(f.ok), 'FaceColor',[.2 .4 .6], 'EdgeColor','none');
    xlabel('trial'); ylabel('max residual (ms)');
    ylim([0 max(1, max(f.resid_ms(f.ok))*1.4)]);
    title({'(f) Worst edge disagreement per trial', ...
           'measured on every edge, not just the ones matched'});
end

function hdr = read_bv_header(vhdr_path)
% Minimal BrainVision .vhdr reader: channel names, count, sample rate.
    lines = regexp(fileread(vhdr_path), '\r\n|\n', 'split');
    hdr.n_chan = NaN; hdr.fs = NaN; hdr.chan_names = {};
    for i = 1:numel(lines)
        L = strtrim(lines{i});
        if startsWith(L, 'NumberOfChannels=')
            hdr.n_chan = str2double(extractAfter(L, '='));
        elseif startsWith(L, 'SamplingInterval=')
            hdr.fs = 1e6 / str2double(extractAfter(L, '='));   % us -> Hz
        elseif ~isempty(regexp(L, '^Ch\d+=', 'once'))
            parts = strsplit(extractAfter(L, '='), ',');
            hdr.chan_names{str2double(extractBetween(L,'Ch','='))} = strtrim(parts{1});
        end
    end
    assert(~isnan(hdr.n_chan) && ~isnan(hdr.fs), 'could not parse %s', vhdr_path);
end

%% ================================================================ if it fails
%
% NO MATCH on every trial
%     Check you have the right EEG file for these trials. Then plot the sync
%     channel and confirm it really is the square wave. If the trials come
%     from a different session than the EEG there is nothing to find, and the
%     script is correct to say so.
%
% NO MATCH on some trials
%     Usually a trial whose window clipped the wave, leaving too few clean
%     edges. Look at that trial's Square_Wave row. Lowering K trades certainty
%     for reach; raising TOL trades certainty for tolerance of noisy edges.
%
% A trial reports several candidates
%     The fingerprint was not unique — rare at K=6, but possible in a long
%     recording. Raise K if the trial has edges to spare, and check that trial
%     against panel (d) before trusting it.
%
% Trial times are not monotonic
%     At least one trial matched the wrong place. Nothing in the matching
%     enforces ordering, which is exactly why the check is worth making.
%
% Residuals of several ms rather than a fraction
%     The two systems disagree about the SHAPE of the wave, not just its
%     position. Suspect a channel that went through an amplifier or filter
%     that is not simply recording the level — an EMG input, for instance,
%     turns each step into a spike.
