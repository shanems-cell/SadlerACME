# SadlerACME UI maintenance — 1.0.0-1

Original project by Shane Sadler. Two stylesheets, one shared visual system.

## Where to edit

| Change | Source |
| --- | --- |
| Dark/light colours, reusable controls, card borders, text, status and log surfaces | `src/ui/layout.css`, section 1 and component sections |
| Ordinary page arrangement, header/navigation, responsive grids and main Logs sizing | `src/ui/layout.css` |
| Wizard step/body/log/footer arrangement and short-window fallback | `src/ui/workflow.css` |
| Theme preference and toggle label | `src/ui/theme.js` |
| Initial DSM size/placement and state preservation | `src/ui/SadlerACME.js`, after the unchanged scheduler bridge |
| Heading slots, ordinary fields, status presentation and tab selection | `src/ui/index.cgi` |
| Shared wizard entry points, step presentation and wizard log position | `src/ui/workflow.js` |
| Standalone reading documents | `tools/build_help.py` and source Markdown |

Do not copy the layout into a separate light stylesheet. `layout.css` loads before `workflow.css`, and both use the same palette variables. Each declaration has its own line; edit the relevant named rule rather than append a conflicting override.

## Colour palettes

The first `:root` block provides dark colours and shared sizes. `:root[data-theme="light"]` overrides colour variables only. `theme.js` sets `data-theme` before the stylesheets load. Core variables are `--bg`, `--surface`/`--surface2`/`--surface3`, `--text`, `--muted`, `--label`, `--field-bg`, `--field-border`, `--placeholder`, `--accent`, `--accent2`, `--button-text`, `--line`, `--chrome`, `--blue`, `--log-bg`, and `--log-text`. Status/badge/warning/footer/dialog/spinner colours also have tokens. This avoids dark literal colours leaking into light controls.

The default dark palette is retained except for the primary button hover (`--accent2`), slightly deepened to keep small white text at 4.5:1 or better in that tested pair. Selected enabled text pairs in both palettes are checked by `tests/theme-contrast.py`; that is not a complete accessibility audit. Disabled controls, antialiasing, composited overlays, native widgets and DSM chrome need visual/native review as well.

The header button names the *next* mode, not the current one. The preference uses `localStorage['sadleracme.theme']`; only `dark` and `light` are accepted. Storage read/write errors never block the application; a blocked store gives a page-local selection. Different NAS origins/browser profiles may differ. Theme changes only set attributes/label text: they do not reload the page, rebuild forms, submit settings, clear keys, replay a job or start background processing. Never put API credentials or DSM session material in this preference.

## Shared spacing and certificate form

`--page-gap`, `--panel-pad`, `--action-gap`, fonts and control padding remain shared. Do not reduce every control to force long pages onto one screen. The `certificate-grid` uses named description/key/domains/options/email/token/save areas; the normal and wizard forms use the same arrangement. DOM order matches the narrow reading order. The domains area is normally 88px high and can be resized; expanding it or entering long messages can legitimately require scrolling.

The Settings heading now owns Setup Wizard. The separate actions card distinguishes Save settings from issuance/deployment. Action explanations use spare horizontal space; detailed manual-worker help is a disclosure. The untouched idle activity row is hidden, not errors or results from an actual operation.

## Viewport logs

The outer `.wrap` fills the iframe height. `.content` is the ordinary page scroll owner. `#tab-logs.active` and `.logs-card` use flexible remaining height and zero/minimal flex minima; `.log` owns long text scrolling. Never restore a guessed `100vh - fixed pixels` log height, because heading/toolbars wrap at different widths. The log has a useful minimum and the content parent permits fallback scrolling at very short heights.

With logs visible, `.workflow-dialog.with-log` is bounded to the viewport. `.workflow-body` may scroll when a step is long; `#workflowLogPanel` takes the remaining height; `.workflow-footer` does not shrink out of view. Under 420px height, the wizard uses a scrolling fallback. The shared appearance of `.workflow-log` remains in `layout.css`, while its placement is in `workflow.css`.

The scrollable `.workflow-body` now reserves a stable native scrollbar gutter and 22 CSS pixels of right padding. The padding protects the dropdown arrow from overlay scrollbars; `scrollbar-gutter: stable` alone does not reserve space for overlays. Keep this in the existing named rule, not a theme-specific override. Do not shrink controls or change dropdown behaviour to solve scrollbar overlap. The whole-dialog short-height fallback is retained. The [MDN scrollbar-gutter reference](https://developer.mozilla.org/en-US/docs/Web/CSS/Reference/Properties/scrollbar-gutter) documents the classic/overlay distinction; native browser scrollbar appearance still needs local acceptance.

A viewer follows new lines when already near its bottom. Reading older lines, filtering, pausing or switching palette must not trigger an unexpected jump. Main-page and wizard log controls keep their existing meanings.

## First window placement

Preferred geometry remains 1320 × 820 CSS pixels, preferred minimum 900 × 620, bounded to the outer browser viewport with a 32px horizontal/64px vertical allowance. Final first-show bounds use a meaningful containing-desktop rectangle when available, otherwise conservative viewport allowances. Oversized unmaximised windows can shrink to fit.

DSM's native `AppWindow` reads `appInstance.getUserSettings("restoreSizePos")` and merges it before calling `overwriteAppWinConfig`. Native records use `pageX`, `pageY`, `width`, `height`, `fromRestore` and `maximized`. The supplied native `saveRestoreData` is called on move, resize, close and restore/maximise paths. Do not substitute an unrelated Ext state store for this DSM contract.

The launcher overrides only the native pre-render configuration hook for geometry: call the parent hook, clone its result, and copy finite coordinate pairs into a private per-window snapshot. A native page pair takes precedence over accompanying local x/y. Invalid/partial pairs are removed. This snapshot is not a preference store, and the launcher neither calls the settings writer nor writes localStorage/sessionStorage geometry.

Do not seed local x/y on a fresh opening. Do not infer restoration from post-constructor or post-render movement: native initial placement and move-triggered preference writes can happen at those stages. Do not consult unrelated Ext state to identify DSM restoration.

The first-show handler leaves an in-bounds configured/restored position alone: no extra move/setter is required. A genuinely fresh opening is centred; restored offscreen geometry is bounded, not blindly centred. Use `setPagePosition` for a necessary correction, or the existing local-coordinate conversion fallback. A single-show guard prevents later drag/resize from being overwritten. Maximised, minimised and standalone-main windows are left to DSM. No resize/centre occurs in `onOpen` or `onRequest`.

Selected native function definitions can be exercised against simulated DOM/base classes, but that is not a live DSM lifecycle. See VALIDATION.md for inherited native acceptance and current-build checks; exact runtime behaviour on other DSM builds requires its own evidence.

## Other boundaries

Colours apply inside SadlerACME's iframe. DSM title bars/native package dialogs and browser prompts remain DSM/browser owned. Generated standalone HTML help retains its existing light reading format. Certificate settings and root jobs are not theme state. The CGI `setup_required` hint reads only existing nonsecret settings and root-published availability metadata; it must never inspect private keys to decide an onboarding message.

## Build and focused checks

```sh
sh build-spk.sh
node tests/launcher-size.js
node tests/launcher-placement.js
python3 tests/wizard-clearance.py
node tests/theme-ui.js
python3 tests/theme-contrast.py
python3 tests/layout-common.py
python3 tests/css-maintenance.py
python3 tests/onboarding-status.py
node tests/workflow-ui.js
node tests/temporary-worker-ui.js
python3 tests/regression.py
python3 tests/ui-browser.py
```

The browser suite requires Python Playwright and Chromium (`CHROMIUM` can name an executable). It renders actual assembled CGI markup and shipped scripts/styles with synthetic state. About-blank in-memory fetch and storage fixtures are deliberate because managed Chromium blocks URL navigation; the suite does not alter browser policy. Screenshots under `tests/browser-1.0.0-1` contain synthetic configuration only. Preference persistence across real browser navigation and DSM session/window behaviour must still be checked natively.

## Regression boundary

`tests/launcher-placement.js` contains 38 current geometry-contract cases. It accepts `SADLER_LAUNCHER_SOURCE` for a source comparison and optional `--dsm-reports` paths for the original, privately supplied DSM definitions. Those reports are not distributed in this source archive. The default model is self-contained.

`tests/wizard-clearance.py` supports `SADLER_WORKFLOW_CSS` for stylesheet comparisons and `SADLER_CLEARANCE_QUICK=1` for a small probe. The overlay scrollbar is deliberately synthetic. Tests cover arrow hit targets, fields, separate form/log/footer scrolling and draft retention without changing production data.

Current transcripts are stored under `tests/RESULTS-1.0.0-1-*`. Historical records are preserved outside this public release archive; they are not relabelled as current test runs.
