"""Bounded, read-only profiling of verified Valet/Strata processes. No prompts or GPU loads."""
import argparse
import importlib.util
import json
import math
import pathlib
import statistics
import sys
import time
import psutil

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location('profile_launcher', ROOT / 'ai-launcher.py')
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)

def positive(value):
    result = float(value)
    if not math.isfinite(result) or result <= 0:
        raise argparse.ArgumentTypeError('Use a positive finite value')
    return result

def processes():
    result = {}
    try:
        state = json.loads(launcher.GUI_STATE.read_text(encoding='utf-8'))
        proc = psutil.Process(state['pid'])
        script = ROOT / 'ai-launcher.py'
        if (abs(proc.create_time()-state['created']) < .01
                and launcher.same(proc.exe(), state['exe'])
                and launcher.same(state['script'], script)
                and any(launcher.same(arg, script) for arg in proc.cmdline()[1:])):
            result['tray'] = proc
    except (OSError, ValueError, KeyError, psutil.Error):
        pass
    demand = launcher.read_demand_status()
    if demand:
        try: result['strata_server'] = psutil.Process(demand['owner_pid'])
        except psutil.Error: pass
    return result, demand

def summarize(samples):
    summary = {}
    for role in ('tray', 'strata_server'):
        rows = [s['processes'][role] for s in samples if role in s['processes']]
        cpu = sorted(r['one_core_percent'] for r in rows if r['one_core_percent'] is not None)
        idle_cpu = [s['processes'][role]['one_core_percent'] for s in samples
                    if role in s['processes'] and s.get('active_requests') == 0
                    and s['processes'][role]['one_core_percent'] is not None]
        segments = {}
        for row in rows:
            segments.setdefault((row['pid'], row['created']), []).append(row)
        summary[role] = dict(samples=len(rows),
            cpu_mean=statistics.mean(cpu) if cpu else None,
            idle_cpu_mean=statistics.mean(idle_cpu) if idle_cpu else None,
            cpu_p95=cpu[max(0, math.ceil(.95*len(cpu))-1)] if cpu else None,
            segments=[dict(pid=key[0], created=key[1], samples=len(group),
                rss_growth_mib=group[-1]['rss_mib']-group[0]['rss_mib'],
                rss_max_mib=max(r['rss_mib'] for r in group),
                threads_min=min(r['threads'] for r in group),
                threads_max=max(r['threads'] for r in group),
                handles_growth=group[-1]['handles']-group[0]['handles'])
                for key,group in segments.items()])
    return summary

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--minutes', type=positive, default=60)
    parser.add_argument('--interval', type=positive, default=10)
    parser.add_argument('--output', type=pathlib.Path, required=True)
    args = parser.parse_args()
    if args.minutes > 1440 or args.interval < 1:
        parser.error('Duration must be <= 1440 minutes and interval >= 1 second')
    args.output.mkdir(parents=True, exist_ok=True)
    samples, previous = [], {}
    started = time.monotonic()
    deadline = started + args.minutes*60
    next_sample = started
    with (args.output / 'samples.jsonl').open('w', encoding='utf-8') as log:
        while True:
            now = time.monotonic()
            owned, demand = processes()
            sample = dict(at=time.time(), elapsed_seconds=now-started,
                active_requests=demand.get('active_requests'), loaded=demand.get('loaded'),
                game_busy=bool(demand.get('games')), guard_unknown=demand.get('unknown'),
                processes={})
            for role,proc in owned.items():
                try:
                    created = proc.create_time()
                    key = role, proc.pid, created
                    with proc.oneshot():
                        cpu = proc.cpu_times(); total = cpu.user+cpu.system
                        prior = previous.get(key)
                        percent = max(0, (total-prior[1])/(now-prior[0])*100) if prior and now > prior[0] else None
                        io = proc.io_counters()
                        sample['processes'][role] = dict(pid=proc.pid, created=created,
                            one_core_percent=percent, rss_mib=proc.memory_info().rss/2**20,
                            threads=proc.num_threads(), handles=proc.num_handles(),
                            read_bytes=io.read_bytes, write_bytes=io.write_bytes)
                    previous[key] = now, total
                except (OSError, psutil.Error): pass
            samples.append(sample)
            log.write(json.dumps(sample)+'\n');log.flush()
            if now >= deadline: break
            next_sample += args.interval
            time.sleep(max(0, min(next_sample, deadline)-time.monotonic()))
    report = dict(duration_seconds=time.monotonic()-started, interval_seconds=args.interval,
        cpu_units='Percent of one logical CPU core; process CPU only',
        missing_tray_samples=sum('tray' not in s['processes'] for s in samples),
        missing_server_samples=sum('strata_server' not in s['processes'] for s in samples),
        processes=summarize(samples))
    (args.output/'summary.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2), flush=True)

if __name__ == '__main__': main()
