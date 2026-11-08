# Optional Strata tool diagnostics

`unresolved-tool-diagnostics.patch` adds counters, bounded/sanitized declared-tool names, and `unresolved_call` rejection metadata when a tool call cannot be completed or parsed and is returned as text. It covers incomplete announced streams too. It does not execute partial calls, retry tools, capture arguments, or change returned content.

Target: Strata Python server 0.2.11, source commit `c3b3f503`; validated with engine 0.1.57. The patch includes CPU/mock regression tests. It is not automatically applied by Valet setup or the wrapper installer. Other Strata revisions may reject the patch; do not force it or overwrite later upstream fixes.

1. Finish active requests and stop the external Strata deployment through its normal verified controls.
2. Back up `serve/frontend.py` and `serve/server.py`; preserve local source changes and the upstream MIT license.
3. In that Strata source checkout, check and apply the patch from your extracted Valet release:

```powershell
$patch = 'C:/path/to/inference-valet/backends/strata/patches/unresolved-tool-diagnostics.patch'
git apply --check $patch
# Continue only when the check succeeds.
git apply $patch
python -m unittest serve.test_malformed_diagnostics serve.test_native_tool_parser serve.test_tool_call_envelope serve.test_tool_call_unclosed -v
```

Use Strata's dependency-complete Python, with its root and `tools/` on `PYTHONPATH` when required. Restart the deployment normally after checks pass. Read `/metrics` for `totals.tool_calls_unresolved`; logs and supported responses carry the bounded tool-name markers. A marker is diagnostic evidence, not authorization to replay a tool with side effects.

The upstream Strata code and patch context are MIT licensed; retain [the included upstream notice](UPSTREAM-LICENSE.txt). See [Strata](https://github.com/Niko1221/Strata). Engines, runtime libraries, models, calibrated profiles and local logs are excluded.
