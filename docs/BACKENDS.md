# Backend contract

## Strata root

- Scripts: `launch_strata_profile.py`, `stop_strata_profile.py`, `managed_strata_server.py`.
- Engines: `Strata/engine/strata.exe`, `strata-vision.exe`.
- Python: `Strata/.venv/Scripts/python.exe`; install backend dependencies.
- Profiles: `profiles/<name>.json`; set existing model/pack/MTP paths.
- Profile names: `quality-iq3-xxs`, `quality-iq3-xxs-max-context`, `quality-iq3-xxs-agents`, `quality-iq3-xxs-agents-3`, `quality-iq3-xxs-agents-4`.
- Model ID: `qwen3.8-flash-next-iq3_xxs`.
- HTTP: `/health`, `/v1/models`, `/v1/status`, `/metrics`; port `8080`.

## Read-only activity

- See [Activity semantics](ACTIVITY.md); verify Strata listener identity before attribution.
- Configure `activity.comfyui_url` with a loopback ComfyUI base URL; observe `GET /queue` counts only.
- Observation does not change `on_demand` admission policy or release retained ComfyUI models.

## Port new installations

- Map installed profile names in `ai_profiles.PRESETS`; use the profile editor for tuning.
- Profile labels: `<state_dir>/profile-names.json`; backups: `<state_dir>/profile-backups/`.
- Preserve model paths and unexposed profile fields; profile saves apply on the next launch.
- Preserve verified process ownership; never terminate unrelated port users.
- Validate: `.\.venv\Scripts\python.exe ai-launcher.py --list`.
