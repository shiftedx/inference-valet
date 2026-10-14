# Recovery and startup diagnostics

- Keep Valet running in the tray; existing sign-in task starts it.
- Missing on-demand Strata listener: inspect every 10 seconds; restore unloaded HTTP listener independently of the idle timer.
- Refuse recovery while a verified engine/server process or another application owns the port; inspect the log if an owned process is alive but its API is unavailable.
- Recover at most three times per 10-minute window; 5/15/60-second minimum retry delays; persist attempts across tray restarts.
- Load model: reset recovery limits. Manual Unload: disarm immediate recovery; retain the optional idle restore with the selected 5–30-minute delay.
- Restore when idle: controls idle profile restart in eager mode; on-demand listeners load their engines on a request; listener recovery remains armed until manual Unload.
- Retain game admission policy, native HTTP authentication, context, vision and output budgets.
- VRAM/RAM admission failures: show measured available memory and configured thresholds; never evict other applications.
- Failed native load: clean only the service's partial engines; return HTTP 503 and a retry delay; wait 30 seconds before another load attempt.
- Tray notifications: suppress consecutive duplicate issues; dashboard displays the current load failure.
- State directory: demand-status.json (live owner and load issue), last-issue.json (historical latest issue), issues/*.json (latest 100 events), recovery-state.json (retry history), timestamped startup logs.
- Historical issues remain after successful recovery; live demand status clears the load issue after a successful load.
- Python fault handler: enabled on future starts. Access violations are reported as native crashes; classify VRAM OOM only when the error identifies a GPU allocation failure.

```powershell
.\.venv\Scripts\python.exe ai-launcher.py --diagnose
```

- Diagnostics command: read-only; report listener, verified processes, health, fresh demand status and issue history.
- Rollback: exit tray, restore backed-up Python files, start tray; apply server-side guard rollback at the next idle listener restart.

## External Strata integration

- Set on_demand.enabled only with a launch_strata_profile.py supporting --on-demand and a managed server loading this hook before server.main():

```python
import os, sys
valet = os.environ.get('STRATA_VALET_ROOT')
if valet:
    sys.path.insert(0, valet)
    from ai_demand import install
    install(server)
```

- Keep the native Service unloaded initially; POST /load or generation uses its native lifecycle FIFO.
- Configure optional loopback comfyui_url only when that queue endpoint is available; queue checks are read-only.
- Backend-native before_load hooks can have external side effects; audit those hooks separately.
- Headroom thresholds are admission limits, not predictions of the selected model's final memory use.
- Native HTTP integration tests require the external Strata checkout; policy/recovery tests use simulated resources.

## Idle overhead

- Hidden dashboard/flyout: skip detailed hardware/performance collection and graph redraws; retain endpoint/status checks every 10 seconds.
- Show dashboard/flyout: resume detailed telemetry every 2 seconds immediately.
- Reuse fresh, verified server game status for tray decisions; stale/missing status falls back to game/process inspection.
- Inspect process names first; verify full executable and script paths only for possible backend processes. Names alone never establish ownership.
- Hidden idle UI mailbox: poll every 250 ms; visible UI/actions: every 100 ms.
- Keep game admission/cancellation checks at 1 second; publish status changes immediately, unchanged heartbeat every 2 seconds.

## Worker reuse and profiling

- Reuse one telemetry worker and one recovery-policy worker; retain independent lanes and single-flight polling.
- Keep lifecycle actions separate from polling so model loading cannot exhaust the polling workers.
- Exit: cancel queued polling, stop submitting new work, let bounded in-flight reads finish without blocking the Tk UI.
- Profile only verified tray/server identities; retain separate measurements across PID changes; exclude prompts, credentials and model contents.
- Sample CPU, RSS, threads, handles, I/O counters and request/game activity; use idle CPU separately from overall CPU.
- CPU units: percent of one logical CPU core; exclude other processes and profiler overhead.

```powershell
.\.venv\Scripts\python.exe scripts/profile-performance.py --minutes 60 --interval 10 --output C:/path/to/profile-output
```

- Results: samples.jsonl and summary.json. Keep profile output outside the Git checkout.
- Finite run; maximum 24 hours; minimum 1-second sampling; no startup registration or model lifecycle changes.
