"""Read and edit external Strata profiles without touching the running engine."""
import copy
import hashlib
import json
import math
import pathlib
import time
import uuid

PRESETS = {
    'strata-128k': ('quality-iq3-xxs', 163840, 1),
    'strata-256k': ('quality-iq3-xxs-max-context', 262144, 1),
    'strata-2': ('quality-iq3-xxs-agents', 65536, 2),
    'strata-3': ('quality-iq3-xxs-agents-3', 163840, 3),
    'strata-4': ('quality-iq3-xxs-agents-4', 65536, 4),
}

def argument(args, flag, default=''):
    return args[args.index(flag)+1] if flag in args else default

def set_argument(args, flag, value):
    """Replace the complete override; None restores the backend default."""
    positions = [index for index, item in enumerate(args) if item == flag]
    insert = positions[0] if positions else len(args)
    for index in reversed(positions):
        del args[index:index+2]
    if value is not None:
        args[insert:insert] = [flag, str(value)]

def fingerprint(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None

def read_object(path, default=None):
    if not path.exists() and default is not None:
        return copy.deepcopy(default)
    data = json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(data, dict):
        raise ValueError(f'{path.name} must contain a JSON object.')
    return data

def profile_name(name, context, slots):
    window = f'{context//1024}K' if context % 1024 == 0 else f'{context:,}'
    return f'{name} · {slots} '+('agent' if slots == 1 else 'agents')+f' · {window}'+(' each' if slots > 1 else '')

# Optional fields remain absent when blank; unexposed engine arguments survive saves.
TUNING = {
    'prefill': ('--prefill', int, 1, 32768, 'Prompt batch'),
    'resident': ('--resident-budget-gib', float, 0, 1024, 'Resident RAM budget'),
    'kv_resident': ('--kv-resident', int, 0, 1048576, 'Resident KV tokens'),
    'reserve': ('--vram-reserve-mib', int, 0, 1048576, 'VRAM reserve'),
    'workers': ('--pool-workers', int, 0, 1024, 'CPU workers'),
    'spec': ('--spec', int, 2, 8, 'Draft tokens'),
    'spec_min': ('--spec-min-p', float, 0, 1, 'Draft minimum probability'),
    'pcie': ('--pcie-frac', float, 0, 1, 'PCIe fraction'),
    'expert_cache': ('--expert-cache', int, 0, 2147483647, 'GPU expert slots'),
}

EDITABLE_FLAGS = {'--max-context', '--kv', '--ple-io', *(spec[0] for spec in TUNING.values())}

def validate_arguments(args):
    """Reject ambiguous imports rather than silently editing the wrong override."""
    if not isinstance(args, list) or any(not isinstance(item, str) for item in args):
        raise ValueError('Profile arguments must be a list of strings.')
    for flag in EDITABLE_FLAGS:
        positions = [index for index, item in enumerate(args) if item == flag]
        if len(positions)>1:
            raise ValueError(f'Profile contains duplicate {flag} overrides. Resolve them before editing.')
        if positions and (positions[0]+1>=len(args) or args[positions[0]+1].startswith('--')):
            raise ValueError(f'Profile {flag} is missing its value.')

class ProfileStore:
    def __init__(self, root, state):
        self.root = pathlib.Path(root)
        self.state = pathlib.Path(state)
        self.names_path = self.state/'profile-names.json'

    def paths(self, key):
        name = PRESETS[key][0]
        path = self.root/'profiles'/f'{name}.json'
        return path, path.with_suffix('.shared-settings.json'), self.names_path

    def descriptors(self, python, config):
        names = read_object(self.names_path, {})
        enabled = config.get('enabled_profiles', list(PRESETS))
        if not isinstance(enabled, list) or not enabled or any(key not in PRESETS for key in enabled):
            raise ValueError('enabled_profiles must be a nonempty list of Strata profile IDs')
        result = {}
        for key in enabled:
            preset, context, slots = PRESETS[key]
            path = self.paths(key)[0]
            data = read_object(path) if path.exists() else {}
            context = int(argument(data.get('args', []), '--max-context', context))
            slots = int(data.get('parallel', slots))
            name = profile_name(names.get(key, 'Strata'), context, slots)
            result[key] = dict(label=name, name=name, engine='strata', profile=preset,
                               context=context, slots=slots, model=data.get('model_name', 'qwen3.8-flash-next-iq3_xxs'),
                               command=[str(python), str(self.root/'launch_strata_profile.py'), preset,
                                        *(['--on-demand'] if config.get('on_demand', {}).get('enabled') else [])],
                               cwd=str(self.root))
        for key, profile in result.items():
            if sum(row['label']==profile['label'] for row in result.values())>1:
                profile['name'] = profile['label']+f' · {key}'
        return result

    def load(self, key):
        paths = self.paths(key)
        data = read_object(paths[0]);shared = read_object(paths[1], {});names = read_object(paths[2], {})
        args = data['args']
        validate_arguments(args)
        values = dict(name=names.get(key, 'Strata'), context=argument(args, '--max-context'),
                      slots=str(data.get('parallel', 1)), kv=argument(args, '--kv'),
                      max_tokens=str(shared.get('max_tokens', data.get('max_tokens', ''))),
                      reasoning=str(shared.get('reasoning_budget_tokens', data.get('reasoning_budget_tokens', 0))),
                      effort=shared.get('reasoning_effort', data.get('reasoning_effort', 'high')))
        values.update({key:argument(args, spec[0]) for key, spec in TUNING.items()})
        values['ple_io'] = argument(args, '--ple-io')
        snapshot = dict(data=data, shared=shared, names=names, hashes=[fingerprint(path) for path in paths])
        return values, snapshot

    @staticmethod
    def prepare(snapshot, values):
        data = copy.deepcopy(snapshot['data']);shared = copy.deepcopy(snapshot['shared'])
        validate_arguments(data['args'])
        name = values['name'].strip()
        if not name or len(name)>64 or any(ord(char)<32 for char in name):
            raise ValueError('Profile name must contain 1–64 printable characters.')
        def integer(key, low, high, label):
            try:
                raw = str(values[key]).strip()
                if not raw.isdecimal():raise ValueError()
                value = int(raw)
            except (ValueError, TypeError):raise ValueError(f'{label} must be a whole number.')
            if not low<=value<=high:raise ValueError(f'{label} must be between {low:,} and {high:,}.')
            return value
        context = integer('context', 1024, 1048576, 'Context per agent')
        slots = integer('slots', 1, 4, 'Agents')
        budget = integer('reasoning', 0, context, 'Reasoning budget')
        if values['effort'] not in ('none', 'low', 'medium', 'high'):
            raise ValueError('Choose a supported reasoning effort.')
        # Keep an existing backend KV format if it is not one of the common presets.
        if values['kv'] not in ('int8', 'q4_0', 'fp16', 'k8v4', argument(data['args'], '--kv')):
            raise ValueError('Choose a supported KV format.')
        data['parallel'] = slots
        data['reasoning_budget_tokens'] = shared['reasoning_budget_tokens'] = budget
        data['reasoning_effort'] = shared['reasoning_effort'] = values['effort']
        if str(values['max_tokens']).strip():
            shared['max_tokens'] = integer('max_tokens', 1, context, 'Maximum output')
            if 'max_tokens' in data:data['max_tokens'] = shared['max_tokens']
        else:
            shared.pop('max_tokens', None);data.pop('max_tokens', None)
        set_argument(data['args'], '--max-context', context)
        if values['kv']:set_argument(data['args'], '--kv', values['kv'])
        if 'ple_io' in values:
            placement = str(values['ple_io']).strip()
            if placement not in ('', 'direct', 'mmap', 'ram'):
                raise ValueError('Engram placement must be backend default, direct, mmap, or ram.')
            if placement != argument(data['args'], '--ple-io'):
                set_argument(data['args'], '--ple-io', placement or None)
        for key, (flag, kind, low, high, label) in TUNING.items():
            if key not in values:continue
            raw = str(values[key]).strip()
            if not raw:
                if key in ('prefill', 'spec') and flag in data['args']:
                    raise ValueError(f'{label} is required for serving; keep a supported value.')
                set_argument(data['args'], flag, None);continue
            # Strata's adaptive prompt batching uses the literal "auto".
            if key=='prefill' and raw in ('auto','auto:8192','auto:16384','auto:32768'):
                set_argument(data['args'], flag, raw);continue
            if key=='expert_cache' and raw=='auto':
                set_argument(data['args'], flag, raw);continue
            try:
                value = kind(raw)
                if kind is int and not raw.isdecimal():raise ValueError()
                if not math.isfinite(value) or not low<=value<=high:raise ValueError()
                if key=='resident' and value<=0:raise ValueError()
            except (ValueError, TypeError, OverflowError):
                if key=='resident':raise ValueError('Resident RAM budget must be greater than 0 and at most 1024 GiB.')
                raise ValueError(f'{label} must be between {low:g} and {high:g}.')
            # Preserve valid imported formatting and unexposed arguments on a no-op save.
            if raw != argument(data['args'], flag):
                set_argument(data['args'], flag, value)
        resident = int(argument(data['args'], '--kv-resident', 0))
        if 0<resident<20480:raise ValueError('Resident KV tokens must be 0 or at least 20,480 (Strata minimum).')
        if resident>context:raise ValueError('Resident KV tokens cannot exceed context per agent.')
        return name, data, shared

    def save(self, key, values, snapshot):
        name, data, shared = self.prepare(snapshot, values)
        paths = self.paths(key)
        if [fingerprint(path) for path in paths]!=snapshot['hashes']:
            raise ValueError('This profile changed outside the editor. Close and reopen it before saving.')
        names = dict(snapshot['names']);names[key] = name
        originals = [path.read_bytes() if path.exists() else None for path in paths]
        backup = self.state/'profile-backups'/(time.strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:8])
        backup.mkdir(parents=True)
        for path, raw in zip(paths, originals):
            if raw is not None:(backup/path.name).write_bytes(raw)
        temporary = []
        replaced = []
        try:
            for path, obj in zip(paths, (data, shared, names)):
                path.parent.mkdir(parents=True, exist_ok=True)
                temp = path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp');temporary.append(temp)
                temp.write_text(json.dumps(obj, indent=2)+'\n', encoding='utf-8')
            for index, (temp, path) in enumerate(zip(temporary, paths)):
                temp.replace(path);replaced.append(index)
        except Exception:
            for index in reversed(replaced):
                if originals[index] is None:paths[index].unlink(missing_ok=True)
                else:paths[index].write_bytes(originals[index])
            raise
        finally:
            for temp in temporary:temp.unlink(missing_ok=True)
        return backup
