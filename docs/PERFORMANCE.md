# Limited RAM / page-file tuning

## Reference configuration

| Resource | Observed configuration |
|---|---|
| Host memory / GPU memory | 48 GiB RAM / 32 GiB VRAM |
| Page file | Fixed **65,536 MB initial + maximum** (64 GiB), allocated on the system SSD |
| Commit capacity | Approximately 112 GiB; use the measured Windows limit, not this estimate |
| Model / context | IQ3_XXS; 163,840 tokens per agent; one- and three-agent presets |
| Resident expert budget / KV window | 12 GiB / 32,768 tokens |
| Native admission floor | 26 GiB available RAM; 35 GiB free commit; 24,000 MiB free VRAM |

These are working-host settings, not a benchmark or a universal recommendation. More agents/context/output can exceed the available working set even when commit capacity is adequate. Examples retain these profile settings; measure your own hardware.

## Size for commit; tune for speed

- Keep a page file enabled. Prefer system-managed sizing on a fast SSD with room to grow; pre-size when a measured workload needs predictable commit capacity before loading.
- Estimate: `page-file capacity ≥ expected peak committed memory − physical RAM + headroom`; also satisfy crash-dump requirements. Choose headroom from measured loading/request peaks and other applications, not a fixed RAM multiplier.
- **Available RAM** is physical working-set space. **Commit headroom** is `commit limit − current commit charge`. Increasing the page file helps the latter; it cannot provide GPU VRAM or RAM-speed execution.
- Check Task Manager → Performance → Memory → **Committed**, available RAM, disk activity and Valet → Technical details → System commit. Sustained disk paging/stalls mean the hot working set is too large; reduce it.

Windows sizing and crash-dump requirements vary by workload; excessive disk paging can cause system delays. [Microsoft page-file sizing guidance](https://learn.microsoft.com/en-us/troubleshoot/windows-client/performance/how-to-determine-the-appropriate-page-file-size-for-64-bit-versions-of-windows).

## Configure manually when needed

1. Open `SystemPropertiesAdvanced.exe` → Performance **Settings** → **Advanced** → Virtual memory **Change**.
2. For a reference-like host with sufficient SSD space: select the SSD, choose Custom size, set initial/maximum to **65536 MB**, click **Set**. For other hosts, use the measured sizing estimate above or System managed size.
3. Apply; restart if Windows requests it. Recheck allocated size and the actual commit limit before testing a load. Account for reserved disk space and crash-dump needs.

Read-only inspection:

```powershell
Get-CimInstance Win32_PageFileUsage | Select-Object Name,AllocatedBaseSize,CurrentUsage,PeakUsage
Get-CimInstance Win32_PageFileSetting | Select-Object Name,InitialSize,MaximumSize
```

Valet never changes the page file, RAM/VRAM budgets or firewall automatically.

## Find the actual bottleneck

| Evidence | Action |
|---|---|
| Commit approaches limit / allocation fails | Increase verified commit capacity; close other commit-heavy apps; preserve safe RAM/commit admission floors |
| RAM exhausted + disk stalls | Lower resident RAM budget; reduce parallel agents, context and request/output sizes; leave OS headroom |
| GPU OOM / low VRAM | Reduce agents/context/KV residency; choose a smaller supported KV format; retain VRAM reserve; page-file changes do not fix GPU allocation |
| Slow prompt reading | Compare prompt batch sizes with the same prompt/cache state; `auto` is supported; watch loading/prefill peak memory |
| Uneven decode speed | Compare PCIe fraction, CPU workers and draft settings on identical requests; keep one change per measurement |
| Game/peer GPU workload | Let admission block; never evict peer models or raise thresholds merely to force a load |

Record hardware, model, quantization, context, agents, prompt/output tokens, cache state, prompt/decode/TTFT and peak RAM/commit/VRAM. Distinguish first-load cost from steady state. Save tuned profiles; load explicitly to apply. No universal maximum-performance preset is claimed.
