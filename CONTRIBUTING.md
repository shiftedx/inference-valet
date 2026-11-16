# Contribute

- Read [AGENTS.md](AGENTS.md); preserve game priority, manual Unload, process ownership and calibrated profiles.
- Use Windows Python ≥3.11 with Tcl/Tk; run `scripts/setup.ps1`. Set isolated `AI_PROFILES_CONFIG` / state paths for tests.
- Run applicable tests and `--check-ui`; report skipped native HTTP tests. Reproduce UI changes at 100/150/200%; attach sanitized screenshots.
- Keep PRs focused: behavior, regression evidence, validation and material limits. Prefer workflow/API tests over implementation mirrors.
- Exclude configs, credentials, runtime state, models, engine binaries and profiling results.
- MIT for this repo; preserve upstream licenses/attribution. Keep deployment choices and model tuning in the user’s external Strata profiles.


## Release checks

- Keep `VERSION`, README download/version labels, the SVG version badge and the changelog aligned.
- Build from the tested commit: `python scripts/build-release.py --version X.Y.Z --revision COMMIT`.
- The builder audits the exact ZIP for private/runtime files and common credential/path leaks, verifies its embedded version, and writes `SHA256SUMS.txt`.
- Review source and screenshots as well; pattern scans cannot prove the absence of every possible secret. Tag and publish the same commit used for the archive. Never package an installed deployment directory.
