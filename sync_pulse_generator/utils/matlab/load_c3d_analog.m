function rec = load_c3d_analog(filename)
% LOAD_C3D_ANALOG Read analog (EMG / force / sync) channels from a C3D file.
%
%   rec = load_c3d_analog('SquareWaveTest01.c3d')
%
%   Reads the analog section of a C3D file with no external toolbox. Handles
%   the Intel/DEC/MIPS processor variants and both integer and float storage.
%   Marker (point) data is ignored - this reader exists for analog channels.
%
%   Also accepts a CSV exported from Nexus (Export ASCII), detected by
%   extension, so either export route works with the same downstream code.
%
%   Output struct:
%       .filename  - Source path
%       .fs        - Analog sample rate (Hz), read from the file
%       .labels    - 1xN cell of channel names, as stored
%       .units     - 1xN cell of unit strings
%       .data      - Samples x N matrix, scaled to physical units
%       .n_samples - Number of analog samples
%       .duration  - Trial length in seconds
%       .time      - Column vector of timestamps (seconds, starts at 0)
%
%   Channel names from Vicon Nexus carry a "Voltage." / "Force." prefix and a
%   pin number, e.g. 'Voltage.2-SquareDirect'. Use find_channel to look one up
%   without having to spell the prefix.
%
%   See also FIND_CHANNEL, DETECT_EDGES, EDGE_DELAY, PROCESS_EMG.

    if nargin < 1 || isempty(filename)
        error('load_c3d_analog:noFile', 'Provide a path to a .c3d or .csv file.');
    end
    if exist(filename, 'file') ~= 2
        error('load_c3d_analog:notFound', 'File not found: %s', filename);
    end

    [~, ~, ext] = fileparts(filename);
    if strcmpi(ext, '.csv') || strcmpi(ext, '.txt')
        rec = local_load_csv(filename);
    else
        rec = local_load_c3d(filename);
    end

    rec.filename  = filename;
    rec.n_samples = size(rec.data, 1);
    rec.duration  = rec.n_samples / rec.fs;
    rec.time      = (0:rec.n_samples-1)' / rec.fs;
end


% =========================================================================
function rec = local_load_c3d(filename)
% Parse the C3D header and parameter blocks, then the analog data block.

    fid = fopen(filename, 'r', 'ieee-le');
    if fid < 0
        error('load_c3d_analog:openFailed', 'Could not open %s', filename);
    end
    cleanup = onCleanup(@() fclose(fid));

    % --- Header block (block 1) ------------------------------------------
    param_block = fread(fid, 1, 'uint8');
    key         = fread(fid, 1, 'uint8');
    if key ~= 80
        error('load_c3d_analog:notC3D', ...
              '%s is not a C3D file (header key %d, expected 80).', filename, key);
    end

    % The processor type lives in the parameter section, not the header, and
    % it determines the float format. Read it before trusting any real value.
    proc = local_processor_type(fid, param_block);
    if proc == 2      % DEC (VAX) floats need bit surgery; rare but real
        warning('load_c3d_analog:decFloats', ...
                'DEC float format detected - values are converted, verify results.');
    elseif proc == 3  % MIPS is big-endian
        fclose(fid);
        fid = fopen(filename, 'r', 'ieee-be');
        cleanup = onCleanup(@() fclose(fid)); %#ok<NASGU>
    end

    fseek(fid, 2, 'bof');
    n_points        = fread(fid, 1, 'uint16');  %#ok<NASGU> markers, unused here
    analog_per_frame = fread(fid, 1, 'uint16'); % analog VALUES per video frame
    first_frame     = fread(fid, 1, 'uint16');
    last_frame      = fread(fid, 1, 'uint16');
    fseek(fid, 16, 'bof');
    data_block      = fread(fid, 1, 'uint16');  % first block of the data section
    analog_subframes = fread(fid, 1, 'uint16'); % analog samples per video frame
    video_rate      = local_read_real(fid, proc);

    if analog_subframes == 0 || analog_per_frame == 0
        error('load_c3d_analog:noAnalog', ...
              '%s contains no analog channels.', filename);
    end

    n_frames   = last_frame - first_frame + 1;
    n_channels = analog_per_frame / analog_subframes;
    if mod(n_channels, 1) ~= 0
        error('load_c3d_analog:badHeader', ...
              'Analog channel count is not an integer (%g).', n_channels);
    end

    % --- Parameter section ------------------------------------------------
    P = local_read_parameters(fid, param_block, proc);

    fs = local_param_scalar(P, 'ANALOG', 'RATE', video_rate * analog_subframes);
    if fs <= 0
        fs = video_rate * analog_subframes;
    end

    used = local_param_scalar(P, 'ANALOG', 'USED', n_channels);
    if used > 0 && used <= n_channels
        n_channels_used = used;
    else
        n_channels_used = n_channels;
    end

    labels = local_param_strings(P, 'ANALOG', 'LABELS', n_channels);
    units  = local_param_strings(P, 'ANALOG', 'UNITS',  n_channels);

    scale     = local_param_vector(P, 'ANALOG', 'SCALE',  ones(1, n_channels));
    offset    = local_param_vector(P, 'ANALOG', 'OFFSET', zeros(1, n_channels));
    gen_scale = local_param_scalar(P, 'ANALOG', 'GEN_SCALE', 1);

    scale  = local_fit_vector(scale,  n_channels, 1);
    offset = local_fit_vector(offset, n_channels, 0);

    % --- Data section -----------------------------------------------------
    % Point scale sign tells us the storage format: negative means the file
    % holds floats, positive means scaled 16-bit integers.
    fseek(fid, 12, 'bof');
    point_scale = local_read_real(fid, proc);
    is_float    = point_scale < 0;

    % Analog values are interleaved with point data frame by frame. With no
    % markers (the usual case for an analog-only export) the analog block is
    % contiguous, which is the fast path.
    fseek(fid, (data_block - 1) * 512, 'bof');
    n_total = n_frames * analog_subframes * n_channels;

    if n_points == 0
        if is_float
            raw = fread(fid, n_total, 'float32');
        else
            raw = fread(fid, n_total, 'int16');
        end
        if numel(raw) < n_total
            error('load_c3d_analog:truncated', ...
                  'File ended early: expected %d analog values, read %d.', ...
                  n_total, numel(raw));
        end
        raw = reshape(raw, n_channels, [])';
    else
        % Mixed marker + analog: walk frame by frame, skipping point data.
        raw = zeros(n_frames * analog_subframes, n_channels);
        row = 1;
        for f = 1:n_frames
            if is_float
                fread(fid, n_points * 4, 'float32');
                chunk = fread(fid, analog_subframes * n_channels, 'float32');
            else
                fread(fid, n_points * 4, 'int16');
                chunk = fread(fid, analog_subframes * n_channels, 'int16');
            end
            if numel(chunk) < analog_subframes * n_channels
                error('load_c3d_analog:truncated', ...
                      'File ended early at frame %d of %d.', f, n_frames);
            end
            raw(row:row+analog_subframes-1, :) = reshape(chunk, n_channels, [])';
            row = row + analog_subframes;
        end
    end

    % Apply scaling. Float files are already in physical units unless the
    % parameters say otherwise; integer files always need the full transform.
    if is_float
        data = raw;
        if any(scale ~= 1) || any(offset ~= 0)
            data = (data - offset) .* scale * gen_scale;
        end
    else
        data = (raw - offset) .* scale * gen_scale;
    end

    % Trim to the channels the file says are actually in use.
    data   = data(:, 1:n_channels_used);
    labels = labels(1:min(n_channels_used, numel(labels)));
    units  = units(1:min(n_channels_used, numel(units)));

    rec.fs     = fs;
    rec.labels = labels;
    rec.units  = units;
    rec.data   = data;
end


% =========================================================================
function proc = local_processor_type(fid, param_block)
% Byte 4 of the parameter section header encodes the processor: 84=Intel,
% 85=DEC, 86=MIPS. Default to Intel if the byte is missing or nonsense.

    here = ftell(fid);
    fseek(fid, (param_block - 1) * 512 + 3, 'bof');
    n_param_blocks = fread(fid, 1, 'uint8'); %#ok<NASGU>
    code = fread(fid, 1, 'uint8');
    fseek(fid, here, 'bof');

    switch code
        case 85, proc = 2;   % DEC
        case 86, proc = 3;   % MIPS
        otherwise, proc = 1; % Intel
    end
end


function v = local_read_real(fid, proc)
% Read one 4-byte real, converting from DEC format when needed.
    if proc == 2
        bytes = fread(fid, 4, 'uint8');
        v = local_dec_to_ieee(bytes);
    else
        v = fread(fid, 1, 'float32');
    end
end


function v = local_dec_to_ieee(bytes)
% Convert a DEC (VAX) F-format single to IEEE 754.
    if numel(bytes) < 4 || all(bytes == 0)
        v = 0;
        return;
    end
    b = uint8(bytes(:))';
    % DEC stores word-swapped with an exponent bias 2 greater than IEEE.
    swapped = [b(3) b(4) b(1) b(2)];
    word = double(swapped(4)) * 2^24 + double(swapped(3)) * 2^16 + ...
           double(swapped(2)) * 2^8  + double(swapped(1));
    sign_bit = bitshift(bitand(uint32(word), uint32(hex2dec('80000000'))), -31);
    expo     = bitshift(bitand(uint32(word), uint32(hex2dec('7F800000'))), -23);
    mant     = bitand(uint32(word), uint32(hex2dec('007FFFFF')));
    if expo == 0
        v = 0;
        return;
    end
    v = (1 + double(mant) / 2^23) * 2^(double(expo) - 129);
    if sign_bit, v = -v; end
end


% =========================================================================
function P = local_read_parameters(fid, param_block, proc)
% Walk the linked list of parameter records into a nested struct:
%   P.(GROUPNAME).(PARAMNAME) = struct('type', t, 'dims', d, 'data', raw)

    P = struct();
    groups = struct();   % id -> name

    base = (param_block - 1) * 512;
    fseek(fid, base + 4, 'bof');   % skip the 4-byte section header

    guard = 0;
    while true
        guard = guard + 1;
        if guard > 20000
            warning('load_c3d_analog:paramLoop', ...
                    'Parameter section did not terminate cleanly; stopping.');
            break;
        end

        pos = ftell(fid);
        n_char = fread(fid, 1, 'int8');
        if isempty(n_char) || n_char == 0
            break;
        end
        group_id = fread(fid, 1, 'int8');
        if isempty(group_id)
            break;
        end

        name = fread(fid, abs(n_char), '*char')';
        name = strtrim(name);

        offset_pos = ftell(fid);
        next_offset = fread(fid, 1, 'int16');
        if isempty(next_offset)
            break;
        end

        if group_id < 0
            % Group record: name it so parameters can be filed under it.
            gid = abs(group_id);
            groups.(sprintf('g%d', gid)) = local_valid_name(name);
        else
            % Parameter record: type, dimensions, payload.
            data_type = fread(fid, 1, 'int8');
            n_dims    = fread(fid, 1, 'uint8');
            dims      = double(fread(fid, n_dims, 'uint8'))';
            if isempty(dims), dims = 1; end

            n_elem = prod(dims);
            elem_sz = abs(data_type);
            switch data_type
                case -1, raw = fread(fid, n_elem, '*char')';
                case  1, raw = fread(fid, n_elem, 'int8');
                case  2, raw = fread(fid, n_elem, 'int16');
                case  4
                    if proc == 2
                        raw = zeros(n_elem, 1);
                        for k = 1:n_elem
                            raw(k) = local_dec_to_ieee(fread(fid, 4, 'uint8'));
                        end
                    else
                        raw = fread(fid, n_elem, 'float32');
                    end
                otherwise
                    raw = fread(fid, n_elem * elem_sz, 'uint8');
            end

            gkey = sprintf('g%d', group_id);
            if isfield(groups, gkey)
                gname = groups.(gkey);
            else
                gname = sprintf('GROUP%d', group_id);
            end
            P.(gname).(local_valid_name(name)) = ...
                struct('type', data_type, 'dims', dims, 'data', raw);
        end

        if next_offset == 0
            break;
        end
        fseek(fid, offset_pos + next_offset, 'bof');
        if ftell(fid) <= pos
            break;   % offset pointed backwards; bail rather than spin
        end
    end
end


function name = local_valid_name(raw)
% Parameter names may contain characters that are illegal in struct fields.
    name = upper(strtrim(raw));
    name = regexprep(name, '[^A-Za-z0-9_]', '_');
    if isempty(name) || ~isletter(name(1))
        name = ['P_' name];
    end
end


function v = local_param_scalar(P, group, param, default)
    v = default;
    if isfield(P, group) && isfield(P.(group), param)
        d = P.(group).(param).data;
        if ~isempty(d)
            v = double(d(1));
        end
    end
end


function v = local_param_vector(P, group, param, default)
    v = default;
    if isfield(P, group) && isfield(P.(group), param)
        d = P.(group).(param).data;
        if ~isempty(d)
            v = double(d(:))';
        end
    end
end


function out = local_param_strings(P, group, param, n_expected)
% String parameters are stored as a fixed-width char block: dims = [width n].
    out = cell(1, n_expected);
    for i = 1:n_expected
        out{i} = sprintf('Channel%d', i);
    end
    if ~isfield(P, group) || ~isfield(P.(group), param)
        return;
    end
    rec = P.(group).(param);
    if rec.type ~= -1 || numel(rec.dims) < 2
        return;
    end
    width = rec.dims(1);
    count = rec.dims(2);
    chars = rec.data;
    for i = 1:min(count, n_expected)
        a = (i-1)*width + 1;
        b = min(i*width, numel(chars));
        if a <= numel(chars)
            s = strtrim(chars(a:b));
            if ~isempty(s)
                out{i} = s;
            end
        end
    end
end


function v = local_fit_vector(v, n, fill)
% Pad or trim a per-channel parameter to exactly n entries.
    v = v(:)';
    if numel(v) == 1
        v = repmat(v, 1, n);
    elseif numel(v) < n
        v = [v, repmat(fill, 1, n - numel(v))];
    elseif numel(v) > n
        v = v(1:n);
    end
end


% =========================================================================
function rec = local_load_csv(filename)
% Read a Nexus ASCII export. Nexus writes a "Devices" section preceded by a
% rate line and two header rows; fall back to a plain table if that shape
% is not found.

    lines = local_read_lines(filename, 200);
    dev_idx = find(strcmpi(strtrim(lines), 'Devices'), 1);

    if ~isempty(dev_idx) && dev_idx + 2 <= numel(lines)
        fs = str2double(strtrim(strtok(lines{dev_idx+1}, ',')));
        header = strsplit(lines{dev_idx+2}, ',');
        % Nexus repeats the device name per component; the row after holds
        % the component names, which are the useful labels.
        if dev_idx + 3 <= numel(lines)
            comps = strsplit(lines{dev_idx+3}, ',');
            if numel(comps) >= numel(header)
                header = comps;
            end
        end
        opts = detectImportOptions(filename, 'FileType', 'text', ...
                                   'Delimiter', ',', 'NumHeaderLines', dev_idx + 3);
        T = readtable(filename, opts);
        raw = table2array(T);
        % First two columns are Frame and Sub Frame.
        data = raw(:, 3:end);
        labels = header(3:min(numel(header), size(raw,2)));
    else
        T = readtable(filename);
        vn = T.Properties.VariableNames;
        data = table2array(T);
        labels = vn;
        fs = NaN;
        % A time column lets us infer the rate.
        tcol = find(strcmpi(vn, 'time') | strcmpi(vn, 't'), 1);
        if ~isempty(tcol)
            t = data(:, tcol);
            fs = 1 / median(diff(t));
            data(:, tcol) = [];
            labels(tcol) = [];
        end
    end

    if isnan(fs) || fs <= 0
        error('load_c3d_analog:noRate', ...
              ['Could not determine the sample rate from %s. ', ...
               'Export from Nexus with the rate header, or use a .c3d.'], filename);
    end

    labels = cellfun(@strtrim, labels, 'UniformOutput', false);
    n = size(data, 2);
    if numel(labels) < n
        for i = numel(labels)+1:n
            labels{i} = sprintf('Channel%d', i);
        end
    end

    rec.fs     = fs;
    rec.labels = labels(1:n);
    rec.units  = repmat({''}, 1, n);
    rec.data   = data;
end


function lines = local_read_lines(filename, n_max)
    lines = {};
    fid = fopen(filename, 'r');
    if fid < 0
        error('load_c3d_analog:openFailed', 'Could not open %s', filename);
    end
    c = onCleanup(@() fclose(fid));
    while numel(lines) < n_max
        l = fgetl(fid);
        if ~ischar(l), break; end
        lines{end+1} = l; %#ok<AGROW>
    end
end
