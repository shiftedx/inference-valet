# Setup / operation

## Connect Strata

| Item | Required location / action |
|---|---|
| Backend root | Example `C:/AI/Strata-Valet`; actual root may differ |
| Upstream | Install [Niko1221/Strata](https://github.com/Niko1221/Strata) at `<root>/Strata/`; run its Windows setup; keep its model/dependency licenses |
| Managed wrappers | Install the three scripts bundled in `backends/strata/` at `<root>/` |
| Profiles | `<root>/profiles/<preset>.json` and optional matching `.shared-settings.json` |
| Backend Python | `<root>/Strata/.venv/Scripts/python.exe`, or `strata_python` override |
| API | Native `/health`, `/v1/models`, `/v1/status`, `/metrics`, load/unload lifecycle; port 8080 |

This integration's preflight/admission sampler requires NVIDIA `nvidia-smi`. Other Strata-supported GPUs need a resource-sampler adaptation before these managed wrappers can be used; unknown resource state blocks loading.

```powershell
# Run from the Valet checkout after scripts/setup.ps1.
.\.venv\Scripts\python.exe scripts/install-strata-integration.py --root C:/AI/Strata-Valet --install-examples
```

The helper copies wrappers and missing examples; it never overwrites existing profiles. Conflicting wrappers require `--replace-wrappers`, a stopped backend and a backup. Do not change an active launcher's files: its graceful-stop record verifies their hashes.

**Examples contain placeholder paths.** Before loading, edit both profile JSON files:

| Field | Set to |
|---|---|
| `exe`, `cwd`, `vision.exe` | Actual installed Strata engine/server paths |
| `args`: `--pack` | Installed pack directory |
| `args`: `--native` / `--ple-gguf` | Actual GGUF parts for the matching model |
| `args`: `--mtp`, `--expert-profile` | Installed draft model / expert profile |
| `tokenizer` | Matching tokenizer directory |
| `vision.mmproj`, `vision.model` | Matching vision projector / GGUF model |
| `lib_dirs` | DLL directories from the upstream-generated Windows configuration; do not guess CUDA versions |
| `model_name` | Model ID served by this configuration |

Reuse a known-working upstream configuration for model/runtime paths. Retain profile structure, vision support, `parallel` and `--max-context`; validate before loading. Examples use the reference host's IQ3_XXS tuning, not universal hardware presets. Compatible native lifecycle baseline: upstream commit `296b59d2f73c8f04a805df29c2fa97655adace78`; re-run native HTTP tests when upgrading.

## Configure Valet

```json
{
  "strata_root": "C:/AI/Strata-Valet",
  "enabled_profiles": ["strata-128k", "strata-3"],
  "on_demand": {"enabled": true}
}
```

| Key / preset | Meaning |
|---|---|
| `strata_root` | Managed backend root, containing `Strata/`, wrappers and `profiles/` |
| `strata_python` | Optional backend Python override |
| `state_dir` | Optional state override; default `%LOCALAPPDATA%/AIProfiles` |
| `nvidia_smi` | Optional telemetry executable override |
| `enabled_profiles` | Nonempty subset of installed preset IDs; examples provide the first and fourth entries below |
| `strata-128k` → `quality-iq3-xxs` | Legacy ID; example actually uses 160K tokens per agent |
| `strata-256k` → `quality-iq3-xxs-max-context` | Optional external preset |
| `strata-2` → `quality-iq3-xxs-agents` | Optional external preset |
| `strata-3` → `quality-iq3-xxs-agents-3` | Three-agent example |
| `strata-4` → `quality-iq3-xxs-agents-4` | Optional external preset |

- `AI_PROFILES_CONFIG`: alternate config path; relative Valet paths resolve against its directory. Backend JSON model paths should be absolute.
- Eager mode (`enabled=false`): Valet loads the selected profile; detected games block automatic reloads. Eager mode does not install the native game-triggered unload hook.
- On-demand mode (`enabled=true`): start an unloaded listener; the first request loads the engine after admission checks. Game grace defaults to 5 seconds; game-exit cooldown defaults to 30 seconds. Active games/unknown state/insufficient headroom return retryable errors.
- Idle restore: 5/10/15/20/25/30 minutes, default 20. Eager mode reloads the profile; an on-demand listener stays unloaded until a request. Listener recovery is separate and never waits for the idle timer.
- Manual Unload: disarm immediate listener recovery; optional idle restore still applies. To keep the model unloaded, turn Restore when idle off too.
- Edit profile: adjust existing presets. Memory exposes engram placement, GPU expert slots, resident RAM budget and VRAM reserve; blank restores backend defaults. Save for next load validates and backs up edits. Active and pending settings remain distinct; the next model load applies them, including a compatible unloaded on-demand listener. Creating arbitrary preset names is not supported.

## Games / network / startup

- Discover Steam install directories and Windows game records. Add other games to `<state_dir>/idle-settings.json`: `"extra_games": ["C:/Games/MyGame/game.exe"]`.
- Known game executables remain authoritative. The fallback requires exclusive Direct3D state and a fullscreen foreground process; Valet is identified by its exact executable and script paths. Ordinary desktop busy/presentation states do not identify games. Unknown inspection blocks loading.
- Preserve other GPU workloads. Defaults require ≥24,000 MiB free VRAM, ≤4,096 MiB used VRAM, ≥26 GiB available RAM and ≥35 GiB commit headroom. These are reference-profile admission thresholds; measure before changing them.
- Loopback by default. To expose LAN, configure `on_demand.listen_host` intentionally and audit native authentication/firewall settings; Valet does not establish a secure public service.
- `scripts/install-startup.ps1 -StartNow`: install one sign-in task for this checkout. Close hides to tray; right-click tray → Exit Valet stops monitoring and keeps the backend running.

## Validate / troubleshoot

```powershell
.\.venv\Scripts\python.exe ai-launcher.py --list
.\.venv\Scripts\python.exe ai-launcher.py --check-ui
.\.venv\Scripts\python.exe ai-launcher.py --diagnose
```

| Symptom | Action |
|---|---|
| Missing profile/model path | Correct external JSON paths; select only installed presets |
| Port occupied | Inspect current owner; Valet refuses to stop unrelated applications |
| API absent but process alive | Inspect startup logs; do not force a recovery over the live process |
| Load blocked by game | Close detected game/fullscreen app; wait cooldown; verify `extra_games` |
| RAM/commit/VRAM admission failure | Read [Performance](PERFORMANCE.md); preserve peer workloads |
| Generic shortcut icon | Re-run `scripts/install-shortcuts.ps1` |

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
git switch --detach v0.3.0
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

Set `AI_PROFILES_CONFIG` to a temporary JSON file with a separate `state_dir` and `on_demand.enabled=true`; omit `enabled_profiles` to exercise all five preset IDs. Point `strata_root` at a compatible Strata checkout for native HTTP tests, or an absent directory for core-only tests. The suite uses a simulated engine, not live model prompts. Install dependencies under the interpreter that runs the suite. Report native skips explicitly.

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe ai-launcher.py --check-ui
```
