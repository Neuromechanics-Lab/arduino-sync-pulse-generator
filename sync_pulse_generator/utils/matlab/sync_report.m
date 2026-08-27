function report = sync_report(rec, varargin)
% SYNC_REPORT Measure delays between every sync channel in a recording.
%
%   report = sync_report(rec)
%   report = sync_report(rec, 'channels', {'SquareDirect','SquareWirelessEmg'})
%   report = sync_report(rec, 'reference', 'SquareDirect')
%
%   The one-call entry point for the common question: given a recording that
%   carries the same square wave on two or more channels, how far apart are
%   they? Handles any number of sync channels, not just two.
%
%   With no 'channels' argument it finds them automatically: any channel
%   whose label contains 'square' or 'sync'. The reference defaults to the
%   first one found, or to the channel that looks like a direct recording
%   (the cleanest two-level signal), whichever 'reference' selects.
%
%   Every non-reference channel is compared against the reference, so N sync
%   channels produce N-1 delays, all on a common baseline.
%
%   Name-Value:
%       'channels'  - Cell array of name patterns or numeric indices.
%                     Default: auto-detect from labels.
%       'reference' - Name pattern or index of the reference channel.
%                     Default: the first detected channel.
%       'max_delay' - Widest delay to consider, ms (default 100)
%       'verbose'   - Print a summary table (default true)
%
%   Output struct:
%       .reference       - Label of the reference channel
%       .channels        - Labels compared, in order
%       .delays_ms       - Median delay of each against the reference
%       .results         - Cell array of full EDGE_DELAY structs
%       .edges           - Cell array of DETECT_EDGES structs, reference first
%       .pairwise_ms     - Full matrix of delays between every pair
%       .warnings        - Everything the individual comparisons flagged
%
%   Example:
%       rec = load_c3d_analog('SquareWaveTest01.c3d');
%       r   = sync_report(rec);
%       fprintf('wireless lags by %.2f ms\n', r.delays_ms(1));
%
%   See also DETECT_EDGES, EDGE_DELAY, SHIFT_TIMESTAMPS, PLOT_SYNC_CHECK.

    p = inputParser;
    addParameter(p, 'channels',  {});
    addParameter(p, 'reference', []);
    addParameter(p, 'max_delay', 100);
    addParameter(p, 'verbose',   true);
    parse(p, varargin{:});
    o = p.Results;

    % --- Resolve which channels to use -------------------------------------
    if isempty(o.channels)
        idx = local_autodetect(rec);
        if numel(idx) < 2
            error('sync_report:tooFewChannels', ...
                  ['Found %d sync channel(s) automatically. Name them ', ...
                   'explicitly with the ''channels'' option. Labels present: %s'], ...
                  numel(idx), strjoin(rec.labels, ', '));
        end
    else
        idx = local_resolve(rec, o.channels);
    end

    % --- Resolve the reference ---------------------------------------------
    if isempty(o.reference)
        ref_pos = 1;
    else
        ref_idx = local_resolve(rec, {o.reference});
        ref_pos = find(idx == ref_idx(1), 1);
        if isempty(ref_pos)
            idx = [ref_idx(1), idx(:)'];
            ref_pos = 1;
        end
    end
    ref_ch = idx(ref_pos);
    others = idx(idx ~= ref_ch);

    % --- Detect edges on every channel --------------------------------------
    all_idx  = [ref_ch, others];
    edges    = cell(1, numel(all_idx));
    for k = 1:numel(all_idx)
        edges{k} = detect_edges(rec.data(:, all_idx(k)), rec.fs);
    end

    % --- Compare each against the reference ----------------------------------
    n_cmp   = numel(others);
    results = cell(1, n_cmp);
    delays  = zeros(1, n_cmp);
    warns   = {};

    for k = 1:n_cmp
        r = edge_delay(edges{1}, edges{k+1}, 'max_delay', o.max_delay);
        results{k} = r;
        delays(k)  = r.delay_ms;
        for w = 1:numel(r.warnings)
            warns{end+1} = sprintf('[%s] %s', rec.labels{others(k)}, r.warnings{w}); %#ok<AGROW>
        end
    end

    % --- Full pairwise matrix -------------------------------------------------
    n_all = numel(all_idx);
    M = nan(n_all, n_all);
    for a = 1:n_all
        M(a, a) = 0;
        for b = a+1:n_all
            try
                rab = edge_delay(edges{a}, edges{b}, 'max_delay', o.max_delay);
                M(a, b) =  rab.delay_ms;
                M(b, a) = -rab.delay_ms;
            catch
                % Leave NaN when a pair cannot be matched at all.
            end
        end
    end

    report.reference   = rec.labels{ref_ch};
    report.ref_index   = ref_ch;
    report.channels    = rec.labels(others);
    report.ch_indices  = others;
    report.all_indices = all_idx;
    report.delays_ms   = delays;
    report.results     = results;
    report.edges       = edges;
    report.pairwise_ms = M;
    report.pairwise_labels = rec.labels(all_idx);
    report.warnings    = warns;

    if o.verbose
        local_print(report, rec);
    end
end


% =========================================================================
function idx = local_autodetect(rec)
% Channels whose label mentions a square wave or a sync signal.
    labs = lower(rec.labels);
    hit  = contains(labs, 'square') | contains(labs, 'sync') | contains(labs, 'trig');
    idx  = find(hit);

    % Keep only channels that actually carry transitions, so an unplugged
    % channel with a promising name does not derail the comparison.
    keep = false(size(idx));
    for k = 1:numel(idx)
        x = rec.data(:, idx(k));
        if std(x) > 0
            e = detect_edges(x, rec.fs);
            keep(k) = numel(e.time) >= 4;
        end
    end
    idx = idx(keep);
end


function idx = local_resolve(rec, spec)
% Accept names, patterns, or numeric indices in one list.
    if isnumeric(spec)
        idx = spec(:)';
        return;
    end
    idx = zeros(1, numel(spec));
    for k = 1:numel(spec)
        s = spec{k};
        if isnumeric(s)
            idx(k) = s;
        else
            hit = find_channel(rec, s);
            if isempty(hit)
                error('sync_report:noChannel', ...
                      'No channel matching "%s". Available: %s', ...
                      s, strjoin(rec.labels, ', '));
            end
            idx(k) = hit(1);
        end
    end
end


function local_print(r, rec)
    fprintf('\n');
    fprintf('Sync delay report - %s\n', local_short(rec));
    fprintf('%s\n', repmat('-', 1, 68));
    fprintf('Reference: %s\n', r.reference);
    fprintf('Sample rate: %g Hz   Duration: %.1f s\n\n', rec.fs, ...
            size(rec.data,1)/rec.fs);

    fprintf('%-28s %10s %8s %8s %7s\n', 'Channel', 'delay(ms)', 'sd', 'IQR', 'n');
    for k = 1:numel(r.channels)
        res = r.results{k};
        fprintf('%-28s %10.3f %8.3f %8.3f %7d\n', ...
                local_trim(r.channels{k}, 28), res.delay_ms, ...
                res.delay_std_ms, res.delay_iqr_ms, res.n_matched);
    end

    fprintf('\n');
    for k = 1:numel(r.channels)
        res = r.results{k};
        fprintf('%s\n', local_trim(r.channels{k}, 60));
        fprintf('   median %.3f ms   mean %.3f +/- %.3f ms (95%% CI)\n', ...
                res.delay_ms, res.delay_mean_ms, res.ci95_ms);
        fprintf('   rising %.3f ms   falling %.3f ms   (agreement %.3f ms)\n', ...
                res.rising.median_ms, res.falling.median_ms, ...
                abs(res.rising.median_ms - res.falling.median_ms));
        fprintf('   matched %d/%d edges   drift %.3f ms over the trial\n', ...
                res.n_matched, res.n_reference, res.drift_total_ms);
    end

    if ~isempty(r.warnings)
        fprintf('\nWarnings:\n');
        for k = 1:numel(r.warnings)
            fprintf('  - %s\n', r.warnings{k});
        end
    else
        fprintf('\nNo quality warnings.\n');
    end
    fprintf('\n');
end


function s = local_short(rec)
    if isfield(rec, 'filename') && ~isempty(rec.filename)
        [~, n, e] = fileparts(rec.filename);
        s = [n e];
    else
        s = 'recording';
    end
end


function s = local_trim(s, n)
    if numel(s) > n
        s = ['...' s(end-n+4:end)];
    end
end
