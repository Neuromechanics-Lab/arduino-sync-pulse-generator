function fig = plot_sync_check(rec, report, varargin)
% PLOT_SYNC_CHECK Visual QC of sync channels and EMG in one figure.
%
%   plot_sync_check(rec)                  % auto-detect sync channels
%   plot_sync_check(rec, report)          % reuse a sync_report result
%   plot_sync_check(rec, report, 'emg', {'Sol','TA'})
%
%   Four panels answering the questions worth asking before trusting a run:
%
%     1. Sync overlay      Both square-wave channels over a short window,
%                          normalised so they can share an axis, with the
%                          detected edges marked. Confirms the detector
%                          found the transitions a human would.
%     2. Delay over time   Every matched edge's delay against trial time,
%                          split by polarity. A flat band means a fixed
%                          latency; a slope means clock drift; scatter
%                          means detection trouble.
%     3. Delay histogram   The distribution, with the median marked.
%     4. EMG panels        Raw and envelope per muscle channel.
%
%   Name-Value:
%       'emg'      - Channel patterns to plot, {} for none, 'auto' for all
%                    non-sync voltage channels (default 'auto')
%       'window'   - [start stop] seconds for panel 1 (default first 3 s)
%       'max_emg'  - Cap on EMG panels drawn (default 8)
%       'process'  - true to run process_emg for envelopes (default true)
%
%   Returns the figure handle.
%
%   See also SYNC_REPORT, PROCESS_EMG, DETECT_EDGES.

    p = inputParser;
    addParameter(p, 'emg',     'auto');
    addParameter(p, 'window',  []);
    addParameter(p, 'max_emg', 8);
    addParameter(p, 'process', true);
    parse(p, varargin{:});
    o = p.Results;

    if nargin < 2 || isempty(report)
        report = sync_report(rec, 'verbose', false);
    end

    t = (0:size(rec.data,1)-1)' / rec.fs;

    if isempty(o.window)
        win = [0, min(3, t(end))];
    else
        win = o.window;
    end
    wmask = t >= win(1) & t <= win(2);

    % --- Work out which EMG channels to draw --------------------------------
    emg_idx = local_emg_channels(rec, report, o);
    n_emg   = min(numel(emg_idx), o.max_emg);

    n_rows = 3 + n_emg;
    fig = figure('Name', 'Sync check', 'Color', 'w', ...
                 'Position', [100 100 1000 180 + 130*n_rows]);

    % ---------------------------------------------------------------- panel 1
    ax1 = subplot(n_rows, 1, 1);
    hold(ax1, 'on');
    cols = lines(numel(report.all_indices));
    for k = 1:numel(report.all_indices)
        x = rec.data(wmask, report.all_indices(k));
        x = local_norm(x);
        plot(ax1, t(wmask), x + (k-1)*1.3, 'Color', cols(k,:), 'LineWidth', 1);

        e = report.edges{k};
        in = e.time >= win(1) & e.time <= win(2);
        et = e.time(in);
        ep = e.polarity(in);
        if ~isempty(et)
            plot(ax1, et(ep > 0), (k-1)*1.3 + 1.05*ones(sum(ep>0),1), ...
                 '^', 'Color', cols(k,:), 'MarkerSize', 4, 'MarkerFaceColor', cols(k,:));
            plot(ax1, et(ep < 0), (k-1)*1.3 - 0.05*ones(sum(ep<0),1), ...
                 'v', 'Color', cols(k,:), 'MarkerSize', 4, 'MarkerFaceColor', cols(k,:));
        end
    end
    hold(ax1, 'off');
    xlim(ax1, win);
    ylabel(ax1, 'normalised');
    title(ax1, sprintf('Sync channels with detected edges (%.0f-%.0f s)', win(1), win(2)));
    legend(ax1, local_legend(report), 'Location', 'eastoutside', 'Box', 'off');
    grid(ax1, 'on');

    % ---------------------------------------------------------------- panel 2
    ax2 = subplot(n_rows, 1, 2);
    hold(ax2, 'on');
    for k = 1:numel(report.results)
        r = report.results{k};
        up = r.polarities > 0;
        plot(ax2, r.times(up),  r.deltas_ms(up),  '^', 'MarkerSize', 4, ...
             'Color', cols(k+1,:), 'MarkerFaceColor', cols(k+1,:));
        plot(ax2, r.times(~up), r.deltas_ms(~up), 'v', 'MarkerSize', 4, ...
             'Color', cols(k+1,:));
        yline_local(ax2, r.delay_ms, cols(k+1,:));
    end
    hold(ax2, 'off');
    xlabel(ax2, 'trial time (s)');
    ylabel(ax2, 'delay (ms)');
    title(ax2, 'Per-edge delay over the trial (triangle up = rising, down = falling)');
    grid(ax2, 'on');

    % ---------------------------------------------------------------- panel 3
    ax3 = subplot(n_rows, 1, 3);
    hold(ax3, 'on');
    for k = 1:numel(report.results)
        r = report.results{k};
        nb = max(10, min(60, round(numel(r.deltas_ms)/4)));
        histogram(ax3, r.deltas_ms, nb, 'FaceColor', cols(k+1,:), ...
                  'EdgeColor', 'none', 'FaceAlpha', 0.7);
        yline_local(ax3, [], []);   % no-op keeps the helper symmetrical
        xline_local(ax3, r.delay_ms, cols(k+1,:));
    end
    hold(ax3, 'off');
    xlabel(ax3, 'delay (ms)');
    ylabel(ax3, 'count');
    if ~isempty(report.results)
        r1 = report.results{1};
        title(ax3, sprintf(['Delay distribution - median %.3f ms, sd %.3f ms, ', ...
                            'n = %d'], r1.delay_ms, r1.delay_std_ms, r1.n_matched));
    else
        title(ax3, 'Delay distribution');
    end
    grid(ax3, 'on');

    % ---------------------------------------------------------------- EMG
    for k = 1:n_emg
        ax = subplot(n_rows, 1, 3 + k);
        ch = emg_idx(k);
        x  = rec.data(:, ch);

        hold(ax, 'on');
        plot(ax, t, x, 'Color', [0.7 0.7 0.75], 'LineWidth', 0.4);

        note = '';
        if o.process
            try
                pr = process_emg(x, rec.fs);
                plot(ax, t, pr.envelope, 'Color', [0.85 0.2 0.2], 'LineWidth', 1.2);
                if ~isempty(pr.warnings)
                    note = [' - ' pr.warnings{1}];
                end
            catch err
                note = [' - processing failed: ' err.message];
            end
        end
        hold(ax, 'off');

        ylabel(ax, local_unit(rec, ch));
        title(ax, [local_clean(rec.labels{ch}) note], 'Interpreter', 'none');
        grid(ax, 'on');
        if k == n_emg
            xlabel(ax, 'time (s)');
        end
    end
end


% =========================================================================
function idx = local_emg_channels(rec, report, o)
    if isequal(o.emg, {}) || isempty(o.emg)
        idx = [];
        return;
    end

    if ischar(o.emg) && strcmpi(o.emg, 'auto')
        labs = lower(rec.labels);
        is_v = contains(labs, 'voltage') | ~contains(labs, '.');
        is_sync = false(size(labs));
        is_sync(report.all_indices) = true;
        is_force = contains(labs, 'force') | contains(labs, 'moment');
        cand = find(is_v & ~is_sync & ~is_force);

        % Skip channels that carry nothing worth plotting.
        keep = false(size(cand));
        for k = 1:numel(cand)
            x = rec.data(:, cand(k));
            keep(k) = std(x) > 10*eps;
        end
        idx = cand(keep);
    else
        spec = o.emg;
        if ~iscell(spec), spec = {spec}; end
        idx = [];
        for k = 1:numel(spec)
            hit = find_channel(rec, spec{k});
            idx = [idx, hit(:)']; %#ok<AGROW>
        end
        idx = unique(idx, 'stable');
    end
end


function y = local_norm(x)
    x = double(x);
    lo = min(x); hi = max(x);
    if hi > lo
        y = (x - lo) / (hi - lo);
    else
        y = zeros(size(x));
    end
end


function s = local_legend(report)
    s = cell(1, numel(report.all_indices));
    s{1} = [local_clean(report.reference) ' (ref)'];
    for k = 1:numel(report.channels)
        s{k+1} = sprintf('%s (%+.2f ms)', local_clean(report.channels{k}), ...
                         report.delays_ms(k));
    end
end


function s = local_clean(s)
% Drop the Vicon device prefix for readability.
    d = strfind(s, '.');
    if ~isempty(d)
        s = s(d(end)+1:end);
    end
end


function u = local_unit(rec, ch)
    u = '';
    if isfield(rec, 'units') && numel(rec.units) >= ch
        u = rec.units{ch};
    end
    if isempty(u)
        u = 'a.u.';
    end
end


function yline_local(ax, v, c)
% yline is not in older MATLAB; draw the line by hand.
    if isempty(v), return; end
    xl = xlim(ax);
    plot(ax, xl, [v v], '--', 'Color', c, 'LineWidth', 1);
end


function xline_local(ax, v, c)
    if isempty(v), return; end
    yl = ylim(ax);
    plot(ax, [v v], yl, '--', 'Color', c, 'LineWidth', 1.5);
end
