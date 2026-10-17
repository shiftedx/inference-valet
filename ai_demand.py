"""Admission policy for the managed Strata HTTP server; no proxy or game hooks."""
import json
import os
import psutil
import pathlib
import subprocess
import threading
import time
import urllib.request

from ai_config import CONFIG, NVIDIA_SMI, STATE_DIR, STRATA_ROOT
from ai_idle import GameDetector, Settings
from ai_issues import record_issue, failure_code

DEFAULTS = dict(poll_seconds=1, grace_seconds=5, cooldown_seconds=30,
                max_pending=8, request_timeout_seconds=600, load_timeout_seconds=300,
                max_gpu_utilization=20, max_vram_used_mib=4096,
                min_free_vram_mib=24000, min_ram_gib=26, min_commit_gib=35, load_retry_seconds=30)


class Guard:
    def __init__(self, detector=None, gpu=None, clock=time.monotonic, options=None):
        self.options = {**DEFAULTS, **CONFIG.get('on_demand', {}), **(options or {})}
        for key, value in self.options.items():
            if key in DEFAULTS and (isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0):
                raise ValueError('Invalid on_demand setting: ' + key)
        if self.options['max_pending'] < 1 or self.options['poll_seconds'] < .25:
            raise ValueError('max_pending >= 1 and poll_seconds >= .25 required')
        self.detector = detector or GameDetector()
        self.gpu = gpu or self.resources
        self.clock = clock
        self.lock = threading.RLock()
        self.games = []
        self.unknown = True
        self.reason = 'Checking game activity'
        self.game_since = None
        self.safe_after = 0
        self.load_retry_at = 0
        self.last_load_error = None
        self.load_issue = None
        self.resource_snapshot = None

    def blocked(self, code, message):
        with self.lock:
            if not self.load_issue or self.load_issue['message'] != message:
                self.load_issue = record_issue(code, message, resources=self.resource_snapshot)
        return message

    def failed_load(self, exc):
        with self.lock:
            self.last_load_error = str(exc)[:1800]
            self.load_retry_at = self.clock() + self.options['load_retry_seconds']
        self.blocked(failure_code(exc), 'Strata load failed: ' + str(exc)[:1500])


    def sample(self):
        with self.lock:
            try:
                settings = Settings(STATE_DIR / 'idle-settings.json').read()
                games = self.detector.running(settings['extra_games'], strict=True)
                now = self.clock()
                if games:
                    if self.game_since is None: self.game_since = now
                    self.safe_after = now + self.options['cooldown_seconds']
                else:
                    self.game_since = None
                self.games, self.unknown = games, False
                self.reason = 'Gaming busy: ' + ', '.join(games[:3]) if games else 'Waiting for request'
            except Exception as exc:
                self.unknown = True
                self.reason = 'Game state unknown: ' + str(exc)
            return self.reason

    def admission(self):
        with self.lock:
            if self.unknown or self.games: return self.reason
            if self.clock() < self.safe_after: return 'Gaming cooldown; retry shortly'
        return None

    def load_reason(self):
        self.sample()
        if reason := self.admission(): return reason
        if self.clock() < self.load_retry_at:
            return 'Strata load retry cooldown: ' + (self.last_load_error or 'previous load failed')
        try:
            # Optional read-only ComfyUI queue. Never interrupt or free its models.
            url = self.options.get('comfyui_url')
            if url:
                if not url.startswith(('http://127.0.0.1:', 'http://localhost:')):
                    raise ValueError('ComfyUI status URL must be loopback')
                with urllib.request.urlopen(url.rstrip('/') + '/queue', timeout=2) as reply:
                    queue = json.load(reply)
                if queue.get('queue_running') or queue.get('queue_pending'):
                    return 'ComfyUI generation has priority'
            data = self.gpu()
            self.resource_snapshot = data
            o = self.options
            if data['util'] > o['max_gpu_utilization']: return self.blocked('gpu_busy', f"GPU workload busy: {data['util']:g}% utilization; limit {o['max_gpu_utilization']:g}%")
            if data['used'] > o['max_vram_used_mib'] or data['free'] < o['min_free_vram_mib']:
                return self.blocked('vram_headroom', f"VRAM headroom limited: {data['free']:g} MiB free (need >= {o['min_free_vram_mib']:g}); {data['used']:g} MiB used (limit {o['max_vram_used_mib']:g}); retained models are left untouched")
            if data['ram'] < o['min_ram_gib'] or data['commit'] < o['min_commit_gib']:
                return self.blocked('ram_headroom', f"Insufficient RAM or Windows commit headroom: RAM {data['ram']:.1f} GiB (need {o['min_ram_gib']:g}); commit {data['commit']:.1f} GiB (need {o['min_commit_gib']:g})")
        except Exception as exc:
            return self.blocked('resource_unknown', 'Resource state unknown: ' + str(exc))
        return None

    @staticmethod
    def resources():
        import ctypes
        import psutil
        output = subprocess.check_output([NVIDIA_SMI, '--id=0',
                    '--query-gpu=utilization.gpu,memory.used,memory.free',
                    '--format=csv,noheader,nounits'], text=True, timeout=3,
                    creationflags=subprocess.CREATE_NO_WINDOW)
        util, used, free = map(float, output.strip().split(','))
        class Perf(ctypes.Structure):
            _fields_ = [('cb', ctypes.c_ulong)] + [(k, ctypes.c_size_t) for k in
                ('CommitTotal','CommitLimit','CommitPeak','PhysicalTotal','PhysicalAvailable',
                 'SystemCache','KernelTotal','KernelPaged','KernelNonpaged','PageSize')] + [
                 (k, ctypes.c_ulong) for k in ('HandleCount','ProcessCount','ThreadCount')]
        perf = Perf(); perf.cb = ctypes.sizeof(perf)
        if not ctypes.windll.psapi.GetPerformanceInfo(ctypes.byref(perf), perf.cb):
            raise OSError('Windows commit counter unavailable')
        return dict(util=util, used=used, free=free, ram=psutil.virtual_memory().available/2**30,
                    commit=(perf.CommitLimit-perf.CommitTotal)*perf.PageSize/2**30)


def install(server, guard=None):
    """Extend native handlers, retaining native authentication, SSE and cancellation."""
    guard = guard or Guard()
    original_factory = server.make_handler
    paths = {'/load', '/v1/load', '/v1/chat/completions', '/v1/completions',
             '/v1/responses', '/v1/messages', '/chat', '/completion'}

    def factory(svc):
        base = original_factory(svc)
        pending = threading.BoundedSemaphore(int(guard.options['max_pending']))
        active, mutex = {}, threading.RLock()
        native_ensure, native_run = svc.ensure_loaded, svc.run
        owner_pid, owner_created = os.getpid(), psutil.Process().create_time()
        last_status, last_status_at = None, float('-inf')

        def ensure():
            if reason := guard.admission(): raise server.GpuBusy(reason, retry_after=15)
            if not svc.loaded() or svc._vision_down():
                if reason := guard.load_reason(): raise server.GpuBusy(reason, retry_after=15)
            try:
                if not svc.loaded():
                    from ai_next_load import apply_pending_memory
                    apply_pending_memory(svc, STRATA_ROOT)
                native_ensure()
            except Exception as exc:
                if reason := guard.admission(): raise server.GpuBusy(reason, retry_after=15) from None
                guard.failed_load(exc)
                # The caller holds the native lifecycle FIFO; clean only this Service.
                for engine in (svc.engine, svc.vision):
                    if engine is not None:
                        try: engine.unload()
                        except Exception: pass
                raise server.GpuBusy(guard.load_issue['message'],
                    retry_after=max(1, int(guard.options['load_retry_seconds']))) from None
            with guard.lock:
                guard.load_issue = None
                guard.last_load_error = None
                guard.load_retry_at = 0
            if reason := guard.admission():
                # Caller owns the lifecycle FIFO; no competing unload/load mutation.
                svc.engine.unload()
                if svc.vision is not None: svc.vision.unload()
                raise server.GpuBusy(reason, retry_after=15)
        svc.ensure_loaded = ensure

        def load():
            deadline = guard.clock() + guard.options['load_timeout_seconds']
            while not svc.fifo.acquire(timeout=.25):
                if reason := guard.admission(): raise server.GpuBusy(reason, retry_after=15)
                if guard.clock() >= deadline: raise server.GpuBusy('Load queue deadline exceeded', retry_after=15)
            try:
                svc.last_request_at = time.time()
                ensure()
            finally: svc.fifo.release()
        svc.load = load

        def run(*args, **kwargs):
            cancel = kwargs.get('cancel') or (args[6] if len(args) > 6 else None)
            # Native signature: run(ids, thinking, tools, max_new, sampling, cancel,...).
            if len(args) > 5: cancel = args[5]
            try:
                for item in native_run(*args, **kwargs):
                    if cancel is not None and getattr(cancel, 'valet_reason', None):
                        raise server.EngineDied(cancel.valet_reason)
                    yield item
            except server.EngineDied:
                if cancel is not None and getattr(cancel, 'valet_reason', None):
                    raise server.EngineDied(cancel.valet_reason) from None
                raise
            if cancel is not None and getattr(cancel, 'valet_reason', None):
                raise server.EngineDied(cancel.valet_reason)
        svc.run = run

        def terminate_owned():
            # Popen handles belong to this Service, never look up processes by name/port.
            for engine in (svc.engine, svc.vision):
                proc = getattr(engine, 'proc', None)
                if proc is not None and proc.poll() is None: proc.terminate()

        def tick():
            nonlocal last_status, last_status_at
            guard.sample()
            now = guard.clock()
            overdue = guard.game_since is not None and now-guard.game_since >= guard.options['grace_seconds']
            with mutex:
                for record in active.values():
                    expired = now-record['started'] >= guard.options['request_timeout_seconds']
                    if overdue or expired:
                        record['reason'] = 'Inference cancelled: gaming priority' if overdue else 'Inference request deadline exceeded'
                        if record.get('cancel') is not None:
                            record['cancel'].valet_reason = record['reason']
                            record['cancel'].set()
                loading = not svc.loaded() and bool(active)
                load_expired = loading and any(now-r['started'] >= guard.options['load_timeout_seconds'] for r in active.values())
            if overdue or load_expired:
                # Cancellation is cooperative first; terminate only this server's engines
                # if a prompt/load is still blocking the native unload FIFO.
                result = svc.unload()
                if result == 'busy' or loading: terminate_owned()
            with mutex: count = len(active)
            status = dict(reason=guard.reason, games=guard.games, unknown=guard.unknown,
                          active_requests=count, loaded=svc.loaded(), checked_at=time.time(),
                          owner_pid=owner_pid, owner_created=owner_created,
                          load_issue=guard.load_issue, resources=guard.resource_snapshot,
                          load_retry_seconds=max(0, round(guard.load_retry_at-now)))
            if guard.load_issue and not guard.admission(): status['reason'] = guard.load_issue['message']
            content = json.dumps({key:value for key,value in status.items() if key != 'checked_at'})
            if content == last_status and now-last_status_at < 2: return
            try:
                STATE_DIR.mkdir(parents=True, exist_ok=True)
                temp = STATE_DIR / 'demand-status.tmp'
                temp.write_text(json.dumps(status), encoding='utf-8')
                temp.replace(STATE_DIR / 'demand-status.json')
                last_status, last_status_at = content, now
            except OSError: pass

        def monitor():
            while True:
                try: tick()
                except Exception as exc:
                    with guard.lock: guard.unknown = True; guard.reason = 'Guard unavailable: ' + str(exc)
                time.sleep(guard.options['poll_seconds'])
        guard.sample()
        threading.Thread(target=monitor, daemon=True).start()

        class Handler(base):
            def do_POST(self):
                path = self.path.split('?')[0].rstrip('/')
                if path not in paths: return super().do_POST()
                # Preserve the native authentication / foreign-origin checks before admission.
                if not self._authorized() or (path.startswith('/v1/') and self._foreign_page()): return
                reason = guard.admission()
                acquired = False if reason else pending.acquire(blocking=False)
                if reason or not acquired:
                    self.close_connection = True
                    return self._json(503, {'error': {'type': 'server_error', 'code': 'gaming_busy' if reason else 'queue_full',
                        'message': reason or 'Inference queue full; retry shortly'}}, headers={'Retry-After': 15})
                self.valet_record = dict(started=guard.clock(), cancel=None, reason=None)
                with mutex: active[id(self)] = self.valet_record
                try: return super().do_POST()
                finally:
                    with mutex: active.pop(id(self), None)
                    pending.release()

            def _watch_client(self, cancel):
                record = getattr(self, 'valet_record', None)
                if record is not None:
                    with mutex:
                        record['cancel'] = cancel
                        if record['reason']:
                            cancel.valet_reason = record['reason']; cancel.set()
                return super()._watch_client(cancel)

            def _body(self):
                body = super()._body()
                if self.path.split('?')[0].rstrip('/') in paths:
                    try: req = json.loads(body or b'{}')
                    except ValueError: return body # Native malformed-body response.
                    if isinstance(req, dict) and req.get('model') not in (None, *svc.model_names()):
                        raise server.BadBody(404, 'model not found')
                return body
        Handler.valet_tick = staticmethod(tick)
        return Handler
    server.make_handler = factory
    return guard
