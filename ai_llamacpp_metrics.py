"""Bounded numeric-only llama.cpp observations; never retain response content."""
import json
import math
import threading
import time

from ai_config import STATE_DIR
from ai_issues import write_json

_LOCK = threading.RLock()
FIELDS = ('time', 'duration_s', 'ttft_ms', 'prompt_tokens', 'prompt_read', 'reused',
          'output_tokens', 'prompt_ms', 'decode_ms', 'prefill_tok_s', 'decode_tok_s',
          'drafts_accepted', 'drafts_offered')
FINISH = {'stop', 'length', 'cancelled', 'error', 'completed'}


def number(value):
    return value if type(value) in (int, float) and math.isfinite(value) and value >= 0 else None


def safe_row(row):
    if not isinstance(row, dict):
        return {}
    result = {k: number(row.get(k)) for k in FIELDS}
    result['finish'] = row.get('finish') if row.get('finish') in FINISH else 'completed'
    return result


class History:
    def __init__(self, path=None):
        self.path = path if path is not None else STATE_DIR / 'llamacpp-performance.json'

    def read(self, identity):
        try:
            with self.path.open('rb') as stream:
                data = stream.read(256 * 1024 + 1)
            if len(data) > 256 * 1024:
                return []
            saved = json.loads(data)
            if saved.get('schema') != 1 or saved.get('identity') != list(identity):
                return []
            rows = saved.get('requests')
            return [safe_row(row) for row in rows[:100] if isinstance(row, dict)] if isinstance(rows, list) else []
        except (OSError, ValueError, TypeError, AttributeError):
            return []

    def append(self, identity, row):
        try:
            with _LOCK:
                write_json(self.path, dict(schema=1, identity=list(identity),
                                          requests=[safe_row(row), *self.read(identity)][:100]))
        except (OSError, ValueError, TypeError):
            pass  # Observability must never fail inference.


class Observation:
    def __init__(self, identity, started=None, history=None, clock=time.monotonic, wall=time.time):
        self.identity = identity
        self.clock, self.wall = clock, wall
        self.started = clock() if started is None else started
        self.history = history if history is not None else History()
        self.row = {}
        self.done = False
        self.first = None
        self.finished = False

    def event(self, event, streaming=True):
        if not isinstance(event, dict):
            return
        timings = event.get('timings')
        if isinstance(timings, dict):
            for source, target in [('prompt_n', 'prompt_read'), ('cache_n', 'reused'),
                    ('predicted_n', 'output_tokens'), ('prompt_ms', 'prompt_ms'),
                    ('predicted_ms', 'decode_ms'), ('prompt_per_second', 'prefill_tok_s'),
                    ('predicted_per_second', 'decode_tok_s'), ('draft_n', 'drafts_offered'),
                    ('draft_n_accepted', 'drafts_accepted')]:
                value = number(timings.get(source))
                if value is not None:
                    self.row[target] = value
        usage = event.get('usage')
        if isinstance(usage, dict):
            for source, target in [('prompt_tokens', 'prompt_tokens'), ('completion_tokens', 'output_tokens'),
                    ('input_tokens', 'prompt_tokens'), ('output_tokens', 'output_tokens'),
                    ('cache_read_input_tokens', 'reused')]:
                value = number(usage.get(source))
                if value is not None and (target not in self.row or source in ('completion_tokens', 'output_tokens')):
                    self.row[target] = value
            cache = usage.get('prompt_tokens_details')
            if isinstance(cache, dict) and number(cache.get('cached_tokens')) is not None:
                self.row['reused'] = cache['cached_tokens']
        meaningful = False
        choices = event.get('choices')
        for choice in choices if isinstance(choices, list) else []:
            if not isinstance(choice, dict):
                continue
            delta = choice.get('delta') or {}
            if isinstance(delta, dict):
                meaningful |= any(bool(delta.get(k)) for k in ('content', 'reasoning_content', 'reasoning', 'tool_calls'))
            if choice.get('finish_reason'):
                self.done = True
                self.row['finish'] = 'length' if choice['finish_reason'] == 'length' else 'stop'
        kind = event.get('type')
        if kind == 'content_block_delta':
            delta = event.get('delta') or {}
            if isinstance(delta, dict):
                meaningful |= any(bool(delta.get(k)) for k in ('text', 'thinking', 'partial_json'))
        elif kind == 'content_block_start':
            block = event.get('content_block') or {}
            if isinstance(block, dict):
                meaningful |= any(bool(block.get(k)) for k in ('text', 'thinking', 'name'))
        elif kind in ('response.output_text.delta', 'response.reasoning_text.delta',
                      'response.reasoning_summary_text.delta', 'response.function_call_arguments.delta'):
            meaningful |= bool(event.get('delta'))
        if kind == 'message_delta':
            delta = event.get('delta') or {}
            if isinstance(delta, dict) and delta.get('stop_reason'):
                self.row['finish'] = 'length' if delta['stop_reason'] == 'max_tokens' else 'stop'
        if kind in ('message_stop', 'response.completed', 'response.incomplete'):
            self.done = True
            self.row.setdefault('finish', 'length' if kind == 'response.incomplete' else 'stop')
        if event.get('error') or kind in ('error', 'response.failed'):
            self.done = True
            self.row['finish'] = 'error'
        if streaming and meaningful and self.first is None:
            self.first = self.clock()
        # Messages/Responses wrap usage and native timings in the response/message.
        for field in ('response', 'message'):
            nested = event.get(field)
            if isinstance(nested, dict):
                done = self.done
                self.event(nested, streaming=False)
                self.done = done
        if not streaming:
            self.done = True
            self.row.setdefault('finish', 'length' if event.get('stop_reason') == 'max_tokens' else 'stop')

    def finish(self, status=200, failed=False):
        if self.finished:
            return
        self.finished = True
        row = dict(self.row)
        row.update(time=self.wall(), duration_s=max(0, self.clock() - self.started),
                   ttft_ms=max(0, (self.first-self.started)*1000) if self.first is not None else None)
        if status >= 400 or failed or not self.done:
            row['finish'] = 'error'
        if row.get('prompt_read') is not None and row.get('reused') is not None:
            row['prompt_tokens'] = row['prompt_read'] + row['reused']
        self.history.append(self.identity, row)


def observe_owned(started):
    """Only a verified llama.cpp listener can produce this backend's history."""
    try:
        from ai_ninfer import owned_process
        owned = owned_process()
        if owned and owned[0].name().lower() == 'llama-server.exe':
            return Observation((owned[0].pid, owned[0].create_time()), started=started)
    except Exception:
        pass
    return None


class SlotRates:
    """Measured counter deltas, reset at every backend or task boundary."""
    def __init__(self):
        self.identity = None
        self.previous = {}

    def sample(self, identity, slots, now):
        if self.identity != identity:
            self.previous = {}
            self.identity = identity
        current, result = {}, {}
        for slot in slots:
            if not isinstance(slot, dict) or not slot.get('is_processing'):
                continue
            sid, task = number(slot.get('id')), number(slot.get('id_task'))
            if sid is None or task is None:
                continue
            next_token = slot.get('next_token') or []
            generated = number(next_token[0].get('n_decoded')) if isinstance(next_token, list) and next_token and isinstance(next_token[0], dict) else None
            processed = number(slot.get('n_prompt_tokens_processed'))
            current[sid] = (task, now, processed, generated)
            old = self.previous.get(sid)
            rates = dict(tok_s=None, prefill_tok_s=None)
            if old and old[0] == task and .05 <= now-old[1] <= 30:
                for key, before, after in [('prefill_tok_s', old[2], processed), ('tok_s', old[3], generated)]:
                    if before is not None and after is not None and after >= before:
                        rates[key] = (after-before)/(now-old[1])
            result[sid] = rates
        self.previous = current
        return result
