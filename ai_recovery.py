"""Restart a missing API listener, never a live process or GPU model."""
import collections
import threading
import json
from ai_issues import write_json


class RecoveryPolicy:
    def __init__(self, window=600, limit=3, path=None):
        self.window, self.limit = window, limit
        self.attempts = collections.deque()
        self.retry_at = 0
        self.pending = False
        self.lock = threading.RLock()
        self.path = path
        if path:
            try:
                state = json.loads(path.read_text())
                self.attempts.extend(float(t) for t in state['attempts'])
                self.retry_at = float(state['retry_at'])
            except FileNotFoundError: pass
            except (ValueError, KeyError, TypeError):
                # Corrupt recovery state fails closed until explicit Load.
                self.retry_at = float('inf')

    def save(self):
        if self.path:
            write_json(self.path, dict(attempts=list(self.attempts), retry_at=self.retry_at))

    def decide(self, now, armed, owned_live, listener, games, action_busy):
        with self.lock:
            while self.attempts and now-self.attempts[0] >= self.window:
                self.attempts.popleft()
            if not armed: return False, 'API recovery paused by manual Unload'
            if owned_live or listener: return False, 'API listener running or owned process still alive'
            # Recovery starts only the lazy HTTP listener; its request/load guard
            # still refuses games and unknown state before any GPU work.
            if self.pending or action_busy: return False, 'API recovery already in progress'
            if len(self.attempts) >= self.limit:
                return False, 'API recovery paused: repeated crashes; use Load model to retry'
            if self.retry_at == float('inf'): return False, 'API recovery paused: unreadable recovery state; use Load model to retry'
            if now < self.retry_at:
                return False, f'API recovery retry in {int(self.retry_at-now)+1}s'
            return True, 'API recovery: restoring unloaded listener'

    def begin(self, now):
        with self.lock:
            if self.pending: return False
            self.pending = True
            self.attempts.append(now)
            self.retry_at = now + (5, 15, 60)[min(len(self.attempts)-1, 2)]
            self.save()
            return True

    def finished(self):
        with self.lock: self.pending = False

    def reset(self):
        with self.lock:
            self.pending = False
            self.attempts.clear()
            self.retry_at = 0
            self.save()


def listener_present(socket_module, port=8080):
    with socket_module.socket() as sock:
        sock.settimeout(.3)
        return sock.connect_ex(('127.0.0.1', port)) == 0
