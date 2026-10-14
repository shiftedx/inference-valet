"""Bounded local diagnostics; never include request bodies or credentials."""
import json
import os
import time
import uuid
from ai_config import STATE_DIR

def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        temp.write_text(json.dumps(value, indent=2), encoding='utf-8')
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)

def record_issue(code, message, **details):
    issue = dict(code=code, message=str(message)[:1800], checked_at=time.time(),
                 owner_pid=os.getpid(), details=details)
    try:
        write_json(STATE_DIR / 'last-issue.json', issue)
        # Independent immutable events avoid tray/server append races. Keep 100 events.
        events = STATE_DIR / 'issues'
        write_json(events / (str(time.time_ns()) + '-' + uuid.uuid4().hex + '.json'), issue)
        for old in sorted(events.glob('*.json'))[:-100]:
            old.unlink(missing_ok=True)
    except OSError:
        pass  # Disk failure must not change admission or lose the HTTP error message.
    return issue

def failure_code(message):
    text = str(message).lower()
    if any(s in text for s in ('cuda out of memory', 'cuda_error_out_of_memory', 'out of device memory', 'cudamalloc', 'insufficient vram')):
        return 'vram_allocation_failed'
    if '0xc0000005' in text or 'access violation' in text:
        return 'native_crash'
    return 'startup_failed'
