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
- Send the requested profile ID to `POST /v1/chat/completions` or Strata's `POST /v1/responses`. Valet loads an inactive profile, waits for readiness, then forwards the request. Allow up to 620 seconds for loading or waiting behind another model's requests.
- Same-profile requests run concurrently. Model switches wait for existing Valet requests and streams to finish; local and LAN endpoints share the queue. Manual Unload still cancels startup.
- Backend model IDs are accepted when active or unambiguous. Use a profile ID to select context/slot variants. Unknown IDs and unsupported endpoints never trigger a load. Load failures return `503 model_load_failed`; queue timeouts return `503 model_wait_timeout`. A running Strata listener can still warm on demand under its existing guards.
