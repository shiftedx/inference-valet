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
- Edit profile: adjust existing presets; Save creates backups and updates labels. Click Load/Switch model to apply. Creating arbitrary new preset names is not supported by this first editor.

## Games / network / startup

- Discover Steam install directories and Windows game records. Add other games to `<state_dir>/idle-settings.json`: `"extra_games": ["C:/Games/MyGame/game.exe"]`.
- Fullscreen/presentation applications are conservatively treated as blockers. Unknown process/game inspection blocks loading; ordinary desktop input never unloads an already loaded model.
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

## Test without touching production

Set `AI_PROFILES_CONFIG` to a temporary JSON file with a separate `state_dir` and `on_demand.enabled=true`; omit `enabled_profiles` to exercise all five preset IDs. Point `strata_root` at a compatible Strata checkout for native HTTP tests, or an absent directory for core-only tests. The suite uses a simulated engine, not live model prompts. Install dependencies under the interpreter that runs the suite. Report native skips explicitly.

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe ai-launcher.py --check-ui
```
