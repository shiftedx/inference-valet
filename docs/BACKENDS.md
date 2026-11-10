# Backend contract

## Existing Strata deployment

- Install Strata and models separately; Valet does not supply engine or model presets.
- Point `strata_root` at the deployment containing `Strata/` and `profiles/`.
- Install managed scripts: `launch_strata_profile.py`, `stop_strata_profile.py`, `managed_strata_server.py`.
- Python: `Strata/.venv/Scripts/python.exe`, or an explicit `strata_python` override.
- Profiles: discover executable `profiles/<name>.json`; ignore shared-settings/support JSON.
- Managed JSON requires `exe`, `model_name` (or `model`) and an `args` list containing `--max-context`; `parallel` is optional. Keep upstream model/runtime paths valid.
- Use the deployment's existing model paths, context, concurrency and generation settings.
- HTTP: `/health`, `/v1/models`, `/v1/status`, `/metrics`; default port `8080`.
- Manual **Load model** / **Switch model**: start the selected profile, then `POST /load` on the verified managed listener; wait for loaded status, context and concurrency before reporting Ready. Surface admission/load failures.
- Automatic on-demand restore/recovery: restore the unloaded listener; load on the next admitted request.
- Authenticated Strata: set `strata_api_key` in Valet's local `config.json` (or `STRATA_API_KEY` in the environment). Valet authenticates telemetry and passes the key to the backend through its environment. View or copy the masked token in the dashboard details → API access tab. Restart Valet after changing it; managed scripts must forward `STRATA_API_KEY` to Strata.

## NInfer and Infernix

- Register an installed Windows runtime under `ninfer_profiles` in local `config.json`. Each named entry supplies `engine`, `label`, `exe`, `artifact`, `model`, `context`, `slots` and optional engine `args`.
- Reopen Valet to discover the entry. Select it from the same model picker as Strata. Its runtime and artifact paths must be absolute.
- Valet owns one listener on port 8080. NInfer-family profiles bind to loopback, load when selected, and use **Restore when idle**. Strata profiles can restore an unloaded listener and load on request.
- Set `auth: true` on an Infernix profile to reuse Valet's configured API token. NInferEZ profiles use the loopback listener without token forwarding.
- Infernix dashboard telemetry uses `/metrics?format=json`. NInferEZ uses `/stats` for live rates and request counts. Completed-request timings require Infernix's JSON history.
- Check the restore target in Valet or run `python ai-launcher.py --diagnose` and read `auto_load`. `--list` shows the backend, model and context for each profile.
- Model starts check the configured GPU and game admission rules. The native process monitor unloads on sustained low memory or game activity.

## Profile discovery

- Add a compatible profile to the external `profiles/` directory; restart Valet to discover it.
- Omit `enabled_profiles` to discover all compatible profiles; use filename stems to restrict the list.
- Missing profiles leave loading/editing unavailable until a compatible deployment is configured.
- Older saved profile IDs remain compatible; new installations need no source-code profile mapping.
- Profile labels: `<state_dir>/profile-names.json`; backups: `<state_dir>/profile-backups/`.
- Profile saves preserve unexposed fields and back up originals; changes apply on the next launch.
- Preserve verified process ownership; never terminate unrelated port users.
- Validate: `.\.venv\Scripts\python.exe ai-launcher.py --list`.

## llama.cpp GGUF profiles

- Install an official Windows CUDA llama.cpp runtime separately, including its matching CUDA runtime DLLs. Valet does not download, convert or quantize weights.
- Add an entry under the existing `ninfer_profiles` config section with `engine: "llamacpp"`, an absolute `exe` pointing to `llama-server.exe`, an absolute GGUF `artifact`, `label`, `model` (the API alias), `context`, `slots`, and `auth: true`. Keep model files and host tuning in local config, outside the application repository.
- This adapter initially advertises text input only. It uses the existing verified process ownership, game/resource admission, manual Unload, idle restore and model-switch draining controls.
- Managed arguments bind loopback port 8080, set the alias and slot count, enable read-only slot telemetry, and disable unified KV. `context` is per slot; native `--ctx-size` is `context × slots`. Discovery reports independent slot capacities, not an inflated per-request context. The backend's live capacity must match before Valet reports Ready/loaded.
- Optional `args` carry native settings. DFlash2 uses `--spec-type draft-dflash`, `--spec-draft-model <absolute GGUF path>`, `--spec-draft-ngl <layers>` and `--spec-draft-n-max <tokens>`. Use a build with DFlash2 support and a compatible drafter. Missing draft files fail preflight before the existing model is stopped.
- The embedded chat template must support the client's history format. Agent clients can send system turns later in a conversation. A compatible override can be supplied with `--chat-template-file <absolute path>`; missing files fail preflight. Preserve turn roles/order and verify unchanged rendering for previously supported histories. Valet does not rewrite messages to work around a model template's restrictions.
- Set `--n-predict` for the fallback output limit and `--reasoning-budget` for thinking. Both consume the request context. Cache formats, batching, draft length and sampling are native llama.cpp settings; Infernix tuning flags are not interchangeable.
- `auth: true` writes the existing Valet token to a temporary API-key file and removes it when the child exits. The token is not put in process arguments. Native model/listener/context/authentication overrides are reserved for Valet.
- Chat Completions, Responses, Anthropic Messages and token counting route through the same Valet provider/profile queue. Native errors and streams are preserved. Queue depth remains unavailable. Live output/prefill rates use slot-counter deltas and reset when the process or task changes.
- Completed Chat Completions, Responses and Messages requests through Valet populate dashboard/history from native timings: prefill/decode speeds, input/output tokens, prefix reuse and draft acceptance. Streamed TTFT measures admission-to-first text, reasoning or tool delta; non-streaming TTFT remains unknown. Token counting is excluded. Direct backend clients have live slot telemetry but no Valet request history.
- History retains at most 100 numeric-only records in `llamacpp-performance.json` under the configured state directory; the dashboard shows the newest 12. It survives a dashboard restart for the same backend PID/creation time and resets for a different backend instance. Prompts, completions, reasoning, tool arguments and credentials are not recorded. Missing timings stay unavailable; telemetry/storage errors do not fail inference.
- Reopen Valet only when it is safe to interrupt the provider. Adding files or preparing a config fragment does not activate a profile. GPU memory fit, draft acceptance, latency and quality require a separate live test after the running workload finishes.

See the [native server reference](https://github.com/ggml-org/llama.cpp/tree/master/tools/server) and the drafter publisher's instructions for build compatibility. A successful CLI/help or mock test does not establish GPU load/performance readiness.

## Read-only activity

- See [Activity semantics](ACTIVITY.md); verify Strata listener identity before attribution.
- Configure optional `activity.comfyui_url` with a loopback ComfyUI base URL; observe `GET /queue` only.
- Observation does not change admission policy or release retained ComfyUI models.

### Valet provider

- Base URL: `http://127.0.0.1:8079/v1`. Use the Valet API token as the bearer key.
- For LAN access, set `provider_lan` to the host IPv4 address with its subnet prefix and `on_demand.listen_host` to `127.0.0.1`. Valet serves the LAN address on port `8080`, accepts only peers in its subnet by default, and keeps Strata on loopback. Set `provider_lan_clients` to an explicit list of allowed IPv4 subnets to include other trusted LAN segments. Restart both Valet and the managed Strata listener after changing the bind addresses.
- Open Valet with an API token configured, or run `run.cmd --serve-api` for a standalone listener.
- `GET /v1/models` lists configured profiles. `GET /v1/models/{id}` returns one profile. Select its ID as the model in your client.
- Model metadata: `context_length` is the maximum **input + output** tokens per request; `parallel_slots` is configured serving concurrency.
- `kv_cache_tokens` is total logical live-session KV capacity. `kv_shared: true` means one pool shared by all requests (NInfer/Infernix); never multiply it by `parallel_slots`. For Strata, `kv_shared: false` and `kv_cache_tokens_per_slot` describe independent slots; total capacity is slot capacity × slots. These are logical capacities, not GPU residency or a guarantee that parked conversations remain cached.
- `default_max_output_tokens` is the configured fallback when a client omits its limit. `max_output_tokens` is the absolute output ceiling before deducting input. `output_tokens_share_context: true` requires subtracting the rendered prompt from that ceiling. `context_reserved_tokens` is already deducted from `max_output_tokens` (Strata reserves 8). Thinking tokens count toward output. Unknown defaults or automatic KV capacities are `null`; Valet does not guess them.
- Example: Infernix can report 131072 request context, 262144 shared KV, 6 slots, 32768 default output, and 131072 output ceiling. Four requests share the 262144 pool; six full 128K requests cannot all remain resident. Choose an actual output allowance and leave headroom when dividing the pool among active agents.
- `loaded` is a live, verified resident-profile snapshot. An unloaded lazy Strata listener, unavailable health, or a mismatched native launch reports `false`. Discovery is read-only and never triggers a load. List and single-model endpoints return the same metadata.
- OpenAI defines the model discovery envelope. Context and profile fields are Valet extensions. For clients that ignore them, enter the advertised context limit in the client settings.
- Send the requested profile ID to `POST /v1/chat/completions` or Strata/llama.cpp `POST /v1/responses`. Valet loads an inactive profile, waits for readiness, then forwards the request. Allow up to 620 seconds for loading or waiting behind another model's requests.
- Same-profile requests run concurrently. Model switches wait for existing Valet requests and streams to finish; local and LAN endpoints share the queue. Manual Unload still cancels startup.
- Backend model IDs are accepted when active or unambiguous. Use a profile ID to select context/slot variants. Unknown IDs and unsupported endpoints never trigger a load. Load failures return `503 model_load_failed`; queue timeouts return `503 model_wait_timeout`. A running Strata listener can still warm on demand under its existing guards.

### Claude Code / Anthropic Messages

Valet also routes `POST /v1/messages` and `POST /v1/messages/count_tokens` to the selected backend's native Anthropic API. Use a Strata or NInfer-family runtime that implements these endpoints; Valet does not translate Messages into Chat Completions. The same admission, profile loading, request queue and stream-draining rules apply. Token counting can load an inactive profile so the backend can count its rendered prompt accurately.

Use the **root** URL for Anthropic clients, without `/v1`. The token is the same Valet API token shown under API access. Both `Authorization: Bearer ...` and `x-api-key` authenticate requests. For example, in the PowerShell session that starts Claude Code:

```powershell
$env:ANTHROPIC_BASE_URL = 'http://127.0.0.1:8079'
$env:ANTHROPIC_AUTH_TOKEN = '<your Valet API token>'
$env:ANTHROPIC_MODEL = '<profile ID from /v1/models>'
$env:ANTHROPIC_DEFAULT_OPUS_MODEL = $env:ANTHROPIC_MODEL
$env:ANTHROPIC_DEFAULT_SONNET_MODEL = $env:ANTHROPIC_MODEL
$env:ANTHROPIC_DEFAULT_HAIKU_MODEL = $env:ANTHROPIC_MODEL
claude --model $env:ANTHROPIC_MODEL
```

For a remote client use the configured LAN Valet root on port 8080. Pinning the model aliases keeps foreground and background requests on the intended profile. Unknown Claude cloud IDs are not silently mapped to a local model. Claude Code's automatic discovery can filter out non-Claude profile IDs; select the profile explicitly using these model variables. Check its configured context/output budgets against Valet's discovery metadata; the local model retains its own capabilities and quality settings.

Messages bodies, including system/cache hints, image blocks, thinking configuration, tools, tool-use history and tool results, are forwarded with only the model ID changed to the backend model. `anthropic-version` and `anthropic-beta` headers reach the backend unchanged. Valet relays native SSE events incrementally, including pings, thinking, partial tool JSON, usage and final message events. It aliases the model in both JSON Messages and streamed `message_start.message`. Retry/request-ID headers and native backend errors are preserved. Errors generated by Valet use the Anthropic error envelope on Messages routes, while rejection diagnostics remain redacted.

Clients that accidentally append `/v1` to their Anthropic base can also reach `/v1/v1/messages` and `/v1/v1/messages/count_tokens`; other duplicated paths are not aliases. OpenAI clients keep using the existing `/v1` base URL.

Protocol references: [Claude Code gateway compatibility](https://code.claude.com/docs/en/llm-gateway-protocol), [Anthropic streaming](https://platform.claude.com/docs/en/build-with-claude/streaming), [Infernix native serving](https://github.com/Wallawalla47/Infernix/blob/main/docs/serving.md).

### Vision discovery

- `supports_vision` and `input_modalities` advertise the **configured** profile: `["text", "image"]` when enabled, otherwise `["text"]`. They do not load or probe a model. `loaded` separately verifies the resident launch.
- For an installed Infernix artifact with vision support, append `--vision --vision-offload on` to its existing `args` in local config, preserving its tuning. Offload keeps the tower in system RAM and borrows GPU memory while encoding images. Reopen Valet and load the profile when active work is finished. Valet does not rewrite profiles or assume every artifact supports vision.
- Strata discovery requires `--vision` and its vision executable, projection and model settings. A configured vision section does not prove GPU execution; inspect native encoder logs for CPU fallback.
- Submit images through Chat Completions `image_url` content parts. Model discovery extensions are documented here for agent clients; clients must opt into using them.

### Provider rejection diagnostics

- Before routing, malformed inference requests retain the existing HTTP 400 response. Oversized bodies return HTTP 413; the limit remains 64 MiB. Chunked transfer is unsupported; send one valid `Content-Length`.
- Rejections carry `X-Request-ID`. Match it to a `provider_request_rejected` event under the configured state directory's `issues/` folder. Events contain a fixed reason code, declared/received byte counts, elapsed time, endpoint and optional fixed exception class. Retention follows the existing bounded issue store.
- Reasons distinguish missing/invalid lengths, unsupported transfer encoding, oversize or incomplete bodies, read errors/timeouts, invalid JSON/UTF-8, non-object JSON and invalid model fields. Bodies, images, header values, exception text and credentials are not logged.
- The socket timeout remains **30 seconds without read progress**, not a 30-second total request deadline. Model loading/forwarding waits are separate. Body validation runs before profile selection; a 400 here does not establish a model/router failure.
- Optional native Strata tool-call diagnostics are packaged separately: see [patch instructions](../backends/strata/patches/README.md). Application upgrades do not modify a live external backend.
