# Inference Valet branding

The folded V holds a compute token: capable infrastructure, calmly at your service. Use this identity across the dashboard, tray, editors, diagnostics, documentation, and future UI. Retain Quiet Valet's compact, legible behavior; express it in aubergine, vermilion, and parchment.

## Source of truth

- Product name: **Inference Valet**. Short name: **Valet**. Sentence-case interface labels.
- Design contract: this file. Shared colors and typography: [`ai_theme.py`](ai_theme.py). Mark rendering, window identity, and generated icon assets: [`ai_branding.py`](ai_branding.py).
- Import semantic tokens; do not add local palettes or copy hex values into new widgets. Update tokens, this guide, and affected visual checks together when changing the system.
- Preserve existing Windows app identity and legacy IPC, state-directory, and scheduled-task identifiers. A visual change does not rename installation/runtime contracts.

## Color roles

| Token | Color | Use |
|---|---|---|
| `bg` | `#26212F` aubergine | Window and page canvas |
| `card` | `#302A39` | Inputs, grouped surfaces, table backgrounds |
| `raised` | `#3A3244` | Secondary controls, hover surfaces |
| `line` | `#514657` | Quiet dividers and component boundaries |
| `text` | `#FFF1D9` parchment | Primary text, values, headings |
| `muted` | `#C0B4C8` | Secondary labels, hints, timestamps |
| `accent`, `primary` | `#ED794D` vermilion | Primary action, active brand accent |
| `primary_hover` | `#FF9167` | Hovered primary action |
| `on_primary`, `on_accent` | `#26212F` | Text over filled vermilion |
| `focus` | `#FFB596` | Keyboard-focus outline |
| `selected` | `#503B3B` | Selected tab, row, or option background |
| `success` | `#A9C8AB` sage | Ready, completed, healthy |
| `warning` | `#E5BE7E` amber | Pending, paused, actionable caution |
| `error` | `#EF9A9A` rose | Failure or blocked action |
| `info` | `#BFB2CF` lilac | Neutral information |

Vermilion is the brand/action color, not the failure color. Pair status color with a clear word or icon; never communicate state through color alone. Use secondary text for ordinary idle/unavailable observations, not alarming warning/error colors.

### Charts

| Token | Series |
|---|---|
| `chart_output` | Output speed; vermilion |
| `chart_gpu` | GPU use; sage |
| `chart_cpu` | CPU use; lilac |

Use matching `chart_*_fill` tokens for subdued areas: output `#41303B`, GPU `#2F3A37`, CPU `#383041`. Memory meters use `meter_gpu` vermilion and `meter_ram` warm parchment `#DCC8AF`; labels identify each resource. Keep labels, units, legends, and scales explicit. A sage GPU series identifies GPU use; it does not assert healthy state. Series colors are stable across charts. Do not reuse primary/action color to mark an error. Legacy pigment aliases exist only for compatibility; new code uses role names.

## Typography and spacing

- Native **Segoe UI** throughout; use `ui_font()` and `FONT_SIZES` from `ai_theme.py`. Body 10 pt; captions 9 pt; section headings and key metrics 12 pt. Bold is selective, not a second hierarchy everywhere.
- Use concise sentence-case labels and familiar units. Align numeric values consistently; preserve `GiB`, `MiB`, tokens, tok/s, and milliseconds/seconds where applicable.
- Base spacing rhythm: 4, 8, 12, 16, 24 device-independent pixels. Existing shared surface padding is 18 horizontal / 14 vertical; keep it consistent within a window.
- Shared controls start at **34 DIP**, grow for font metrics and display scale, and use **8 DIP** corners. Grouped surfaces use **14 DIP** corners. Reuse shared `Button`, `TextField`, `ProfileSelect`, and `Surface` components instead of approximating them locally.
- Preserve useful density. Keep actions close to their subject and diagnostics behind clear tabs/disclosures. Avoid oversized headers, ornamental gradients, glows, and repeated nested cards.

## Interaction and component rules

- Primary buttons: vermilion fill, aubergine label; warmer hover and visible focus outline. Reserve primary treatment for the main action in the current group. Secondary controls use raised surfaces; quiet actions remain visually quieter.
- Inputs: card surface, parchment entered values, muted helper text, visible boundary/focus. State units and accepted values beside the field. Show validation near the field and preserve the user's input after an error.
- Tabs: use a consistent selected background/accent and legible text. Selection and keyboard focus are distinct states. Keep native navigation, Space/Enter activation, Escape dismissal, and tab order intact.
- Disabled controls remain recognizable and inert. Do not present unavailable actions as ready. Save labels must communicate timing; engine changes use **Save for next load**, with pending status separate from the running configuration.
- Keep semantic statuses separate from chart colors and branding. Plain observations are not confirmed GPU blockers. A known game continues to take priority; a brand refresh does not alter lifecycle policy.
- Technical tables scroll within their own viewport using wheel, keyboard, Home/End, and paging. Keep headings/context visible; avoid a second visible scrollbar competing with the table. Pointer scrolling must not move the whole dashboard while over a table.
- Use compact tables for engine settings, evidence, and request activity. Keep sources explicit: Reported, Startup log, Active configuration, Shared defaults, or Last start. A configured value is not proof of live residency.
- Hide optional metrics unsupported by the backend. For supported data temporarily missing, use a restrained unavailable state only when it helps explain the current operation. Never fabricate zero values, percentages, timing, or expert counts. Do not repeat a large diagnostic text dump above the tables.

## Mark and assets

| Asset | Purpose |
|---|---|
| `docs/assets/logo.png` | Approved dark horizontal wordmark lockup |
| `docs/assets/icon.png` | 512 px app icon derived from the approved master |
| `docs/assets/inference-valet.ico` | Windows icon: 16, 24, 32, 48, 64, 128, 256 px |
| `docs/assets/tray-icon.png` | 32 px transparent tray adaptation |
| `docs/assets/icon.svg` | Portable wrapper of the approved artwork |
| `docs/assets/brand-held-token-20261017/` | Preserved approved source artwork |

- Use the supplied folded-V/token artwork. Do not return to the key, arrow/orbit, or blue identity. Do not regenerate or reinterpret the mark for each surface.
- Preserve aspect ratio, geometry, palette, and wordmark spelling. Do not stretch, rotate, add effects, place status badges inside the mark, or redraw the wordmark in a substitute font.
- Keep clear space of at least one token height around standalone artwork and lockups. Let the icon's native rounded silhouette supply its boundary; do not nest it in another decorated tile.
- Use the dark wordmark on aubergine or its own native background. Do not place the opaque dark lockup on a light field without its intended panel.
- Use the full mark for title/app surfaces at 20 px and larger. At Windows tray sizes use the simplified high-contrast ribbon/token adaptation, rendered at the actual target size; retain the aubergine keyline for legibility on light and dark taskbars.
- Use the wordmark only where its full text remains readable. In compact controls use the icon plus ordinary accessible product text instead. Keep descriptive alt text in documentation.
- Show the product name and icon once per surface. The dashboard uses its native title bar; its content header identifies the model profile. The borderless tray keeps its own branded header.
- Windows system menus follow the operating-system theme; preserve their native behavior rather than replacing them just to recolor them.
- Native tray geometry is a deliberate small-size adaptation. `icon.svg` preserves the approved raster artwork in a portable wrapper; it is not an independently editable vector master.

## Accessibility and review

- Preserve text contrast of at least **4.5:1** for ordinary enabled text and **3:1** for large text. Check actual foreground/background pairs after introducing overlays, selected states, or new controls; a palette alone does not guarantee accessibility.
- Use aubergine text on vermilion primary fills. Parchment on vermilion is not an approved ordinary-text pairing. Do not use quiet divider lines as the only cue for an interactive target or focus.
- Preserve visible keyboard focus and native control semantics. Tooltips supplement clear labels; they cannot be the only way to understand an action.
- Review dashboard, tray, profile editor, disclosures, selected tabs, pending/error/disabled states, and technical tables at 100%, 150%, and 200% Windows scaling. Keep monitor-bound placement and footer/actions reachable.

Before shipping UI:

- [ ] Shared semantic tokens and components used; no stale graphite/blue/key branding.
- [ ] Source artwork and icon/window/shortcut/tray identity agree.
- [ ] Primary, hover, focus, selected, disabled, and semantic states remain distinguishable.
- [ ] Labels, units, evidence sources, pending changes, and unavailable data are accurate.
- [ ] Keyboard navigation, table scrolling, and all supported scales remain usable.
- [ ] Run `python -m unittest discover -s tests -v` and `python ai-launcher.py --check-ui`; inspect real UI previews before updating documentation screenshots.
