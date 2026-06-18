# Design System — TTB Label Verification

The interface is a government compliance tool used all day by ~47 agents across a
wide tech-comfort range (some 50+, low-tech). So the design goal is **calm,
trustworthy, and obvious** — civic-grade clarity, not startup flash. Every screen
should read in seconds and never make a tired agent hunt for the next step.

## Principles

1. **Verdict first.** The PASS / FLAG / NEEDS-REVIEW result is the loudest thing on
   the page. Everything else supports it.
2. **One obvious path.** A single primary action per screen, large and unmistakable.
3. **Calm, not clinical.** Soft surfaces, generous whitespace, restrained color —
   color is reserved to *mean* something (a verdict), never decoration.
4. **Legible over dense.** Large type, high contrast (WCAG-AA), big targets (≥44px).
5. **Honest states.** Pass, flag, needs-review, and couldn't-read each look
   distinct and unambiguous.
6. **Local + fast.** No external fonts or assets at runtime (the deploy blocks
   outbound) — a refined system-font stack, server-rendered, no JS required to use.

## Color

Semantic, restrained. Color carries meaning; surfaces stay neutral.

| Token | Value | Use |
|-------|-------|-----|
| `--bg` | `#eef1f6` | App background (cool, soft) |
| `--surface` | `#ffffff` | Cards, header |
| `--surface-sunken` | `#f7f9fc` | Insets, table headers, code |
| `--border` / `--border-strong` | `#e3e8ef` / `#cdd5e0` | Hairlines, inputs |
| `--ink` / `--ink-soft` / `--muted` | `#0b1524` / `#3b4a5e` / `#6b7a8d` | Text hierarchy |
| `--brand` / `--accent` | `#1e3a8a` / `#2563eb` | Wordmark/headers · interactive (buttons, links, focus) |
| Pass | text `#0f7a3d`, bg `#e7f6ed`, line `#b7e3c6` | Compliant |
| Flag | text `#c0271f`, bg `#fdeceb`, line `#f3c2bf` | Non-compliant |
| Review | text `#b06a00`, bg `#fdf2e3`, line `#f3d9a8` | Low-confidence read |
| Unreadable | text `#854d0e`, bg `#fef6e0` | Couldn't read |

## Type

System stack: `ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif`;
mono `ui-monospace, Menlo, monospace` for filenames / raw OCR.

- **H1** 2.1rem / 800 / tight tracking — page title & verdict
- **H2** 1.35rem / 700
- **Body** 1.0625rem (17px) / 1.6
- **Label** 0.8rem / 700 / UPPERCASE / 0.06em tracking / muted
- **Small** 0.9rem / muted

## Shape, depth, motion

- Radius: `--r-sm` 8px · `--r` 12px · `--r-lg` 18px · pill 999px
- Shadow (one soft elevation): `0 2px 4px rgba(11,21,36,.04), 0 12px 28px -14px rgba(11,21,36,.18)`
- Borders are 1px hairlines; verdict cards add a 6px left color bar
- Motion: 150ms ease on hover/focus only. No gratuitous animation.
- Spacing: 4px base scale (`.5/1/1.5/2/3/4` rem rhythm)

## Components

- **Header** — sticky, white, hairline bottom. A rounded `TTB` badge (brand) +
  "Label Verification" wordmark on the left; quiet nav (Single · Text · Batch) on
  the right. The active route is bolded.
- **Card** — white, 1px border, soft shadow, `--r-lg` radius, generous padding.
- **Buttons** — primary: `--accent` fill, white, 700, full-width on forms, hover
  darken + lift. Secondary: white with accent border/text.
- **Inputs / dropzone** — large, 2px border, 3px accent focus ring. The dropzone
  is a dashed drop target with an inline thumbnail preview.
- **Verdict banner** — full-width, verdict-tinted bg, large H1, 6px left bar.
- **Field result card** — white card, left bar in the verdict color, a pill badge
  (PASS/FLAG), and a `Application says` / `On the label` definition pair.
- **Batch table** — zebra-free, hairline rows, pill badges per cell; the "needs
  attention" filter hides passing rows.

## Layout

- Single-column. Content max-width **720px** (single label / text) or **980px**
  (batch table). Comfortable top rhythm; the header is the only chrome.
- Print: a clean one-page report — banner + fields + thumbnail, nav/buttons hidden.

## Voice

Plain, reassuring, second person. "We check the brand, alcohol content, and the
government warning." Never jargon. Errors say what to do next, not just what broke.
