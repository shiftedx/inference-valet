# Backend activity

## Edit the next load

- Engine tab → **Edit selected profile** → **Memory** or **Engine** → **Save for next load**.
- Memory: Engram/PLE `direct`, `mmap`, or `ram`; GPU expert cache `auto`, `0`, or slots; positive expert RAM budget in GiB; VRAM reserve in MiB; resident KV tokens.
- Engine: prompt batch, CPU workers, speculative tokens, draft probability, PCIe fraction.
- Blank optional fields remove overrides. Required serving values retain a supported prompt batch and 2–8 draft tokens.
- Saving validates first, checks external edits, and backs up the profile. It leaves active model arguments untouched.
- On the next unloaded native model load, the guarded listener validates the saved profile again and refreshes only the exposed engine arguments under its native lifecycle lock.
- The running model retains its current configuration. Context, KV format, agent count, and request defaults on the Profile tab require loading that profile through Valet.
- The Engine header marks saved engine changes pending until the next load uses them.
- Scroll tables directly with the wheel or keyboard; table wheel input does not move the dashboard. Right-hand table scrollbars are hidden.

- Expand details → **Engine**: memory placement, expert counts, effective engine settings, and shared generation defaults.
- **Requests**: recent native outcomes and timing columns; no prompt capture.
- **Diagnostics**: bounded blocker summary, ComfyUI queue state, and observed GPU processes.
- Source column: `Reported`, `Startup log`, `Active configuration`, `Shared defaults`, `Last start`, or `Not reported`.
- Shared generation defaults may be overridden by individual requests. Runtime configuration belongs to the current managed listener; saved profile edits apply on the next load.
- Resident expert RAM and pinned expert RAM are separate startup measurements. Engram/PLE placement comes from the latest verified engine startup log.

## Game priority

- Preserve detection of running Steam, recorded, and explicitly configured game executables, including windowed and background games.
- Windows notification `BUSY` and `PRESENTATION_MODE` do not identify games; opening Valet must not unload a model.
- Unknown exclusive Direct3D fullscreen applications retain a fallback guard after checking actual foreground-window bounds.
- Exempt only Valet's exact launcher script and trusted interpreter installation from that fallback; unrelated Python programs remain eligible.

| Observation | Meaning |
|---|---|
| Ready | Verified Strata listener; model loaded; no reported request work |
| Reading / generating | Native request phase; not inferred from GPU utilization |
| Waiting | Native queue or current admission guard reports pending work |
| Unloaded | API available; model not resident |
| Unavailable | Observation failed; not proof that the backend stopped |
| GPU blocker | Current admission evidence or GPU resource pressure; not exclusive GPU ownership |

- Observe existing Strata setup; never load, unload, cancel, or submit requests while refreshing.
- Verify listener process identity before accepting native status and activity.
- Treat `/metrics` and `/v1/status` as separate samples; discard data after an owner change.
- Use native parallel request counts; `/v1/status.activity.in_flight` alone can undercount parallel work.
- Accept demand status only while fresh and tied to the current server identity.
- Guard resource snapshots describe the last load attempt; sample current GPU resources separately.
- During admitted model warmup, allocations may belong to Strata; do not label its own increasing memory use as a new resource blocker.
- GPU process observations cover compute processes reported on GPU 0; Windows WDDM may omit memory sizes or graphics workloads. Names and utilization do not establish exclusive ownership.
- Report unavailable measurements explicitly; do not retain a previous live phase as current.
- Keep collection active in the tray; use a slower hidden cadence and refresh when shown.
- Activity contains counts, timings, phases, and outcomes; exclude prompts, responses, workflow graphs, credentials, and client identities not supplied by the backend.
- Native recent-request history is bounded and process-local; polling can miss short phases and rejected requests.

## ComfyUI observation

```json
{"activity": {"comfyui_url": "http://127.0.0.1:8188"}}
```

- Read `GET /queue`; retain only lengths of `queue_running` and `queue_pending`.
- Empty queue means no queued generation; retained models may still occupy VRAM.
- A failed probe means unavailable, not idle.
- `activity.comfyui_url` enables observation only; it does not change admission priority or automatically interrupt either backend.
- Existing `on_demand.comfyui_url` is a separate admission-policy setting; preserve its behavior.
- Never call ComfyUI `/prompt`, `/interrupt`, `/free`, or queue mutation endpoints during observation.

## Validation cases

- Foreign listener on 8080 with an owned Strata process elsewhere: reject API attribution.
- Listener PID changes during sampling: discard the mixed backend sample.
- Stale, future-dated, or wrong-owner demand file: ignore guard details.
- Three native parallel requests with status `in_flight=1`: preserve native parallel count.
- Model unloads between metrics and status: clear live speed and phase.
- Hidden dashboard: continue sampling; reopen with a fresh reading.
- ComfyUI offline, empty, running, and queued: report each without mutation.
- GPU measurement fails: show unavailable rather than zero utilization or free VRAM.
