"""Refresh managed Strata engine overrides immediately before an unloaded model starts.

Call under Strata's native request FIFO. No HTTP requests or process lifecycle
operations occur here; every other launch argument stays with the current listener.
"""
import copy
import json
import math
import os
from pathlib import Path
import sys
import uuid

import psutil

from ai_profiles import ProfileStore, argument, fingerprint, read_object, safe_stem, set_argument

ENGINE_FLAGS = ('--ple-io', '--expert-cache', '--resident-budget-gib',
                '--vram-reserve-mib', '--kv-resident', '--prefill',
                '--pool-workers', '--spec', '--spec-min-p', '--pcie-frac')
MEMORY_FLAGS = ENGINE_FLAGS  # Compatibility for the existing admission hook.


def _same_path(left, right):
    return os.path.normcase(str(Path(left).resolve())) == os.path.normcase(str(Path(right).resolve()))


def _verify_owner(record, root):
    """The recorded server may be the venv shim above this Python listener."""
    wrapper = root/'managed_strata_server.py'
    expected_python = root/'Strata'/'.venv'/'Scripts'/'python.exe'
    current = psutil.Process()
    chain = [current, *current.parents()]
    try:
        pid = int(record['server_pid'])
        started = float(record['server_started'])
        if pid <= 0 or not math.isfinite(started):
            raise ValueError('The active Strata server identity is invalid.')
        owner = next((process for process in chain if process.pid == pid), None)
        if owner is None or abs(owner.create_time()-started) > .05:
            raise ValueError('The active Strata server ownership changed; reload the profile from Valet.')
        interpreters = [expected_python, Path(sys.executable), Path(getattr(sys, '_base_executable', sys.executable))]
        for process in (owner, current):
            command = process.cmdline()
            if (not command or not any(_same_path(command[0], python) for python in interpreters)
                    or not any(_same_path(part, wrapper) for part in command[1:] if not part.startswith('-'))
                    or not any(_same_path(process.exe(), python) for python in interpreters)):
                raise ValueError('The active Strata process is not the managed listener; reload the profile from Valet.')
    except (KeyError, TypeError, OverflowError, psutil.Error) as error:
        raise ValueError('Cannot verify ownership of the active Strata listener.') from error


def _merged(args, desired):
    if not isinstance(args, list) or any(not isinstance(item, str) for item in args):
        raise ValueError('Strata launch arguments must be a list of strings.')
    result = list(args)
    for flag in ENGINE_FLAGS:
        if flag in ('--prefill', '--spec') and flag not in desired:
            continue  # Legacy templates may omit these required serving values.
        set_argument(result, flag, argument(desired, flag, None))
    # Context changes require recreating the listener. Validate the effective
    # memory/context pair rather than the template pair alone.
    resident = int(argument(result, '--kv-resident', '0'))
    context = int(argument(result, '--max-context', '0'))
    if resident > context:
        raise ValueError('Saved KV residency exceeds current context; load the profile from Valet to apply its context change.')
    spec = argument(result, '--spec', None)
    if spec is not None and (not spec.isdecimal() or not 2 <= int(spec) <= 8):
        raise ValueError('Draft tokens must be between 2 and 8 for serving.')
    prefill = argument(result, '--prefill', None)
    if prefill is not None and prefill not in ('auto', 'auto:8192', 'auto:16384', 'auto:32768'):
        if not prefill.isdecimal() or not 1 <= int(prefill) <= 32768:
            raise ValueError('Prompt batch must be positive or a supported auto mode for serving.')
    return result


def apply_pending_memory(svc, root):
    """Apply validated Engine-tab settings to this listener's next model load.

    Return True if launch arguments changed. A loaded model is never touched.
    Invalid owned configuration raises ValueError so admission can fail clearly.
    """
    if not getattr(svc, 'config_path', None):
        return False
    engine = getattr(svc, 'engine', None)
    if engine is None or not getattr(engine, 'unloaded', False) or svc.loaded():
        return False
    temporary = None
    original_spawn = None
    try:
        root = Path(root).resolve()
        logs = (root/'profile-logs').resolve()
        runtime = Path(svc.config_path).resolve()
        if runtime.parent != logs or runtime.suffix.lower() != '.json':
            raise ValueError('The active Strata run config is outside the managed profile logs.')
        active = logs/'active-profile.json'
        active_hash = fingerprint(active)
        record = read_object(active)
        if not _same_path(record.get('config', ''), runtime):
            raise ValueError('The active Strata profile changed; reload it from Valet.')
        _verify_owner(record, root)
        # The verified active record names the actual user profile, not a Valet
        # tuning preset. ProfileStore enforces filename and directory scope.
        key = safe_stem(record.get('profile'))
        # Read twice around ProfileStore.load so its parsed data and conflict hashes
        # cannot describe different versions of a concurrently saved profile.
        store = ProfileStore(root, root/'profile-logs'/'.valet-next-load')
        profile_paths = store.paths(key)
        before = [fingerprint(path) for path in profile_paths]
        values, snapshot = store.load(key)
        if before != snapshot['hashes']:
            raise ValueError('The Strata profile changed while preparing its next load; retry.')
        _, desired, _ = store.prepare(snapshot, values)
        runtime_hash = fingerprint(runtime)
        config = read_object(runtime)
        original_spawn = engine.spawn
        if not isinstance(original_spawn, (tuple, list)) or len(original_spawn) < 2:
            raise ValueError('The active Strata listener has no supported native launch settings.')
        new_args = _merged(original_spawn[1], desired['args'])
        runtime_args = _merged(config['args'], desired['args'])
        changed = new_args != original_spawn[1]
        config_changed = runtime_args != config['args']
        if not changed and not config_changed:
            return False
        new_spawn = list(original_spawn)
        new_spawn[1] = new_args
        new_spawn = tuple(new_spawn) if isinstance(original_spawn, tuple) else new_spawn
        new_config = copy.deepcopy(config)
        new_config['args'] = runtime_args
        if config_changed:
            temporary = runtime.with_name(runtime.name+'.'+uuid.uuid4().hex+'.tmp')
            temporary.write_text(json.dumps(new_config, indent=2)+'\n', encoding='utf-8')
        if (fingerprint(active) != active_hash or fingerprint(runtime) != runtime_hash
                or [fingerprint(path) for path in profile_paths] != snapshot['hashes']):
            raise ValueError('Strata settings changed while preparing the next load; retry.')
        # Recheck immediately before mutation even though the caller owns the FIFO.
        if svc.loaded() or not getattr(engine, 'unloaded', False):
            return False
        engine.spawn = new_spawn
        try:
            if temporary is not None:
                temporary.replace(runtime)
        except Exception:
            engine.spawn = original_spawn
            raise
        if argument(original_spawn[1], '--vram-reserve-mib', None) != argument(new_args, '--vram-reserve-mib', None):
            # A prior POST /v1/vram otherwise wins over the newly selected reserve.
            if hasattr(svc, 'vram_reserve'):
                svc.vram_reserve = None
            if hasattr(svc, 'vram_reserve_asked'):
                svc.vram_reserve_asked = False
        return changed or config_changed
    except (OSError, KeyError, TypeError, AttributeError, psutil.Error) as error:
        raise ValueError(f'Cannot apply pending Strata engine settings: {error}') from error
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
