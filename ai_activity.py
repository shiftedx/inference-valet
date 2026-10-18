"""Read-only, privacy-preserving backend activity and optional local probes."""
import csv
import io
import ipaddress
import json
import math
import ntpath
import subprocess
import urllib.parse
import urllib.request


def _mapping(value):
    return value if isinstance(value, dict) else {}


def _number(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0 else None


def _count(value):
    value = _number(value)
    return int(value) if value is not None and value == int(value) else None


def read_gpu_processes(nvidia_smi):
    """Observe GPU 0 compute processes; names never establish ownership."""
    try:
        result = subprocess.run([str(nvidia_smi), '--id=0',
            '--query-compute-apps=pid,process_name,used_gpu_memory',
            '--format=csv,noheader,nounits'], capture_output=True, text=True,
            timeout=2, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if result.returncode:
            raise ValueError('query failed')
        processes = []
        for row in csv.reader(io.StringIO(result.stdout)):
            if not row:
                continue
            if len(row) != 3:
                raise ValueError('invalid row')
            pid = int(row[0].strip())
            if pid <= 0:
                raise ValueError('invalid pid')
            try:
                memory = _number(float(row[2].strip()))
            except ValueError:
                memory = None  # Windows WDDM commonly reports N/A.
            name = ntpath.basename(row[1].strip())
            name = ''.join(c for c in name if c.isprintable())[:80] or 'Unknown process'
            processes.append(dict(pid=pid, name=name, memory_mib=memory))
        return dict(available=True, processes=processes, error=None)
    except (OSError, ValueError, subprocess.SubprocessError):
        return dict(available=False, processes=[], error='GPU process details unavailable')


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def read_comfy(url):
    """Read only queue counts from explicitly configured loopback ComfyUI."""
    base = dict(state='unavailable', title='Unavailable', running=None, queued=None,
                detail='ComfyUI queue could not be read')
    if not url:
        return {**base, 'state': 'not_configured', 'title': 'Not configured',
                'detail': 'Set a local ComfyUI URL to observe its queue'}
    try:
        parsed = urllib.parse.urlsplit(url)
        hostname = parsed.hostname
        local = hostname == 'localhost'
        if not local:
            try:
                local = ipaddress.ip_address(hostname).is_loopback
            except (ValueError, TypeError):
                local = False
        if (parsed.scheme != 'http' or not local or parsed.username is not None
                or parsed.password is not None or parsed.query or parsed.fragment
                or parsed.path not in ('', '/')):
            raise ValueError('invalid local URL')
        port = parsed.port  # Validate malformed or out-of-range ports.
        target = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, '/queue', '', ''))
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
        with opener.open(target, timeout=1) as reply:
            payload = reply.read(256 * 1024 + 1)
        if len(payload) > 256 * 1024:
            raise ValueError('queue response too large')
        queue = json.loads(payload)
        if not isinstance(queue, dict) or not all(isinstance(queue.get(k), list) for k in ('queue_running', 'queue_pending')):
            raise ValueError('invalid queue')
        running, queued = len(queue['queue_running']), len(queue['queue_pending'])
        return dict(state='busy' if running or queued else 'idle',
                    title='Working' if running or queued else 'Idle', running=running,
                    queued=queued, detail=f'{running} active · {queued} queued')
    except (OSError, ValueError, TypeError):
        return base


def build_activity(status, metrics, demand, hardware, processes, owned,
                   verified=True, health=None, options=None):
    """Derive a snapshot without mutations or transferring raw request data.

    Counts from demand are in-flight admissions, never an inferred queue count.
    GPU headroom rules apply only before load, avoiding self-blocking a resident
    Strata model. Process names are observations, not authority or VRAM owners.
    """
    status, metrics, demand, hardware = map(_mapping, (status, metrics, demand, hardware))
    options = _mapping(options)
    live = _mapping(metrics.get('live'))
    activity = _mapping(status.get('activity'))
    owned = set(owned or ())
    running = _count(live.get('running'))
    queued = _count(live.get('queued'))
    admissions = [_count(activity.get('in_flight')), _count(demand.get('active_requests'))]
    known_admissions = [value for value in admissions if value is not None]
    in_flight = max(known_admissions) if known_admissions else None
    recent = []
    requests = metrics.get('requests')
    for row in requests[:12] if isinstance(requests, list) else []:
        if not isinstance(row, dict):
            continue
        finish = row.get('finish')
        # Never pass arbitrary server messages, prompt text or client labels.
        finish = finish if finish in ('stop', 'length', 'cancelled', 'canceled', 'cancel', 'error', 'failed', 'complete', 'completed', 'eos') else 'finished'
        duration = _number(row.get('duration_s'))
        if duration is None:
            total_ms = _number(row.get('total_ms'))
            if total_ms is not None:
                duration = total_ms / 1000
            else:
                prompt_ms, decode_ms = _number(row.get('prompt_ms')), _number(row.get('decode_ms'))
                if prompt_ms is not None and decode_ms is not None:
                    duration = (prompt_ms + decode_ms) / 1000
        recent.append(dict(time=_number(row.get('time')), finish=finish,
                           tokens=_count(row.get('output_tokens', row.get('generated'))), duration_s=duration))
    blockers = []
    if demand.get('games'):
        blockers.append('Gaming priority is active')
    elif demand.get('unknown') is True:
        blockers.append('Game activity could not be verified')
    if status.get('loaded') is False:
        retry = _number(demand.get('load_retry_seconds'))
        if retry:
            blockers.append('Waiting for the model load retry cooldown')
        # Allocations may already belong to the admitted model warm-up.
        # Admission counts are observations, never summed or treated as a queue.
        if not in_flight:
            used, total = _number(hardware.get('gpu_mem_used')), _number(hardware.get('gpu_mem_total'))
            util = _number(hardware.get('gpu_util'))
            if util is not None and util > options.get('max_gpu_utilization', 20):
                blockers.append('GPU workload is above the load limit')
            free = (total - used) / 2**20 if used is not None and total is not None and total >= used else None
            if ((used is not None and used / 2**20 > options.get('max_vram_used_mib', 4096))
                    or (free is not None and free < options.get('min_free_vram_mib', 24000))):
                blockers.append('GPU memory headroom is below the load limit')
            ram, commit = _number(hardware.get('ram_free_gib')), _number(hardware.get('commit_free_gib'))
            if ((ram is not None and ram < options.get('min_ram_gib', 26))
                    or (commit is not None and commit < options.get('min_commit_gib', 35))):
                blockers.append('System memory or commit headroom is below the load limit')
    blockers = list(dict.fromkeys(blockers))
    gpu_data = processes if isinstance(processes, dict) else dict(available=True, processes=processes or [])
    observed = [p for p in gpu_data.get('processes', []) if isinstance(p, dict) and p.get('pid') not in owned]
    gpu_note = 'GPU process details unavailable' if not gpu_data.get('available') else 'No other compute processes reported on GPU 0'
    if observed:
        gpu_note = f'{len(observed)} other compute process' + ('es' if len(observed) != 1 else '') + ' reported on GPU 0'
    gpu_processes = []
    for row in observed[:8]:
        raw_name = row.get('name') or row.get('process_name') or 'Unknown process'
        name = ntpath.basename(raw_name) if isinstance(raw_name, str) else 'Unknown process'
        name = ''.join(c for c in name if c.isprintable())[:80] or 'Unknown process'
        gpu_processes.append(dict(pid=_count(row.get('pid')), name=name,
                                  memory_mib=_number(row.get('memory_mib'))))
    if status.get('loaded') is False:
        used, total = _number(hardware.get('gpu_mem_used')), _number(hardware.get('gpu_mem_total'))
        if used is None or total is None or total < used or total == 0:
            gpu_note = 'GPU headroom unavailable · ' + gpu_note
        else:
            gpu_note = f'{(total-used)/2**30:.1f} / {total/2**30:.1f} GiB free · ' + gpu_note
            if 'GPU memory headroom is below the load limit' in blockers:
                gpu_note += f" · Load requires {options.get('min_free_vram_mib', 24000)/1024:.1f} GiB free and ≤ {options.get('max_vram_used_mib', 4096)/1024:.1f} GiB used"
            if 'GPU workload is above the load limit' in blockers:
                gpu_note += f" · GPU {hardware['gpu_util']:g}% (load limit {options.get('max_gpu_utilization', 20):g}%)"
        # Newer lifecycle status wins over the earlier metrics sample.
        running, queued = None, None
    elif running is None:
        if live.get('state') in ('reading', 'generating'):
            running = 1
        elif live.get('state') in ('idle', 'ready') and in_flight == 0:
            running = 0
    if not owned:
        state, title, detail = ('unavailable', 'Unverified backend', 'A responding endpoint has no verified Valet process') if status or health else ('offline', 'Offline', 'Strata server is not running')
    elif not verified:
        state, title, detail = 'unavailable', 'Unverified backend', 'The endpoint could not be matched to the managed Strata server'
    elif not status:
        state, title, detail = 'unavailable', 'Status unavailable', 'Waiting for a fresh Strata status response'
    elif demand.get('games'):
        state, title, detail = 'blocked', 'Game priority', 'Gaming priority is active'
    elif demand.get('unknown') is True:
        state, title, detail = 'blocked', 'Game status unavailable', 'Game activity could not be verified'
    elif status.get('loaded') is False:
        if blockers:
            state, title, detail = 'blocked', 'Waiting for resources', blockers[0]
        elif in_flight:
            state, title, detail = 'busy', 'Preparing request', 'Request admitted · waiting for model readiness'
        else:
            state, title, detail = 'unloaded', 'Unloaded', 'Model will load on the next admitted request'
    elif live.get('state') in ('loading', 'reading', 'generating'):
        state = live['state']
        title, detail = {'loading': ('Loading model', 'Strata is preparing the model'),
                         'reading': ('Reading prompt', 'Strata is processing input'),
                         'generating': ('Generating', 'Strata is producing output')}[state]
    elif status.get('loaded') is not True:
        state, title, detail = 'unavailable', 'Status unavailable', 'Model readiness could not be verified'
    elif (running or queued or in_flight):
        state, title, detail = 'busy', 'Working', 'Requests are in flight; generation stage is not available'
    elif live.get('state') in ('idle', 'ready') or (in_flight == 0):
        state, title, detail = 'ready', 'Ready', 'Strata is loaded and idle'
    else:
        state, title, detail = 'busy', 'Loaded', 'Request activity is not available'
    return dict(state=state, title=title, detail=detail, blockers=blockers,
                gpu_note=gpu_note, gpu_processes=gpu_processes,
                gpu_process_count=len(observed) if gpu_data.get('available') else None,
                recent=recent, running=running, queued=queued,
                in_flight=in_flight)
