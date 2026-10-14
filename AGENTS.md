# Agent guide

Windows tray controller for external Strata: Tkinter/ttk UI, verified process control, game/resource admission, optional on-demand loading and idle restore. Read [setup](docs/SETUP.md), [performance](docs/PERFORMANCE.md) and [backend contract](docs/BACKENDS.md) before configuring a host.

## Layout

| Path | Responsibility |
|---|---|
| `ai-launcher.py` | Dashboard/tray, IPC, verified start/stop, recovery scheduling |
| `ai_config.py`, `config.example.json` | Local config; paths relative to config directory |
| `ai_profiles.py`, `ai_profile_editor.py` | Preset mapping; validated, backed-up external profile edits |
| `ai_widgets.py`, `ai_branding.py`, `ai_telemetry.py` | Shared font/geometry tokens, app identity, read-only telemetry |
| `ai_idle.py`, `ai_demand.py`, `ai_recovery.py` | Game discovery, idle delay, native admission, listener recovery |
| `backends/strata/` | Managed wrappers and placeholder profiles; install outside this repo |
| `scripts/`, `tests/` | Setup/startup/integration; unit, native HTTP and Tk workflow checks |

## Configure a host

1. Inspect Windows/Python/Tk, GPU, RAM, free SSD space, page-file allocation and current processes; preserve requests and existing profiles. Process names and port 8080 alone never establish ownership.
2. Run `scripts/setup.ps1`; it creates Valet's `.venv`, local `config.json`, Desktop/Start shortcuts and app identity. Supply `-Python C:\path\python.exe` when `py` is absent.
3. Install upstream Strata separately at `<strata_root>/Strata/`. Install wrappers with `scripts/install-strata-integration.py`; correct placeholder paths before loading. Never overwrite a live managed launcher: its stop record verifies script hashes.
4. Set `strata_root` / optional `strata_python`, valid `enabled_profiles` and `state_dir`. Select only existing profiles. Preserve pack/model-part/MTP/tokenizer/vision/DLL paths; use absolute backend paths. Do not copy another host's drive letters.
5. Verify **available physical RAM and commit headroom** separately. Read the page-file guide. Larger commit capacity does not fix RAM/VRAM pressure or guarantee more tokens/s. Never silently change page-file settings, admission thresholds or calibrated tuning.
6. Choose eager load or `on_demand.enabled=true`; enable the latter only with compatible wrappers. Use loopback by default. LAN exposure, firewall and authentication changes require explicit user intent.
7. Run `--list` / `--check-ui`. A model load, inference request or listener outage is a separate live operation within the user's authorized scope. UI/docs work uses mocks or read-only diagnostics.
8. Register startup for the intended installed checkout; keep one tray instance. Reinstall the task after moving a checkout.

```powershell
.\.venv\Scripts\python.exe ai-launcher.py --list
.\.venv\Scripts\python.exe ai-launcher.py --check-ui
.\.venv\Scripts\python.exe ai-launcher.py --diagnose
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Use isolated `AI_PROFILES_CONFIG` / `state_dir` and all five Strata presets for the complete selection suite. Native HTTP tests skip without Strata; for full integration, use its dependency-complete Python and add Valet's site-packages to `PYTHONPATH` if needed. Report passed/skipped separately. A UI check is not a load/inference check. GitHub CI runs backend-independent Windows tests.

## Preserve contracts

- Game priority: Steam roots, Windows game records, `extra_games`, fullscreen/presentation guard; unknown inspection blocks loading. Retain on-demand grace, native HTTP authentication, cancellation/SSE and admission checks.
- Manual Unload disarms immediate listener recovery. Optional idle restore is independent; delay 5/10/15/20/25/30 minutes, default 20. UI-only changes must not rearm recovery.
- Recovery every 10 seconds; at most three attempts per 10 minutes with persisted backoff. Never force recovery through an occupied port or kill a live peer application.
- Reverify executable/script path and creation time immediately before stopping; retain graceful shutdown and authenticated GUI IPC.
- Preserve legacy pipe `AI-Profiles`, state `AIProfiles`, task `AI Profiles - Idle Reload`.
- Quiet Valet: graphite, flat/compact layout, shared `ui_font` / control sizes, equal grid columns, real data. Preserve keyboard input, DPI bounds and native window controls; verify 100/150/200%, resized forms and tray fallback.
- Profile saves preserve unexposed settings, reject stale snapshots and back up originals; apply only on a later profile launch. Save never hot-reloads a model.
- Exclude configs, session/issue/log/state files, credentials, private hostnames/IPs, models, engines, venvs, profiling output and profile backups. Screenshots must reveal no private desktop content.
- README: concise commands/tables, real visuals, quick links; move detail to `docs/`. No invented benchmarks or universal page-file multipliers.
- Run focused checks, full applicable suite and `--check-ui`. Back up installed files before deploying; verify unchanged backend/request state for UI/docs updates.
