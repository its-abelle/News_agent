# News Agent design system

## Direction

A dark, focused editorial studio. Restrained mint-teal accents mark actions and selection, while the reporting question and source map establish the hierarchy. The interface is a workbench, with no marketing landing page or decorative analytics.

## Colours

CSS tokens in `deluxe/ui/style.css` use OKLCH:

| Role | Token | Value |
| --- | --- | --- |
| Canvas | `--bg` | `oklch(0.13 0 0)` |
| Sidebar | `--sidebar` | `oklch(0.16 0.004 200)` |
| Surface | `--surface` | `oklch(0.185 0.004 200)` |
| Primary text | `--ink` | `oklch(0.95 0.005 200)` |
| Secondary text | `--muted` | `oklch(0.73 0.013 200)` |
| Primary action | `--primary` | `oklch(0.87 0.075 190)` |
| Selected surface | `--selection` | `oklch(0.24 0.035 200)` |
| Reporting caution | `--amber` | `oklch(0.86 0.10 80)` |
| Failure | `--danger` | `oklch(0.83 0.09 25)` |

## Typography

Use the operating system's sans-serif for controls and interface headings. Georgia is reserved for the editorial brief and article reading surface. A system monospace identifies small utility labels and the raw Markdown editor. No remote fonts or asset requests are needed.

## Layout

A persistent left rail holds the editorial desk, saved runs and sources/connections. The desk pairs a briefing form with a short explanation of the workflow. Pitch selection pairs a source-led shortlist with the editor's question. Review pairs the editable document with its source map. Columns collapse in sequence on smaller screens; the left rail becomes a menu below 760px.

## Components and states

Use consistent native buttons, inputs, selects and textareas. Mint indicates primary actions and the current selection. Amber indicates reporting gaps, sample material and briefs; red indicates an actionable failure. An active run shows its saved stage and source/search counts. Loading placeholders do not hide existing work. All motion is limited to state feedback and is disabled under reduced-motion preferences.

## Documents

Preview and Markdown views share the same text buffer. Saving produces a separate `-edited.md` file; verified originals remain intact. Downloads return the saved edited copy when present. Sources are clickable, attribution is visible, and raw source HTML is never rendered.
