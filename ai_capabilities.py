"""Backend response-format guarantees, separate from tool-call constraints."""
import functools
import os
import pathlib
import subprocess
import time


RESPONSES_BACKENDS = {'strata', 'infernix', 'llamacpp', 'delta', 'maya', 'dsv41'}


@functools.lru_cache(maxsize=32)
def _validator(python, pythonpath, interval):
    """Check the serving interpreter without importing or starting an engine."""
    if not pathlib.Path(python).is_file():
        return None
    env = dict(os.environ)
    if pythonpath:
        env['PYTHONPATH'] = pythonpath
    try:
        result = subprocess.run([python, '-c',
            'from jsonschema import validators; from referencing import Registry; '
            'validators.Draft202012Validator.check_schema({"type":"object"}); print("ready")'],
            env=env, capture_output=True, text=True, timeout=3,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        return result.returncode == 0 and result.stdout.strip() == 'ready'
    except (OSError, subprocess.TimeoutExpired):
        return None


def validator_available(profile):
    engine = profile['engine']
    if engine == 'strata':
        command = profile.get('command') or []
        python = command[0] if command else ''
        pythonpath = ''
    else:
        settings = profile.get(engine) or {}
        python = settings.get('server_python', '')
        pythonpath = settings.get('env', {}).get('PYTHONPATH', '')
    if not python:
        return None
    return _validator(str(python), pythonpath, int(time.monotonic() // 300))


def capabilities(profile):
    engine = profile['engine']
    grammar = engine in ('infernix', 'llamacpp')
    validated = engine in ('strata', 'dsv41', 'maya')
    schema = True if grammar else validator_available(profile) if validated else None
    formats = ['json_object', 'json_schema'] if grammar or validated else []
    endpoints = {'/v1/chat/completions': 'response_format'} if formats else {}
    if formats and engine in RESPONSES_BACKENDS:
        endpoints['/v1/responses'] = 'text.format'
    return dict(
        supports_json_mode=bool(formats),
        supports_json_schema=schema if formats else None,
        supports_structured_outputs=schema if formats else None,
        structured_output=dict(formats=formats,
            method='grammar_constrained' if grammar else 'prompt_and_validate' if validated else 'unknown',
            constrained_decoding=True if grammar else False if validated else None,
            schema_validation=schema,
            schema_scope='backend_supported_subset' if grammar else 'jsonschema_supported_dialects' if schema else None,
            stream_buffered=False if grammar else True if validated else None,
            endpoints=endpoints,
            # This does not claim Anthropic output_config.format support.
            anthropic_output_format=False if engine == 'infernix' else None),
        tool_calling=dict(strict_schema=True if engine == 'infernix' else False if validated else None))
