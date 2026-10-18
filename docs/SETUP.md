# Setup / operation

## Connect Strata

| Item | Required location / action |
|---|---|
| Upstream | Install [Strata](https://github.com/Niko1221/Strata) and models separately; retain their licenses |
| Backend root | Your existing deployment containing `Strata/` and `profiles/` |
| Managed wrappers | Install the three scripts from `backends/strata/` at the backend root |
| Profiles | Existing executable `profiles/<name>.json`; optional matching shared settings |
| Backend Python | `<root>/Strata/.venv/Scripts/python.exe`, or `strata_python` override |

```powershell
# Run after scripts/setup.ps1; substitute your existing backend root.
.\.venv\Scripts\python.exe scripts/install-strata-integration.py --root C:/path/to/Strata-deployment
```

The helper installs wrappers, not model presets. Keep your working external profiles and model settings. Conflicting wrappers require `--replace-wrappers`, a stopped backend and a backup. Never replace a live launcher's files: graceful-stop verification checks their hashes.

Managed resource inspection currently requires NVIDIA `nvidia-smi`. Other Strata-supported GPUs need a compatible resource sampler. Unknown inspection blocks loading. Native lifecycle compatibility must be rechecked when upgrading Strata.

## Configure Valet

Set `strata_root` in `config.json` to the deployment above. Valet discovers compatible executable JSON profiles from its `profiles/` directory; it does not choose a model, context size or agent count for you. Shared-settings and support JSON files are excluded.

| Key | Meaning |
|---|---|
| `strata_root` | Existing managed backend root |
| `strata_python` | Optional backend Python override |
| `enabled_profiles` | Optional list of profile filename stems; omit to discover all compatible profiles |
| `state_dir` | Optional state override; default `%LOCALAPPDATA%/AIProfiles` |
| `nvidia_smi` | Optional telemetry executable override |
| `on_demand.enabled` | Optional first-request loading; requires compatible managed wrappers |

- `AI_PROFILES_CONFIG`: alternate config path; relative Valet paths resolve against its directory.
- No profiles found: check the configured root and external profile format; restart Valet after adding profiles. Loading and editing stay unavailable until a profile is discovered.
- Eager mode: load a selected profile immediately; detected games block automatic restoration.
- On-demand mode: start an unloaded listener; the first request loads after admission checks. Game grace defaults to 5 seconds; game-exit cooldown defaults to 30 seconds.
- Optional resource thresholds are deployment settings. Existing configured thresholds are preserved; Valet supplies no machine-specific RAM, VRAM or page-file recommendations.
- Idle restore: 5/10/15/20/25/30 minutes, default 20. An on-demand listener remains unloaded until a request.
- Manual Unload disarms immediate listener recovery; optional idle restore still applies. Turn Restore when idle off to keep it unloaded.
- Edit profile: adjust supported fields in a discovered profile. Save validates, backs up the original and applies on the next model launch; it never hot-reloads the model.

## Games / network / startup

- Steam installations and Windows game records are discovered automatically. Add other games to `<state_dir>/idle-settings.json`: `"extra_games": ["C:/Games/MyGame/game.exe"]`.
- Known game executables remain authoritative. The fallback checks exclusive Direct3D state with a fullscreen foreground process; ordinary desktop presentation state does not identify a game. Unknown inspection blocks loading.
- Preserve peer GPU workloads; a resource check does not guarantee that a model will fit.
- Loopback by default. Configure LAN binding, authentication and firewall settings deliberately in your deployment.
- `scripts/install-startup.ps1 -StartNow`: register sign-in for this checkout. Close hides to tray; tray → Exit Valet stops monitoring and retains running backends.

## Validate / troubleshoot

```powershell
.\.venv\Scripts\python.exe ai-launcher.py --list
.\.venv\Scripts\python.exe ai-launcher.py --check-ui
.\.venv\Scripts\python.exe ai-launcher.py --diagnose
```

| Symptom | Action |
|---|---|
| No profiles | Check `strata_root`, executable profile JSON and optional allowlist |
| Invalid model path | Correct the external deployment's profile paths |
| Port occupied | Inspect ownership; Valet preserves unrelated applications |
| API absent but process alive | Inspect startup logs; do not force recovery over the live process |
| Game blocks load | Close the detected game; wait for the configured cooldown |
| Resource admission failure | Check the reported reading and your configured guard |
| Generic shortcut icon | Rerun `scripts/install-shortcuts.ps1` |

## Install / upgrade

Install from a cloned repository or extract the release source ZIP into a permanent folder. Windows Python 3.11+ with Tcl/Tk and an internet connection for Python dependencies are required; the release does not bundle Python, Strata or model files.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup.ps1
# No Desktop or Start links, suitable for an isolated install:
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup.ps1 -NoShortcuts
```

For an upgrade, exit Valet using **tray → Exit Valet** first. Keep the same installation directory. Back up `config.json` and your configured state directory (default `%LOCALAPPDATA%/AIProfiles`). For a clean Git checkout, pull the intended release/tag without discarding local changes. For a source ZIP, extract into a separate temporary folder and copy the new application files over the existing installation, preserving `config.json`, `.venv` and state. Never copy another host's configuration over yours. Then rerun `setup.ps1`: existing config is kept byte-for-byte, dependencies are refreshed, and shell links are updated only if they belong to this checkout. If dependency installation fails, correct the error and rerun setup; do not delete your config/state.

For a Git release checkout after backing up local changes and exiting Valet:

```powershell
git fetch --tags origin
git switch --detach v0.3.1
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup.ps1
```

If you use the sign-in task, rerun `scripts/install-startup.ps1` after upgrading or moving the checkout. Only one checkout can own the legacy sign-in task and named shortcuts. A foreign checkout's integration is preserved unless installation is explicitly given `-ReplaceExisting`; use that switch only for an intentional migration. `setup.ps1` also accepts `-NoDesktop`, `-Python C:\path\python.exe`, and `-ShortcutDirectories` for controlled alternative shortcut destinations.

Ordinary application upgrades do not replace external managed wrappers or calibrated backend profiles. If integration changes are required, stop the managed backend through its normal controls before running `install-strata-integration.py --replace-wrappers`; matching live ownership records or unknown Python/Strata process identity block replacement. Existing wrapper changes are backed up under the external root's `integration-backups/`. Replacing wrappers while the backend is live can invalidate graceful-stop verification.

## Uninstall

1. If desired, unload the model explicitly using its normal controls. **Exit Valet** from the tray menu to stop monitoring. Exiting Valet preserves running backend servers.
2. Remove this installation's shell integration:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\uninstall.ps1
```

The command is safe to repeat. It removes only shortcuts and the sign-in task whose executable, launcher arguments and working directory match this checkout. Other checkout targets remain intact; permission/provider failures are reported. Use the same `-ShortcutDirectories` if installed to custom destinations; `-NoStartup` skips task removal when startup was never installed.

Config, state, virtual environment, source, external Strata, models, profiles and backups are preserved. There is deliberately no recursive settings purge. For complete removal, stop any managed backend first: its admission hooks can reference this checkout. After exiting Valet, remove the installation folder using File Explorer. Delete `%LOCALAPPDATA%/AIProfiles` only if no other installation uses it and you want to discard saved preferences/history; with custom `state_dir`, inspect its contents and ownership before removing anything. Never delete the external Strata/model directory as part of removing Valet. Python itself is shared software and is not removed.

## Test without touching production

Use isolated `AI_PROFILES_CONFIG` and `state_dir` paths. Core tests use temporary profile fixtures and simulated resources; no real model is loaded. Native HTTP integration tests additionally require a compatible external Strata checkout and dependencies; report skipped tests explicitly.

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe ai-launcher.py --check-ui
```
