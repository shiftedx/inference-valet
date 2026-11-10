"""Native llama.cpp launch and read-only status contracts; never starts a model."""
import pathlib


RESERVED = {'--model', '-m', '--model-url', '-mu', '--hf-repo', '-hf', '--hf-file', '-hff',
            '--host', '--port', '--ctx-size', '-c', '--parallel', '-np', '--alias', '-a',
            '--api-key', '--api-key-file', '--config', '--kv-unified', '-kvu',
            '--no-kv-unified', '-no-kvu', '--kv-unified-per-slot', '--slots', '--no-slots',
            '--models-dir', '--models-preset', '--models-autoload', '--models-max',
            '--rpc', '--rpc-server', '--sleep-idle-seconds'}


def validate(args):
    if not isinstance(args, list) or any(not isinstance(a, str) or
            a.partition('=')[0] in RESERVED for a in args):
        raise ValueError('llama.cpp args must not override model, listener, context, slots or authentication')


def command(profile):
    # Fixed per-slot contexts avoid advertising a divided/shared pool as a per-request limit.
    return [str(profile['exe']), '--model', str(profile['artifact']),
            '--host', '127.0.0.1', '--port', '8080',
            '--ctx-size', str(profile['context'] * profile['slots']),
            '--parallel', str(profile['slots']), '--no-kv-unified',
            '--alias', profile['model'], '--slots', *profile.get('args', [])]


def matching_command(actual, profile):
    if len(actual) >= 2 and actual[-2] == '--api-key-file':
        actual = actual[:-2]
    expected = command(profile)
    return (len(actual) == len(expected) and
            pathlib.Path(actual[0]).resolve() == pathlib.Path(expected[0]).resolve() and
            pathlib.Path(actual[2]).resolve() == pathlib.Path(expected[2]).resolve() and
            actual[1:2] == expected[1:2] and actual[3:] == expected[3:])


def ready(profile, fetch):
    props = fetch('/props')
    models = fetch('/v1/models')
    defaults = props.get('default_generation_settings') or {}
    return (fetch('/health').get('status') == 'ok' and
            not props.get('is_sleeping', False) and
            props.get('total_slots') == profile['slots'] and
            defaults.get('n_ctx') == profile['context'] and
            any(m.get('id') == profile['model'] for m in models.get('data', [])))


def telemetry(props, slots, rates=None, requests=()):
    """Use public slot state only; do not retain prompts or request parameters."""
    if not isinstance(props, dict) or not isinstance(slots, list):
        raise ValueError('Unsupported llama.cpp status schema')
    context = (props.get('default_generation_settings') or {}).get('n_ctx')
    capacity = props.get('total_slots')
    if type(context) is not int or context < 1 or type(capacity) is not int or capacity < 1:
        raise ValueError('Missing llama.cpp capacity')
    rows = []
    rates = rates or {}
    for row in slots:
        active = row.get('is_processing') is True
        prompt = row.get('n_prompt_tokens') or 0
        processed = row.get('n_prompt_tokens_processed') or 0
        read = processed + (row.get('n_prompt_tokens_cache') or 0)
        next_tokens = row.get('next_token') or []
        generated = (next_tokens[0].get('n_decoded') or 0) if next_tokens else 0
        phase = 'generating' if active and generated else 'reading' if active else 'idle'
        speed = rates.get(row.get('id'), {})
        rows.append(dict(slot=row.get('id', len(rows)), state=phase,
                         prompt_tokens=read if active else None,
                         prompt_read=processed if active else None,
                         generated=generated if active else None,
                         tok_s=speed.get('tok_s') if phase == 'generating' else None,
                         prefill_tok_s=speed.get('prefill_tok_s') if phase == 'reading' else None,
                         held_tokens=prompt if not active else None))
    running = sum(row['state'] != 'idle' for row in rows)
    state = 'generating' if any(row['state'] == 'generating' for row in rows) else 'reading' if running else 'idle'
    def total_rate(phase, key):
        values = [row[key] for row in rows if row['state'] == phase]
        return sum(values) if values and all(value is not None for value in values) else None
    # Queue depth is not reported by /slots. Rates are measured counter deltas.
    metrics = dict(engine=dict(max_context=context, batch_slots=capacity, images=False),
                   requests=list(requests),
                   live=dict(state=state, slots=rows, running=running, queued=None,
                             tok_s=total_rate('generating', 'tok_s'),
                             prefill_tok_s_mean=total_rate('reading', 'prefill_tok_s'),
                             prompt_read=sum(row['prompt_read'] or 0 for row in rows if row['state'] == 'reading') if state == 'reading' else None,
                             generated=sum(row['generated'] or 0 for row in rows if row['state'] == 'generating') if state == 'generating' else None))
    status = dict(loaded=not props.get('is_sleeping', False), context=dict(native=context), concurrency=dict(serving=capacity),
                  vision=dict(enabled=False))
    return metrics, status
