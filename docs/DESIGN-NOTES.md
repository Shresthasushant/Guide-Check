# Design notes — the Guide Check site

Why the front end looks and behaves the way it does. The palette figures here
are computed, not chosen by eye.

## Structure

Five pages, plain HTML, served by `app.py` at clean URLs. No build step, no
framework, no bundler — the whole front end is three files in `static/assets/`.

| URL | File | Job |
|---|---|---|
| `/` | `static/index.html` | What Guide Check does, in plain language |
| `/how-to-use` | `static/how-to-use.html` | Filling the form, reading the result |
| `/check` | `static/check.html` | The tool itself |
| `/how-it-works` | `static/how-it-works.html` | Method and measured accuracy |
| `/limits` | `static/limits.html` | What it cannot tell you |
| — | `static/404.html` | Served by the 404 handler |

`static/assets/app.css` is the whole stylesheet. `app.js` is the shared chrome
(theme toggle, mobile nav, current-page marking). `check.js` is the tool: the
API call, the rendering, and the three charts.

Each page carries its own copy of the header and footer. That duplication is
deliberate — it keeps every page a standalone file that can be opened, diffed
and understood without a template engine in the way.

## Typography

The project's existing faces are kept: **Source Serif 4** for prose, **IBM Plex
Mono** for every number, label and piece of chrome. The serif/mono pairing reads
as a workpaper rather than a dashboard, which suits a tool whose output is
evidence. Both load from Google Fonts with real fallback stacks, so the page is
readable if the CDN is blocked.

All figures — stat tiles, axis ticks, table numbers — are mono, the project's
data face. `tabular-nums` is applied only where numbers align vertically (table
columns, axis ticks), not to standalone figures.

## Colour

Light and dark are both defined explicitly. Dark is selected, not an inverted
light: tokens are redefined under `@media (prefers-color-scheme: dark)` guarded
by `:root:not([data-theme="light"])`, and again under `:root[data-theme="dark"]`
so the in-page toggle wins in both directions. The toggle persists in
`localStorage`, wrapped in try/catch because private-mode browsers throw on it.

### Validated slots

Every colour that carries meaning was run through the data-viz six-checks
validator against **the surfaces the charts actually render on** — `#f7f8f4`
light and `#1b1f19` dark — not against a default surface.

**Severity (status).** Three hues, with the alarm hue carrying a second, darker
step for "well below":

| Band | Light | Dark |
|---|---|---|
| consistent | `#15784a` | `#2a9270` |
| at the low end | `#a8841a` | `#ad8a34` |
| below the evidence | `#b8462e` | `#e0564b` |
| well below | `#87301f` | `#f2766a` |

The three-hue set passes lightness band, chroma floor, normal-vision separation
and contrast in both modes (light: worst all-pairs normal-vision ΔE 15.4, all
slots ≥ 3:1 on the surface; dark: worst 15.1).

Adjacent red-versus-amber sits in the CVD warn band, which **no** four-step
red/amber/green status scale can escape — the two are confusable under
deuteranopia by construction. The mitigation is the one the status rule
requires: a severity is **never** carried by colour alone. Every badge ships an
icon and the words, the verdict repeats the finding in a sentence, and the
`how-to-use` key is a labelled table rather than a row of colour chips.

**Diverging pair (the SHAP drivers).** Blue ↔ warm, gray midpoint:
`#2d6d9e` / `#c25a33` light, `#4a97d4` / `#cf7346` dark. Both pass every check
in both modes (worst CVD ΔE 16.4 light, 20.1 dark; normal-vision 25.1 / 24.6).
Bars are direct-labelled with a signed percentage, so polarity is carried by
direction and number as well as hue.

**The comparables.** Deliberately a de-emphasis grey (`#69776f` / `#97a199`,
both ≥ 3.7:1) — they are context, and the guide is the emphasis mark. This is
the emphasis form, not a categorical series, so the chroma floor does not apply.

## The charts

Three, each picked by what the reader has to do with the data.

**Where the guide sits — a beeswarm strip plot.** The job is to place one value
inside a distribution, so the form is 25 dots on a price axis with the guide
marked. It replaced a 0–100 gauge, which hid the thing that matters: the
comparables are spread across hundreds of thousands of dollars, and a percentile
alone conceals that. You can count the dots to the left of the guide line.

**What moved the estimate — a diverging bar chart.** The job is polarity
(raises / lowers), centred on a neutral zero rule.

**The model's range — a range bar.** One interval and one point. Not a chart of
anything else; a stat tile with a track.

Every chart:

- re-renders on resize against the container's measured width, so text stays at
  a fixed size instead of scaling with a viewBox;
- draws from CSS custom properties, so switching theme repaints without a redraw;
- has a **table view** beneath it holding the same numbers, because no value may
  be reachable only by hovering;
- carries an `aria-label` summarising what it shows.

Driver bars are keyboard-focusable (there are four). The 25 comparable dots are
not — 25 tab stops would be worse than useless, and the table view is the
accessible twin.

## Accessibility

Skip link; landmarks; visible `:focus-visible` rings; `aria-current` on the
current nav item; `aria-live` on the result and the error message;
`aria-invalid` on fields that failed validation; `prefers-reduced-motion`
honoured. Body text clears 4.5:1 in both themes and muted text clears 4:1.

Wide tables scroll inside their own `overflow-x: auto` container so the page
body never scrolls sideways.

## Deployment

- Pages are static files; only `/api/check` and `/api/suburbs` touch the model.
- `/healthz` answers without loading anything, so a platform health check cannot
  block on the 30–45 second model load or restart-loop the service.
  `render.yaml` points at it.
- HTML is sent `Cache-Control: no-cache` so a redeploy is visible immediately;
  `/assets/` gets one hour.
- A print stylesheet drops the chrome and the form, expands the table views and
  keeps cards from breaking across pages, so a result prints as a workpaper.
