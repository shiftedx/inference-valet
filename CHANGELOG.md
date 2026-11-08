# Changes

## 0.4.1

- Advertise configured vision support and image input modalities in model discovery without loading models.
- Read provider bodies in bounded chunks and record redacted rejection reasons, byte counts and correlated request IDs; retain existing response semantics, body limit and inactivity timeout.
- Cover large valid JSON uploads, malformed framing and body timeouts with regression tests.
- Package optional native Strata diagnostics for unresolved/incomplete tool calls, with separate installation instructions and CPU/mock tests.
- Preserve external profile tuning and NInferEZ loaded-profile discovery.

## 0.4.0

- Serve an authenticated OpenAI-compatible Valet endpoint with dynamic profile loading and a shared local/LAN request queue; drain active streams before switching models.
- Advertise request context, shared or per-slot KV capacity, output limits and verified loaded-profile metadata for agent context budgeting.
- Fix overlapping dashboard controls and distinguish in-flight requests from occupied engine slots.
- Show backend-specific activity and loading labels while retaining Infernix and NInferEZ telemetry.
- Preserve external profiles, model caches, game admission and manual Unload controls.

## 0.3.2

- Discover and manage native Windows Infernix and NInferEZ model profiles alongside Strata.
- Show live inference telemetry and the expected idle restore backend and model.
- Preserve verified listener ownership, memory monitoring, and game admission across backend switches.

## Unreleased

- API access details: masked token field, eye reveal/hide and Copy; automatically mask when leaving the tab.

- Authenticate Strata telemetry, launch verification and unload requests; forward configured API keys through the backend environment.
- Graceful stop skips inaccessible native children while retaining launcher ownership, process identity and script provenance checks.

## 0.3.1

- Themed tray menu: shared colors, buttons, selected profiles, busy states.
- Keyboard navigation; monitor bounds; scrolling; outside-click dismissal.
- Long profile names: compact labels, agent/context details, hover tooltips.
- Hidden status: 10-second heartbeat; 80% fewer scheduled checks.
- Visible telemetry: 2-second refresh; immediate refresh on open.
- Game priority, cancellation, recovery and manual Unload preserved.

## 0.3.0

- Discover existing Strata profiles; no bundled model presets or machine-specific memory recommendations.

- Compact dashboard and tray controls; one Strata status beside the idle-restore controls.
- Aligned tabs, numeric readouts and profile settings; monitor-aware layout and tooltip dismissal.
- GPU core and memory clocks, memory activity, temperature, power limit and session average power during verified Strata activity. Unsupported readings remain unavailable.
- Safe setup, upgrade and removal procedures preserving external backends, profiles and saved settings.
- Sharper documentation screenshots captured at 2×.

Windows source distribution; Python 3.11+ with Tcl/Tk required. Install Strata and model files separately. Memory activity measures VRAM read/write busy time; the GiB meter shows capacity use. Strata average measures whole-GPU draw during verified activity and can include other GPU workloads.
