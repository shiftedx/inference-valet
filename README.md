<p align="center"><img src="docs/assets/icon.png" width="88" alt="Inference Valet"></p>

<h1 align="center">Inference Valet</h1>

<p align="center"><b>Your GPU when you game. Your model when you need it.</b><br>
Automatic game detection, model loading and idle restore for Strata on Windows.</p>

<p align="center">
  <img src="docs/assets/version.svg" alt="Version 0.2.0">
  <img src="https://img.shields.io/badge/Windows-10%20%2F%2011-a5c6af" alt="Windows 10 / 11">
  <img src="https://img.shields.io/badge/Python-3.11%2B-a5c6af" alt="Python 3.11+">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-a5c6af" alt="MIT license"></a>
</p>

<p align="center"><a href="#run">Install</a> · <a href="docs/SETUP.md">Configure</a> · <a href="docs/PERFORMANCE.md">RAM / page file</a> · <a href="AGENTS.md">Agents</a></p>

<p align="center"><img src="docs/assets/panel.png" width="940" alt="Performance dashboard with model controls, restore timer, output/GPU/CPU plots and memory metrics"></p>

| Automatic game detection | Automatic model loading |
|---|---|
| Detect Steam games, Windows game records, configured executables and fullscreen/presentation activity. Block new loads; optional on-demand mode unloads after its game grace period. | Eager mode restores the last profile after **5–30 idle minutes**. Optional on-demand mode loads on the first request when games and resource guards permit. |
| **Native controls** | **Performance at a glance** |
| Load, switch, unload; close to tray. Edit context, agents, KV, reasoning/output limits and engine tuning. Saved changes apply on the next profile launch. | Output, prompt speed, first-token latency, GPU/RAM, request activity and agent context. Flat charts; Technical details expands the window. |

<p align="center"><img src="docs/assets/lifecycle.svg" width="940" alt="Detected game pauses loading; game closes and PC becomes idle: restore; optional first-request loading"></p>

## Run

**Windows 10/11 · NVIDIA GPU / `nvidia-smi` · Python ≥3.11 with Tcl/Tk · installed [Strata](https://github.com/Niko1221/Strata) and model files.** This managed integration targets NVIDIA; unavailable readings display `—`.

```powershell
git clone https://github.com/shiftedx/inference-valet.git
cd inference-valet
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup.ps1
notepad .\config.json
```

1. Install managed Strata wrappers; configure model paths: **[setup guide](docs/SETUP.md#connect-strata)**.
2. Set `strata_root`, `enabled_profiles` and optional on-demand mode in `config.json`.
3. Validate; open the dashboard:

```powershell
.\.venv\Scripts\python.exe ai-launcher.py --list
.\run.cmd
```

| Do this | Result |
|---|---|
| Load model / Switch model | Load selected profile; remember it for restore |
| Start a detected game | Block automatic loading; on-demand mode rejects new inference and unloads after grace |
| Close games; leave PC idle | Eager mode: restore after selected delay. On demand: load on the next request after cooldown |
| Unload model | Release GPU; disarm immediate listener recovery; optional idle restore remains enabled |
| Restore when idle → off | Persistently pause idle GPU reload |
| Tray left-click / right-click | Quick controls / actions and Exit Valet |

<p align="center"><img src="docs/assets/profile-editor.png" width="590" alt="Aligned Strata profile editor"></p>

## Limited RAM / maximum performance

**Keep a page file enabled; keep the hot working set in RAM/VRAM.** Reference setup: **48 GiB RAM + 32 GiB VRAM + 64 GiB page file**. This provides commit capacity for loading; it is not a universal speed preset. Sustained paging requires a smaller working set. See **[page-file sizing, memory budgets and troubleshooting](docs/PERFORMANCE.md)**.

## Startup / checks

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\install-startup.ps1 -StartNow
.\.venv\Scripts\python.exe ai-launcher.py --diagnose
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe ai-launcher.py --check-ui
```

Signed-in, awake Windows session required. Remove startup with `scripts/remove-startup.ps1`. Core tests need no GPU/models; native HTTP tests require the compatible external Strata checkout and dependencies.

| Need | Open |
|---|---|
| Paths, profiles, extra games, LAN, first-run setup | [Setup](docs/SETUP.md) |
| Commit headroom, page-file sizing, constrained hosts | [Performance](docs/PERFORMANCE.md) |
| Missing-listener recovery, safe unloading, issue history | [Recovery](docs/RECOVERY.md) |
| Backend API / launcher contract | [Backends](docs/BACKENDS.md) |
| Configure or contribute with an agent | [AGENTS.md](AGENTS.md) · [Contributing](CONTRIBUTING.md) |

Screenshots: actual app on the reference host; values vary and unavailable metrics display `—`. Engines/models remain external. [MIT](LICENSE); upstream licenses remain separate. [Credits](CREDITS.md).
