"""Authenticated dashboard exports: bounded allowlists, cached read-only sampling."""
import copy
import math
import threading
import time

SCHEMA = 'inference-valet.metrics/1'
STATES = {'ready', 'reading', 'generating', 'loading', 'busy', 'blocked', 'unloaded', 'offline', 'unavailable'}
FINISHES = {'stop', 'length', 'cancelled', 'canceled', 'cancel', 'error', 'failed', 'complete', 'completed', 'eos', 'finished'}
BACKENDS = {'strata', 'infernix', 'ninfer', 'llamacpp'}
HARDWARE = {
    'cpu_utilization_ratio': ('cpu', .01), 'ram_used_bytes': ('ram_used', 1),
    'ram_total_bytes': ('ram_total', 1), 'gpu_utilization_ratio': ('gpu_util', .01),
    'gpu_memory_used_bytes': ('gpu_mem_used', 1), 'gpu_memory_total_bytes': ('gpu_mem_total', 1),
    'gpu_temperature_celsius': ('gpu_temp', 1), 'gpu_power_watts': ('gpu_power', 1),
    'gpu_power_limit_watts': ('gpu_power_limit', 1), 'gpu_clock_hertz': ('gpu_clock', 1e6),
    'gpu_memory_clock_hertz': ('gpu_memory_clock', 1e6), 'gpu_memory_activity_ratio': ('gpu_memory_busy', .01),
}
PERFORMANCE = {
    'decode_tokens_per_second': ('live_speed', 1), 'prefill_tokens_per_second': ('prefill_speed', 1),
    'last_decode_tokens_per_second': ('last_speed', 1), 'last_prefill_tokens_per_second': ('last_prefill', 1),
    'last_ttft_seconds': ('ttft_ms', .001), 'last_request_timestamp_seconds': ('last_at', 1),
    'prefix_reuse_ratio': ('reuse', .01), 'draft_acceptance_ratio': ('draft_acceptance', .01),
    'expert_cache_hit_ratio': ('expert_hits', .01), 'pcie_transfer_ratio': ('pcie_share', .01),
    'prompt_read_tokens': ('prompt_read', 1), 'prompt_total_tokens': ('prompt_total', 1),
    'generated_tokens': ('generated', 1),
}
RECENT = {
    'time': ('time', 1), 'output_tokens': ('tokens', 1), 'duration_seconds': ('duration_s', 1),
    'prefill_tokens_per_second': ('prefill_tok_s', 1), 'decode_tokens_per_second': ('decode_tok_s', 1),
    'ttft_seconds': ('ttft_ms', .001), 'prefix_reuse_ratio': ('reuse_percent', .01),
    'draft_acceptance_ratio': ('draft_percent', .01),
}


def mapping(value):
    return value if isinstance(value, dict) else {}


def numeric(value, factor=1):
    if type(value) not in (int, float) or value < 0:
        return None
    try:
        result = value * factor
        return result if math.isfinite(result) else None
    except OverflowError:
        return None


def fields(source, definitions):
    source = mapping(source)
    out = {key: numeric(source.get(name), scale) for key, (name, scale) in definitions.items()}
    return {key: None if key.endswith('_ratio') and value is not None and value > 1 else value for key, value in out.items()}


def sanitize(reading, key, profile):
    reading = mapping(reading)
    activity = mapping(reading.get('activity'))
    state = activity.get('state')
    state = state if state in STATES else 'unavailable'
    profile = mapping(profile)
    info = {'id': key[:256] if isinstance(key, str) else None,
            'backend': profile.get('engine') if profile.get('engine') in BACKENDS else None,
            'loaded': True if state in {'ready', 'reading', 'generating', 'busy'} else
                      False if state in {'unloaded', 'offline'} else None,
            **{name: numeric(profile.get(source)) for name, source in {
                'context_tokens': 'context', 'parallel_slots': 'slots', 'kv_capacity_tokens': 'kv_cache_tokens',
                'default_max_output_tokens': 'default_max_output_tokens', 'max_output_tokens': 'max_output_tokens'}.items()}}
    for name in ('supports_vision', 'kv_shared'):
        info[name] = profile.get(name) if type(profile.get(name)) is bool else None
    slots, seen = [], set()
    raw_slots = reading.get('slots')
    for slot in raw_slots[:256] if isinstance(raw_slots, list) else []:
        slot = mapping(slot)
        row = fields(slot, {name: (source, 1) for name, source in {
            'slot': 'slot', 'used_tokens': 'used', 'context_tokens': 'limit', 'decode_tokens_per_second': 'speed'}.items()})
        if row['slot'] is None or row['slot'] != int(row['slot']) or row['slot'] in seen:
            continue
        seen.add(row['slot'])
        row['state'] = slot.get('state') if slot.get('state') in STATES | {'cached', 'idle'} else 'unavailable'
        slots.append(row)
    recent = []
    raw_recent = activity.get('recent')
    for item in raw_recent[:12] if isinstance(raw_recent, list) else []:
        item = mapping(item)
        row = fields(item, RECENT)
        row['finish'] = item.get('finish') if item.get('finish') in FINISHES else 'finished'
        recent.append(row)
    hardware = fields(reading.get('hardware'), HARDWARE)
    hardware['gpu_active_average_watts'] = numeric(mapping(reading.get('power_stats')).get('average_watts'))
    return {'state': state, 'profile': info, 'hardware': hardware, 'performance': fields(reading, PERFORMANCE),
            'requests': {**{key: numeric(activity.get(key)) for key in ('in_flight', 'running', 'queued')},
                         'occupied_slots': numeric(reading.get('occupied_slots'))},
            'slots': slots, 'recent_requests': recent}


class MetricsExporter:
    """One sampler per provider group; scrapes never enter model admission or load."""
    def __init__(self, sample, profile, interval=2, clock=time.monotonic, wall=time.time):
        self.sample, self.profile = sample, profile
        self.interval, self.clock, self.wall = interval, clock, wall
        self.lock = threading.Lock()
        self.started = clock()
        self.attempted = float('-inf')
        self.sampled = None
        self.timestamp = None
        self.data = sanitize({}, None, {})
        self.error = None

    def snapshot(self):
        with self.lock:
            now = self.clock()
            if now - self.attempted >= self.interval:
                self.attempted = now
                try:
                    key, profile = self.profile()
                    reading = self.sample()
                    if self.profile()[0] != key:
                        raise ValueError('Profile changed during sampling')
                    self.data = sanitize(reading, key, profile)
                    self.sampled, self.timestamp, self.error = self.clock(), self.wall(), None
                except Exception:
                    self.error = 'collection_failed'
                self.attempted = self.clock()
            now = self.clock()
            age = now - self.sampled if self.sampled is not None else None
            return {'schema': SCHEMA, 'sampled_at': self.timestamp, 'age_seconds': age,
                    'available': self.sampled is not None and self.error is None and self.data['state'] != 'unavailable',
                    'stale': age is None or age > 10 or self.error is not None, 'collection_error': self.error,
                    'exporter_uptime_seconds': max(0, now - self.started), **copy.deepcopy(self.data)}


def escape(value):
    return str(value).replace('\\', '\\\\').replace('\n', '\\n').replace('"', '\\"')


def prometheus(snapshot):
    """Prometheus text 0.0.4; omit unavailable samples and unbounded request labels."""
    groups = {}

    def add(name, value, labels=None):
        if type(value) is bool:
            value = int(value)
        if numeric(value) is not None:
            groups.setdefault('valet_' + name, []).append((value, labels or {}))

    profile = snapshot['profile']
    labels = {name: value for name, value in [('profile', profile['id']), ('backend', profile['backend'])] if value is not None}
    add('telemetry_up', snapshot['available'])
    add('telemetry_stale', snapshot['stale'])
    add('telemetry_age_seconds', snapshot['age_seconds'])
    add('telemetry_sample_timestamp_seconds', snapshot['sampled_at'])
    add('metrics_exporter_uptime_seconds', snapshot['exporter_uptime_seconds'])
    add('profile_info', 1, {**labels, 'state': snapshot['state']})
    for key, value in profile.items():
        if key not in ('id', 'backend'):
            add('profile_' + key, value, labels)
    for section in ('hardware', 'performance', 'requests', 'provider'):
        for key, value in snapshot.get(section, {}).items():
            add(section + '_' + key, value, None if section in ('hardware', 'provider') else labels)
    for slot in snapshot['slots']:
        slot_labels = {**labels, 'slot': slot['slot']}
        for key, value in slot.items():
            if key not in ('slot', 'state'):
                add('slot_' + key, value, slot_labels)
    lines = []
    for name, values in groups.items():
        lines.extend([f'# HELP {name} Valet sampled {name[6:].replace("_", " ")}.', f'# TYPE {name} gauge'])
        for value, labels in values:
            suffix = '{' + ','.join(f'{key}="{escape(value)}"' for key, value in labels.items()) + '}' if labels else ''
            lines.append(f'{name}{suffix} {value}')
    return '\n'.join(lines) + '\n'
