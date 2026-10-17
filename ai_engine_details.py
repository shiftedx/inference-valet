"""Small, source-labelled views of Strata's runtime facts; no model/file I/O."""
import math
import ntpath
import re


def _num(value):
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
        return result if math.isfinite(result) and result >= 0 else None
    except (TypeError, ValueError, OverflowError):
        return None


def _count(value, unit=''):
    n = _num(value)
    return f'{n:,.0f}{unit}' if n is not None else None


def _gib(value):
    n = _num(value)
    return f'{n / 1024:,.1f} GiB' if n is not None else None


def _text(value):
    if not isinstance(value, (str, int, float)) or isinstance(value, bool):
        return None
    return str(value).replace('\n', ' ').replace('\r', ' ')[:100]


def _filename(value):
    return ntpath.basename(str(value).strip().strip('"'))[:100] if value else None


def parse_startup_facts(log_text):
    """Parse only the final startup in an already bounded, verified log sample.

    Callers must not join an old prefix to an unrelated tail: a missing startup
    is intentionally unknown. Paths are reduced to filenames at this boundary.
    """
    if not isinstance(log_text, str):
        return {}
    starts = list(re.finditer(r'(?m)^.*(?:\[strata\].*engine started:|strata generate: memory guard: limit).*$', log_text))
    if not starts:
        return {}
    text = log_text[starts[-1].start():]
    facts = {}
    match = re.search(r'RAM budget ([\d.]+) GiB: (\d+) of the', text)
    ready = re.search(r'cache complement ready: resident ([\d.]+) GiB, pinned ([\d.]+) GiB', text)
    if match and ready:
        facts.update(ram_experts=int(match[2]), ram_expert_gib=float(ready[1]),
                     ram_expert_pinned_gib=float(ready[2]))
    match = re.search(r'PLE on, table (\d+) rows of (.+)', text)
    if match:
        facts.update(ple_rows=int(match[1]), ple_file=_filename(match[2]))
        if 'PLE direct read probe:' in text:
            facts['ple_location'] = 'Disk / direct file reads'
        if 'using --ple-io mmap instead' in text:
            facts['ple_location'] = 'Mapped file / OS page cache'
        if 'PLE table locked in RAM (--ple-io ram)' in text:
            facts['ple_location'] = 'Locked host RAM'
        elif 'PLE table loaded (not locked) (--ple-io ram)' in text:
            facts['ple_location'] = 'Host RAM / not page-locked'
    match = re.search(r'profile .+?: (\d+) ranked pairs, built for (\d+) slots', text)
    if match:
        facts['total_experts'] = int(match[2])
    match = re.search(r'token embedding (\S+) in mapped host memory \((\d+) MiB', text)
    if match:
        facts['token_embedding'] = f'{match[1]} · mapped host RAM · {match[2]} MiB'
    match = re.search(r'KV streaming: (\d+) of (\d+) cells per QSA layer in VRAM, the K/V in ([\d.]+) GiB of pinned RAM', text)
    if match:
        facts['kv_placement'] = f'{int(match[1]):,} cells/layer in VRAM · {match[3]} GiB pinned RAM'
    return facts


def build_engine_details(metrics, status, runtime_config=None, startup_facts=None, shared_settings=None):
    """Return stable compact groups; active config must belong to verified server.

    Engine INFO survives unloading. Never describe its cached memory figures as
    presently resident when status cannot confirm the model is loaded.
    """
    metrics = metrics if isinstance(metrics, dict) else {}
    status = status if isinstance(status, dict) else {}
    engine = metrics.get('engine') or {}
    engine = engine if isinstance(engine, dict) else {}
    config = runtime_config if isinstance(runtime_config, dict) else {}
    facts = startup_facts if isinstance(startup_facts, dict) else {}
    shared = shared_settings.get('defaults') if isinstance(shared_settings, dict) else {}
    shared = shared if isinstance(shared, dict) else {}
    args = config.get('args') or []
    flags = {}
    if isinstance(args, list):
        for i, arg in enumerate(args):
            if isinstance(arg, str) and arg.startswith('--'):
                flags[arg] = args[i + 1] if i + 1 < len(args) and not str(args[i + 1]).startswith('--') else True
    loaded = status.get('loaded') is True
    unloaded = status.get('loaded') is False
    groups = []

    def group(title):
        result = {'title': title, 'rows': []}
        groups.append(result)
        return result['rows']

    def add(rows, label, value=None, source='Reported'):
        rows.append({'label': label, 'value': str(value) if value is not None else 'Not reported',
                     'source': source if value is not None else 'Not reported'})

    def reported(rows, label, key, formatter=_text, flag=None):
        value = formatter(engine.get(key))
        if value is not None:
            add(rows, label, value)
        elif flag in flags:
            add(rows, label, formatter(flags[flag]), 'Active configuration')
        else:
            add(rows, label)

    rows = group('Model memory')
    add(rows, 'Model residency', 'Loaded' if loaded else 'Model unloaded' if unloaded else None)
    memory_source = 'Reported' if loaded else 'Last start'
    for label, key, formatter in [('GPU expert slots', 'expert_slots', lambda v: _count(v, ' slots')),
                                   ('GPU expert cache', 'expert_cache_mib', _gib)]:
        add(rows, label, formatter(engine.get(key)), memory_source)
    add(rows, 'RAM experts', _count(facts.get('ram_experts'), ' experts'), 'Startup log' if loaded else 'Last start')
    n = _num(facts.get('ram_expert_gib'))
    add(rows, 'Resident expert RAM', f'{n:,.2f} GiB' if n is not None else None, 'Startup log' if loaded else 'Last start')
    n = _num(facts.get('ram_expert_pinned_gib'))
    add(rows, 'Pinned expert RAM', f'{n:,.2f} GiB' if n is not None else None, 'Startup log' if loaded else 'Last start')
    add(rows, 'Profile expert slots', _count(facts.get('total_experts'), ' slots'), 'Startup log' if loaded else 'Last start')
    add(rows, 'Engram / PLE placement', _text(facts.get('ple_location')), 'Startup log' if loaded else 'Last start')
    filename = _filename(facts.get('ple_file'))
    if filename:
        add(rows, 'Engram / PLE table', filename, 'Startup log' if loaded else 'Last start')
    elif '--ple-gguf' in flags:
        add(rows, 'Engram / PLE source', _filename(flags['--ple-gguf']), 'Active configuration')
    else:
        add(rows, 'Engram / PLE table')
    add(rows, 'Engram / PLE rows', _count(facts.get('ple_rows')), 'Startup log' if loaded else 'Last start')
    add(rows, 'KV placement', _text(facts.get('kv_placement')), 'Startup log' if loaded else 'Last start')
    add(rows, 'Token embeddings', _text(facts.get('token_embedding')), 'Startup log' if loaded else 'Last start')

    rows = group('Engine settings')
    reported(rows, 'Strata version', 'version')
    reported(rows, 'Context per agent', 'max_context', lambda v: _count(v, ' tokens'), '--max-context')
    reported(rows, 'KV format', 'kv', _text, '--kv')
    reported(rows, 'KV GPU cells / layer', 'kv_resident', _count, '--kv-resident')
    reported(rows, 'Prefill chunk limit', 'prefill_cap', lambda v: _count(v, ' tokens'), '--prefill')
    reported(rows, 'CPU pool workers', 'pool_workers', _count, '--pool-workers')
    reported(rows, 'Control vector', 'cvec')
    reported(rows, 'Conversation cache budget', 'conversation_cache_mib', _gib)
    for label, flag, formatter in [('Expert cache policy', '--expert-cache', _text),
                                    ('Engram / PLE I/O mode', '--ple-io', _text),
                                    ('Expert RAM budget', '--resident-budget-gib', lambda v: f'{_num(v):g} GiB' if _num(v) is not None else None),
                                    ('GPU reserve target', '--vram-reserve-mib', lambda v: _count(v, ' MiB'))]:
        add(rows, label, formatter(flags.get(flag)), 'Active configuration')
    concurrency = status.get('concurrency') or {}
    add(rows, 'Parallel agents', _count(concurrency.get('serving')))
    vision = (status.get('vision') or {}).get('enabled')
    add(rows, 'Vision', 'On' if vision is True else 'Off' if vision is False else None)

    rows = group('Generation settings')
    reported(rows, 'Verify window', 'spec', lambda v: _count(v, ' tokens'), '--spec')
    reported(rows, 'MTP draft limit', 'mtp_max', lambda v: _count(v, ' tokens'))
    reported(rows, 'Lookup draft limit', 'lookup', lambda v: _count(v, ' tokens'))
    reported(rows, 'Draft minimum probability', 'spec_min_p', _text, '--spec-min-p')
    for label, key, formatter in [('Max output tokens', 'max_tokens', lambda v: _count(v, ' tokens')),
                                  ('Reasoning effort', 'reasoning_effort', _text),
                                  ('Reasoning budget', 'reasoning_budget_tokens', lambda v: _count(v, ' tokens'))]:
        if key in shared:
            add(rows, label, formatter(shared[key]), 'Shared defaults')
        else:
            add(rows, label, formatter(config.get(key)), 'Active configuration')
    # These are defaults for requests that do not override them; never inspect
    # arbitrary request fields or serialize the settings/config dictionaries.
    for label, key in [('Temperature', 'temperature'), ('Top-p', 'top_p'),
                       ('Top-k', 'top_k'), ('Min-p', 'min_p'),
                       ('Repetition penalty', 'repetition_penalty'), ('Seed', 'seed')]:
        for source, values in [('Shared defaults', shared), ('Reported', engine), ('Active configuration', config)]:
            if key in values:
                n = _num(values[key])
                add(rows, label, f'{n:g}' if n is not None else None, source)
                break
    fit = config.get('fit_max_tokens')
    add(rows, 'Fit output to context', 'On' if fit is True else 'Off' if fit is False else None, 'Active configuration')
    return groups
