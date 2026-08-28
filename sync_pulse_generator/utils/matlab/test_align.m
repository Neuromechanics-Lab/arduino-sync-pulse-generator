function test_align()
% TEST_ALIGN Self-tests for the MATLAB aligner. Run: test_align
%
% Mirrors utils/python/test_align.py. Each case is one that broke an earlier
% implementation, so a regression shows up as a failure rather than a
% plausible-looking wrong number.

    fprintf('\ntest_align\n');
    total = 0; failed = 0;
    tests = {@t_generator_matches_reference, @t_offset_only, ...
             @t_edge_only_polarities, @t_clock_drift, ...
             @t_lost_count_step, @t_end_to_end_lags, @t_antialias};
    for k = 1:numel(tests)
        total = total + 1;
        try
            tests{k}();
        catch err
            failed = failed + 1;
            fprintf('FAIL %s: %s\n', func2str(tests{k}), err.message);
        end
    end
    fprintf('\n%d/%d passed\n\n', total - failed, total);
end


function t_generator_matches_reference()
% The template generator is the foundation: if it drifts from the firmware
% (or from the Python reference) every alignment silently degrades.
    [tm, lv] = generate_sync_signal_tc(60, 137);
    assert(abs(tm(1)) < 1e-9, 'first toggle must be at t=0');
    assert(lv(1) == 1, 'first toggle is LOW->HIGH');
    d = diff(tm);
    assert(all(d >= 0), 'edge times must be non-decreasing');
    assert(~any(d == 0), 'zero-width pulses are not emittable by the firmware');
    % Frames land ON the tick.
    assert(any(abs(tm - 10000) < 1e-6), 'a frame should start at 10 s');
    fprintf('ok   generator: t=0 start, no zero-width pulses, frames on the tick\n');
end


function t_offset_only()
    rng(1);
    tmpl = align_template(300, 137);
    w = tmpl.time > 20 & tmpl.time < 140;
    e = tmpl.time(w) - 20 + 0.0008*randn(sum(w),1);
    f = align_lock(source_from_edges('a', e, tmpl.polarity(w)), tmpl, 0.006);
    assert(f.ok, f.note);
    assert(abs(f.offset_s - 20) < 0.01, sprintf('offset %.4f', f.offset_s));
    assert(f.match_rate > 0.98, sprintf('matched %.2f', f.match_rate));
    assert(isequal(f.run_id, 137), 'run id should come from the frames');
    fprintf('ok   pure offset recovered, run id read from the signal\n');
end


function t_edge_only_polarities()
% The headline case: a device that reports only one edge polarity.
    rng(2);
    tmpl = align_template(300, 137);
    w = tmpl.time > 20 & tmpl.time < 140;
    for spec = {{'rising', tmpl.polarity > 0}, {'falling', tmpl.polarity < 0}}
        sel = w & spec{1}{2};
        e = tmpl.time(sel) - 20 + 0.0008*randn(sum(sel),1);
        f = align_lock(source_from_edges('x', e, spec{1}{1}), tmpl, 0.006);
        assert(f.ok, sprintf('%s: %s', spec{1}{1}, f.note));
        assert(abs(f.offset_s - 20) < 0.01, ...
               sprintf('%s offset %.4f', spec{1}{1}, f.offset_s));
        assert(f.match_rate > 0.98, sprintf('%s matched %.2f', ...
               spec{1}{1}, f.match_rate));
    end
    fprintf('ok   rising-only and falling-only both lock\n');
end


function t_clock_drift()
% 300 ppm moves alignment ~57 ms over three minutes, far outside any fixed
% pairing window - which is what broke the first implementation.
    rng(3);
    tmpl = align_template(400, 137);
    w = tmpl.time > 15 & tmpl.time < 215;
    e = (tmpl.time(w) - 15) / 1.0003 + 0.0008*randn(sum(w),1);
    f = align_lock(source_from_edges('d', e, tmpl.polarity(w)), tmpl, 0.006);
    assert(f.ok, f.note);
    assert(abs(f.offset_s - 15) < 0.02, sprintf('offset %.4f', f.offset_s));
    assert(f.drift_ppm > 250 && f.drift_ppm < 350, ...
           sprintf('drift %.0f ppm', f.drift_ppm));
    fprintf('ok   300 ppm clock drift recovered\n');
end


function t_lost_count_step()
% A counter-based recorder that loses 250 ms labels everything after it
% early. That IS a step and must split the time map.
    rng(4);
    tmpl = align_template(400, 137);
    w = tmpl.time > 5 & tmpl.time < 180;
    base = tmpl.time(w) - 5; pol = tmpl.polarity(w);
    alive = base < 55 | base > 55.25;
    tt = base(alive); pp = pol(alive);
    loc = tt; loc(tt > 55) = loc(tt > 55) - 0.25;
    f = align_lock(source_from_edges('e', loc + 0.0008*randn(size(loc)), pp), ...
                   tmpl, 0.006);
    assert(f.ok, f.note);
    assert(size(f.segments,1) == 2, ...
           sprintf('expected 2 segments, got %d', size(f.segments,1)));
    assert(size(f.drops,1) >= 1, 'expected a drop');
    step = f.drops(1,2);
    assert(step > 240 && step < 260, sprintf('step %.1f ms', step));
    fprintf('ok   lost-count step split into segments\n');
end


function t_end_to_end_lags()
    rng(5);
    tmpl = align_template(400, 137);
    T = tmpl.time;
    build = @(st,fs,dur) mod(arrayfun(@(x) sum(T<=x), ...
                             st + (0:round(dur*fs)-1)'/fs), 2);
    s1 = source_from_continuous('vicon', build(12,1000,100)+0.01*randn(100000,1), 1000);
    s2 = source_from_continuous('daq',   build(40,2000, 60)+0.01*randn(120000,1), 2000);
    r = align_sources([s1 s2], 'mode', 'lags');
    assert(all([r.fits.ok]), 'both sources should lock');
    lag = r.fits(2).offset_s - r.fits(1).offset_s;
    assert(abs(lag - 28) < 0.01, sprintf('lag %.4f, want 28', lag));
    fprintf('ok   end-to-end lag across 1000/2000 Hz sources\n');
end


function t_antialias()
% Downsampling without a low-pass is silent corruption: a 230 Hz tone taken
% from 2000 Hz to 100 Hz reappears at full amplitude disguised as 30 Hz.
    fs_hi = 2000; fs_lo = 100;
    t = (0:round(6*fs_hi)-1)'/fs_hi;
    dst = (0:round(6*fs_lo)-1)'/fs_lo;
    for f0 = [10 30]
        v = sin(2*pi*f0*t);
        out = align_resample(t, v, dst, 'linear', [], fs_lo, fs_hi);
        assert(max(abs(out(isfinite(out)))) > 0.7, ...
               sprintf('%g Hz should survive', f0));
    end
    for f0 = [70 130 230 430]
        v = sin(2*pi*f0*t);
        out = align_resample(t, v, dst, 'linear', [], fs_lo, fs_hi);
        assert(max(abs(out(isfinite(out)))) < 0.15, ...
               sprintf('%g Hz should be suppressed', f0));
    end
    fprintf('ok   decimation is anti-aliased\n');
end
