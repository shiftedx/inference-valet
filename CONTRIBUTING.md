# Contribute

- Read [AGENTS.md](AGENTS.md); preserve game priority, manual Unload, process ownership and calibrated profiles.
- Use Windows Python ≥3.11 with Tcl/Tk; run `scripts/setup.ps1`. Set isolated `AI_PROFILES_CONFIG` / state paths for tests.
- Run applicable tests and `--check-ui`; report skipped native HTTP tests. Reproduce UI changes at 100/150/200%; attach sanitized screenshots.
- Keep PRs focused: behavior, regression evidence, validation and material limits. Prefer workflow/API tests over implementation mirrors.
- Exclude configs, credentials, runtime state, models, engine binaries and profiling results.
- MIT for this repo; preserve upstream licenses/attribution. Propose tuning changes with hardware, context/agents, workload and peak RAM/commit/VRAM measurements.
