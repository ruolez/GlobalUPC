# Design system

How Global UPC looks and behaves, and the rules a new page follows. Product
context (who uses it and for what) is in `PRODUCT.md`. Everything here lives in
`frontend/src/styles.css`; the top of that file is the source of truth.

## Direction

A back-office ledger: calm, dense and exact. Warm paper neutrals with one
banker's-green accent on the default light theme; seven dark themes share the
same structure. The interface is a working tool, so familiar controls,
consistency and legible numbers come before expression.

- **Depth**: surfaces plus one hairline. The page is the darkest surface, cards
  sit lighter on it, controls are the lightest. Shadows only for things that
  float (popovers, toasts, dialogs).
- **Colour**: neutral structure, one accent. The accent means *primary action*
  or *selected*. Green / amber / red mean success / warning / danger and
  nothing else.
- **Type**: Source Sans 3 for everything, JetBrains Mono only for identifiers
  people compare digit by digit (UPC, invoice, quotation, tracking numbers).
  Both are self-hosted in `frontend/src/fonts/`.
- **Labels** are sentence case. Uppercase survives only on short status codes.

## Tokens

Defined on `:root` (palette = default dark theme) and overridden per theme in
`[data-theme="…"]`. A feature never needs a colour, font-size or radius literal.

### Palette (per theme)

| Token | Role |
|---|---|
| `--bg-primary` | Page |
| `--bg-secondary` | Cards, panels, table headers |
| `--bg-tertiary` | Controls, raised inner surfaces, popovers |
| `--bg-hover` | Hover fill |
| `--border-color` | Hairlines and card borders |
| `--text-primary` / `--text-secondary` / `--text-tertiary` | Body / supporting / metadata (4.5:1 or better on page, card and control surfaces in every theme) |
| `--accent-primary` / `--accent-hover` | Primary action, selection |
| `--on-accent` | Text on an accent or danger fill |
| `--success` / `--warning` / `--danger` / `--info` | Status only |

### Derived (same in every theme, computed with `color-mix`)

`--border-subtle`, `--border-strong`, `--control-bg`, `--control-border`,
`--control-border-hover`, `--accent-soft`, `--accent-soft-border`,
`--success-soft`, `--warning-soft`, `--danger-soft`, `--info-soft`,
`--focus-ring`, `--row-hover`, `--row-stripe`, `--scrim`.

For a new tint use `color-mix(in srgb, var(--token) N%, var(--bg-secondary))`,
never a hex or rgba value.

### Type scale

Source Sans runs about a pixel smaller than a system sans, so the steps sit a
pixel above the usual ones.

| Token | px | Use |
|---|---|---|
| `--text-3xs` | 11 | Counters inside badges |
| `--text-2xs` | 12 | Captions, chips, tags |
| `--text-xs` | 13 | Secondary text, table headers, helper text |
| `--text-sm` | 14 | Controls, table cells |
| `--text-base` | 15 | Body |
| `--text-md` | 16 | Card titles, emphasised body |
| `--text-lg` | 18 | Section and dialog titles |
| `--text-xl` | 21 | Panel titles, headline counts |
| `--text-2xl` | 25 | Page titles |
| `--text-3xl` | 30 | Headline figures |

Weights: 400 body, 550 controls, 600 labels, 650 titles and selected items,
700 page titles. Numbers in tables use `font-variant-numeric: tabular-nums`
(set on every `<table>`) and are right-aligned.

### Shape, size, motion

- Radius: `--radius-sm` 4px (tags, small buttons), `--radius-md` 6px
  (controls), `--radius-lg` 10px (cards, dialogs), `--radius-pill` (chips).
- Control height: 34px by default (`--control-h`), 28px small, 24px minimum.
  On touch devices buttons grow to 40px.
- Motion: 120-180ms, `--ease-out`. State changes only; nothing animates on
  page load. `--transition` covers colour, border, shadow and opacity.

## Layout

- **Shell**: sidebar (`--sidebar-w` 216px, collapsible to a 56px icon rail,
  remembered per browser) + main column. Under 900px the sidebar becomes a
  drawer opened from the app bar.
- **Page header**: every page starts with `<header class="page-header">`
  holding an `<h2>` and one `.subtitle` line; page-level actions go in
  `.page-header-actions` on the right.
- **Report page order**: header → config bar (`.config-bar`, when the page has
  its own store setup) → control card (`.card` + `.toolbar`, or a
  `.card-header` + padded body for a longer form) → results.
- **Forms**: fields first, the action last in `.form-actions`. A field is a
  `.form-group` (label above, `.field-help` below). Optional fields say so in
  the label (`.label-optional`).

## Components

| Component | Class | Notes |
|---|---|---|
| Button | `.btn` + `.btn-primary` / `.btn-secondary` / `.btn-ghost` / `.btn-danger` / `.btn-danger-quiet` | One primary per view. Sizes `.btn-sm`, `.btn-xs`, `.btn-lg`; `.btn-icon` for a square icon button. A Delete that repeats on every row is `.btn-danger-quiet`. |
| Quick-pick chip | `.btn.btn-chip` inside `.chip-row` | Date presets, select all / none. |
| Text field, select, textarea | plain elements | Styled globally; do not restyle. Selects get one chevron everywhere. |
| Date range | `.date-range` (two date inputs with `<span>to</span>`) | Presets go in a `.chip-row` under it. |
| Checkbox / radio | plain elements | Themed through `accent-color`. A wrapping label uses `.check-label`. |
| Card | `.card`, `.card-header`, `.card-body` | No nested cards. |
| Table | `.data-table` inside `.table-container` | Sentence-case headers, sortable headers use `.qip-sortable`. |
| Tabs | `.tab-bar` / `.sa-subnav` / `.bov-subnav` | One underline style. |
| Segmented switch | `.qip-segmented`, `.sales-toggle-group`, `.sa-chip-group`, `.tab-pills`, `.bov-cost-seg` | One of a few options; the chosen one carries the accent tint. |
| Filter chip | `.me-chip`, `.sa-chip-mini` | Toggle any number. |
| Status chip | `.qip-status-chip` | Sentence case. |
| Empty state | `.empty-state` | Icon, one line saying what is empty, one line saying what to do. |
| Notice | `.notice` (+ `.is-warning` / `.is-error`) | Inline, stays on the page. |
| Modal | `.modal` > `.modal-content` > `.modal-header` / `.modal-body` or `.modal-form` / `.modal-footer` | Opened with `openModal(id)` or by adding `.active`. |

## Behaviour (in `app.js`, section "UI kit")

- **Dialogs**: `await uiConfirm("Question?\n\nDetail", { confirmLabel, danger })`
  and `uiAlert(text)` replace `confirm()` / `alert()`. The button names the
  action; a destructive dialog opens with focus on Cancel. `alert()` itself is
  redirected: a short message becomes a toast, a long one a dialog.
- **Toasts**: `showToast(message, "success" | "error" | "warning" | "info")`.
  Errors stay 7 seconds.
- **Every `.modal`** gets `role="dialog"`, a label from its heading, a focus
  trap, focus return to the opener, background scroll lock and Escape-to-close.
  Modals with their own Escape rules are listed in `OWN_ESCAPE`.
- **Icons**: inline SVG, 2px stroke, `currentColor`. From JavaScript use
  `uiIcon("trash" | "ban" | "search" | "box" | "refresh" | "clock" | "check" |
  "pencil" | "chevron")`. No emoji.
- **Labels**: a `.form-group` label without `for` is wired to the group's
  single control at load, and bare date pairs are named "From date" / "To date".

## Accessibility floor

WCAG 2.2 AA: 4.5:1 text contrast in every theme, a visible `:focus-visible`
ring on everything focusable, 24px minimum target size (40px on touch),
`prefers-reduced-motion` respected, no information carried by colour alone.

## Checking a change

There is no build step and no visual test suite. After a UI change, look at
the page in the light theme and one dark theme at 1440, 1100 and 390 px wide,
and run `impeccable detect --json frontend/src/index.html`.
