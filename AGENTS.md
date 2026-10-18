# Agent guide

Windows tray controller for external Strata: Tkinter/ttk UI, verified process control, game/resource admission, optional on-demand loading and idle restore. Read [setup](docs/SETUP.md) and [backend contract](docs/BACKENDS.md) before configuring a host.

## Layout

| Path | Responsibility |
|---|---|
| `ai-launcher.py` | Dashboard/tray, IPC, verified start/stop, recovery scheduling |
| `ai_config.py`, `config.example.json` | Local config; paths relative to config directory |
| `ai_profiles.py`, `ai_profile_editor.py` | External profile discovery; validated, backed-up external profile edits |
| `ai_widgets.py`, `ai_branding.py`, `ai_telemetry.py` | Shared font/geometry tokens, app identity, read-only telemetry |
| `ai_idle.py`, `ai_demand.py`, `ai_recovery.py` | Game discovery, idle delay, native admission, listener recovery |
| `backends/strata/` | Managed wrappers; install outside this repo |
| `scripts/`, `tests/` | Setup/startup/integration; unit, native HTTP and Tk workflow checks |

## Configure a host

1. Preserve the user's external Strata deployment, profiles and local settings. Process names and port 8080 alone never establish ownership.
2. Run `scripts/setup.ps1`; it creates Valet's `.venv`, local config and shortcuts. Supply `-Python C:\path\python.exe` when needed.
3. Connect the existing deployment and install managed wrappers using `scripts/install-strata-integration.py`. Never overwrite a live launcher's files.
4. Set `strata_root` and optional `strata_python` / `state_dir`. Discover executable profiles automatically; optional `enabled_profiles` contains filename stems. Do not add model presets or host-specific memory defaults.
5. Choose eager or optional on-demand loading with compatible wrappers. Preserve configured admission settings, loopback defaults and native authentication.
6. Validate discovery and the UI. Model loads and inference are live operations; UI/docs changes use mocks or read-only diagnostics.
7. Register startup for one intended checkout; reinstall the task after moving it.

```powershell
.\.venv\Scripts\python.exe ai-launcher.py --list
.\.venv\Scripts\python.exe ai-launcher.py --check-ui
.\.venv\Scripts\python.exe ai-launcher.py --diagnose
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Use isolated `AI_PROFILES_CONFIG` / `state_dir`; tests create temporary profiles for populated and empty discovery cases. Native HTTP tests skip without Strata; for full integration, use its dependency-complete Python and add Valet's site-packages to `PYTHONPATH` if needed. Report passed/skipped separately. A UI check is not a load/inference check. GitHub CI runs backend-independent Windows tests.

## Preserve contracts

- Game priority: Steam roots, Windows game records, `extra_games`, fullscreen/presentation guard; unknown inspection blocks loading. Retain on-demand grace, native HTTP authentication, cancellation/SSE and admission checks.
- Manual Unload disarms immediate listener recovery. Optional idle restore is independent; delay 5/10/15/20/25/30 minutes, default 20. UI-only changes must not rearm recovery.
- Recovery every 10 seconds; at most three attempts per 10 minutes with persisted backoff. Never force recovery through an occupied port or kill a live peer application.
- Reverify executable/script path and creation time immediately before stopping; retain graceful shutdown and authenticated GUI IPC.
- Preserve legacy pipe `AI-Profiles`, state `AIProfiles`, task `AI Profiles - Idle Reload`.
- Quiet Valet: follow [BRANDING.md](BRANDING.md); folded-V identity, aubergine surfaces, vermilion actions and parchment text; flat/compact layout, shared `ui_font` / control sizes, equal grid columns, real data. Preserve keyboard input, DPI bounds and native window controls; verify 100/150/200%, resized forms and tray fallback.
- Profile saves preserve unexposed settings, reject stale snapshots and back up originals; apply only on a later profile launch. Save never hot-reloads a model.
- Exclude configs, session/issue/log/state files, credentials, private hostnames/IPs, models, engines, venvs, profiling output and profile backups. Screenshots must reveal no private desktop content.
- README: concise commands/tables, real visuals, quick links; move detail to `docs/`. No invented benchmarks, bundled model tuning or machine-specific RAM/page-file guidance.
- Run focused checks, full applicable suite and `--check-ui`. Back up installed files before deploying; verify unchanged backend/request state for UI/docs updates.
