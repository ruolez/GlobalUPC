# Fonts

Self-hosted so the app has no outside dependency at page load (it runs on a LAN).

| File | Family | Licence |
|---|---|---|
| `source-sans-3-latin*.woff2` | Source Sans 3 (variable, weights 200-900) | SIL Open Font License 1.1, © Adobe |
| `jetbrains-mono-latin*.woff2` | JetBrains Mono (variable, weights 100-800) | SIL Open Font License 1.1, © JetBrains |

Latin and Latin Extended subsets, as distributed by Google Fonts. They are
declared in the `@font-face` block at the top of `styles.css` and cached by
nginx (`location ~ ^/(fonts|vendor)/`), so replace a font under a new file name.
