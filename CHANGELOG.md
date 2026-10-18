# Changes

## 0.3.0

- Discover existing Strata profiles; no bundled model presets or machine-specific memory recommendations.

- Compact dashboard and tray controls; one Strata status beside the idle-restore controls.
- Aligned tabs, numeric readouts and profile settings; monitor-aware layout and tooltip dismissal.
- GPU core and memory clocks, memory activity, temperature, power limit and session average power during verified Strata activity. Unsupported readings remain unavailable.
- Safe setup, upgrade and removal procedures preserving external backends, profiles and saved settings.
- Sharper documentation screenshots captured at 2×.

Windows source distribution; Python 3.11+ with Tcl/Tk required. Install Strata and model files separately. Memory activity measures VRAM read/write busy time; the GiB meter shows capacity use. Strata average measures whole-GPU draw during verified activity and can include other GPU workloads.
