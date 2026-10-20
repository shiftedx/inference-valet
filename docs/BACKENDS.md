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
