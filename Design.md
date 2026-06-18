# Design System — TTB Label Verification

A civic-grade compliance tool that adopts **Linear's design language** — ultra-minimal,
precise, a near-black canvas with a single lavender-blue accent and a surface-ladder
hierarchy — re-tuned to be **Section 508 / WCAG 2.1 AA compliant** for an all-day
federal audience (~47 reviewers across a wide tech-comfort range). Linear's reference
spec: <https://getdesign.md/linear.app/design-md>.

The aesthetic is Linear's; the **non-negotiables are accessibility and verdict-first
clarity**. Where Linear's marketing choices conflict with 508 (low-contrast text,
opacity focus rings, dark-only, color-as-meaning), this system documents the compliant
adaptation and the reason. Every color pair below is contrast-audited (ratios are real,
computed sRGB WCAG values).

> **Implementation status.** This is the **target** design system. The shipped CSS
> (`app/static/style.css`) still implements the prior light theme; migrating it to the
> tokens below is a follow-up. Treat this file as the spec an implementer follows.

---

## Principles

1. **Verdict first.** PASS / FLAG / NEEDS-REVIEW is the loudest thing on the page; the
   dark, quiet chrome exists to make the verdict shout. (Linear leads with product
   screenshots; we lead with the verdict.)
2. **Lavender is scarce.** The accent appears only on the brand mark, the primary CTA,
   focus rings, and link emphasis — never as a fill or decoration.
3. **Hierarchy by surface, not shadow.** A four-step charcoal ladder + hairline borders
   carry depth; the dark canvas *is* the whitespace.
4. **Accessible by construction.** AA contrast, visible focus, ≥44px targets, keyboard
   operable, color never the sole signal, motion that respects user preference.
5. **Honest states.** Pass, flag, needs-review, and couldn't-read each look distinct —
   by **icon + label + color**, so they read without relying on hue.
6. **Local + fast.** No outbound at runtime (the deploy blocks it): self-host the
   display font or fall back to the system stack; server-rendered; usable with no JS.

---

## Color tokens

Dark canvas + four-step surface ladder + one lavender accent, from Linear. Text and
interactive tokens are **adjusted where Linear's value fails AA** — flagged below.

### Surfaces & lines
| Token | Value | Use |
|-------|-------|-----|
| `--canvas` | `#010102` | Page background (near-black, faint blue tint — not pure `#000`). |
| `--surface-1` | `#0f1011` | Default cards, result panels, input fields. |
| `--surface-2` | `#141516` | Featured/hovered cards, selected tabs, status pills. |
| `--surface-3` | `#18191a` | Sub-nav, menus, the chat widget panel. |
| `--surface-4` | `#191a1b` | Deepest lifted surface. |
| `--hairline` | `#23252a` | **Decorative** 1px dividers only (1.24:1 — not a state/boundary). |
| `--hairline-strong` | `#34343a` | Decorative stronger dividers (1.69:1). |
| `--border-interactive` | `#6b7079` | **508 addition** — the perceivable boundary of inputs/buttons/focusable tiles. 4.19:1 vs canvas, 3.83:1 vs surface-1 (meets WCAG 1.4.11 ≥3:1). Linear's hairlines are too faint to bound interactive controls. |

### Text
| Token | Value | On canvas | Use |
|-------|-------|-----------|-----|
| `--ink` | `#f7f8f8` | **19.6:1** | Headlines, emphasized body. |
| `--ink-muted` | `#d0d6e0` | **14.3:1** | Secondary text. |
| `--ink-subtle` | `#8a8f98` | **6.4:1** | Captions, meta, footer (smallest muted text — still AA). |
| `--ink-tertiary` | `#62666d` | 3.6:1 | **Disabled / decorative ONLY** — never body or footnote text (fails AA for normal text; WCAG exempts disabled controls). |

### Accent & semantic
| Token | Value | Contrast | Use |
|-------|-------|----------|-----|
| `--primary` | `#5e6ad2` | white text **4.70:1** | Lavender — brand mark + primary CTA **fill** (with white label). |
| `--primary-hover` | `#828fff` | **7.27:1** on canvas | Hover fill **and** the value for **link / lavender text** (Linear's `#5e6ad2` as text is only 4.44:1 — fails AA; use this lighter lavender for any lavender *text*). |
| `--primary-focus` | `#5e69d1` | 4.39:1 vs canvas | Focus-ring color (solid, full opacity — see Focus). |
| `--on-primary` | `#ffffff` | — | Text/icon on a lavender fill. |
| `--success` | `#27a644` | 5.8:1 on surface-2 | Success status — always paired with an icon/label. |

### Verdict colors (domain requirement, a documented deviation)
Linear ships a **single** accent. A verification tool cannot: PASS/FLAG/REVIEW are
*meaning*, and 508 §1.4.1 forbids conveying them by color alone, so each is a distinct,
AA-contrast, **icon-and-label-paired** state. Tints chosen to read on the dark canvas:

| State | Text token | Value | On canvas | Pairs with |
|-------|-----------|-------|-----------|-----------|
| PASS | `--pass` | `#3fb950` | **8.2:1** | ✓ icon + "PASS" |
| FLAG | `--flag` | `#ff7b72` | **8.3:1** | ✕ icon + "FLAG" |
| NEEDS-REVIEW | `--review` | `#e3b341` | **10.7:1** | ⚠ icon + "REVIEW" |
| UNREADABLE | `--unread` | `#f0b86e` | **11.7:1** | ◌ icon + "Couldn't read" |

Verdict surfaces stay on the surface ladder (e.g. `--surface-1`) with a 4px left bar in
the verdict color **plus** the icon+label — never a saturated fill, never hue-only.

---

## Typography

Linear's display/text/mono scale with aggressive negative tracking. The family is
proprietary; the **508 + offline-safe** substitute is a self-hosted **Inter** (or
**Geist**) bundled with the app, falling back to the system stack — no runtime fetch.

- **Sans:** `Inter, "SF Pro Display", system-ui, -apple-system, "Segoe UI", Roboto, sans-serif`
- **Mono:** `"JetBrains Mono", ui-monospace, "SF Mono", Menlo, monospace` (filenames, raw OCR, IDs)

| Token | Size | Weight | Line | Tracking | Use |
|-------|------|--------|------|----------|-----|
| `display-md` | 40px | 600 | 1.15 | −1.0px | The verdict headline (our largest type — a tool, not a hero). |
| `headline` | 28px | 600 | 1.20 | −0.6px | Page titles, section openers. |
| `card-title` | 22px | 500 | 1.25 | −0.4px | Card / result titles. |
| `subhead` | 20px | 400 | 1.40 | −0.2px | Lead paragraphs. |
| `body` | 16px | 400 | 1.50 | −0.05px | Default body. |
| `body-sm` | 14px | 400 | 1.50 | 0 | Card body, table cells, footer. |
| `button` | 14px | 500 | 1.20 | 0 | All button labels. |
| `eyebrow` | 13px | 500 | 1.30 | **+0.4px** | Section eyebrow / field labels (positive tracking, often UPPERCASE). |
| `caption` | 12px | 400 | 1.40 | 0 | Meta, status, hint. |
| `mono` | 13px | 400 | 1.50 | 0 | Filenames, raw OCR, citations. |

Principles: single voice display→body (weight 600 display / 400 body — Linear resists
700+); negative tracking on display, positive on the eyebrow as taxonomy; mono only in
code/data contexts. **Never below 12px**; body text holds ≥16px for the older audience.

---

## Spacing, shape, elevation, motion

- **Spacing** (4px base): `xxs` 4 · `xs` 8 · `sm` 12 · `md` 16 · `lg` 24 · `xl` 32 ·
  `xxl` 48 · `section` 96. Card interior 24px; CTA/banner 32–48px.
- **Radius:** `xs` 4 (chips/badges) · `md` 8 (**all buttons + inputs**) · `lg` 12
  (cards) · `xl` 16 (image/preview panels) · `pill` 9999 (status pills, toggles). Do
  **not** pill-round CTAs.
- **Elevation = surface ladder, not shadow.** Level 0 flat (body) → L1 `surface-1` +
  hairline (cards) → L2 `surface-2` (featured/hover) → L3 `surface-3` (menus, chat
  panel). Drop shadows are avoided on dark, as in Linear.
- **Focus (508 §2.4.7 / §1.4.11):** a **2px solid, full-opacity** ring in
  `--primary-focus` (or `--primary-hover` for extra margin), ≥3:1 against its
  background, on **every** interactive element. Never Linear's 50%-opacity ring.
- **Motion:** 150ms ease on hover/focus; honor `prefers-reduced-motion: reduce`
  (disable transitions/transforms). No atmospheric gradients, no spotlight cards.

---

## Components

Each maps to a Linear token set, adjusted for our domain + 508. Borders that *bound* a
control use `--border-interactive`; decorative dividers use `--hairline`.

- **Top nav** — sticky bar on `--canvas`, hairline bottom. Lavender `TTB` wordmark left;
  quiet links (Single · Text · Batch · Chat) right; active route in `--ink` + bold.
  Includes a **skip-to-content** link and a **theme toggle** (see Themes).
- **Button — primary** — `--primary` fill, `--on-primary` label, `button` type, 8px
  radius, 8×14 padding, ≥44px tap height. Hover → `--primary-hover`.
- **Button — secondary** — `--surface-1` fill, `--ink` label, `--border-interactive`
  1px. **Tertiary** — text-only on canvas, lavender (`--primary-hover`) label.
- **Card / result panel** — `--surface-1`, 1px `--hairline`, 12px radius, 24px padding.
- **Text input / dropzone** — `--surface-1`, `--ink` text, **`--border-interactive`**
  1px (so the field is perceivable per §1.4.11), 8px radius; focus adds the 2px ring.
- **Verdict banner** — `--surface-1` panel, 4px left bar in the verdict color, the
  verdict **icon + label** in the verdict text token, `display-md` headline.
- **Field result card** — `--surface-1`, verdict left bar + pill badge (icon+label),
  an `Application says` / `On the label` definition pair.
- **Status / verdict pill** — `--surface-2` bg, `pill` radius, caption type, icon+label.
- **Batch table** — hairline rows on `--canvas`, pill badge per cell; the "needs
  attention" filter hides passing rows. Rows are keyboard-focusable.
- **Pop-out chat widget** (`chat-widget.js`) — launcher on `--primary`; panel on
  `--surface-3` with `--hairline` border, docked bottom-right, minimizable. Inherits
  the same focus, target-size, and `prefers-reduced-motion` rules.

---

## Section 508 / WCAG 2.1 AA compliance

The reason this isn't just "Linear, but dark." Every requirement below is enforced by
the tokens/components above; the contrast figures are computed, not asserted.

| Criterion | Requirement | How it's met |
|-----------|-------------|--------------|
| **1.4.3** Contrast (text) | ≥4.5:1 (≥3:1 large) | All text tokens audited above; `--ink-tertiary` restricted to disabled; lavender *text* uses `--primary-hover` (7.27:1), not `--primary` (4.44:1). |
| **1.4.11** Non-text contrast | ≥3:1 for UI boundaries & focus | `--border-interactive` (≥3.8:1) bounds controls; focus ring ≥4.0:1. |
| **2.4.7** Focus visible | Always | 2px solid full-opacity ring on every interactive element. |
| **1.4.1** Use of color | Not sole means | Verdicts + status carry **icon + text label**, not hue alone. |
| **2.5.5 / 2.5.8** Target size | ≥44px (≥24px min) | Buttons, pills, inputs, table rows hold ≥44px tap height. |
| **2.1.1** Keyboard | Fully operable | All actions reachable/operable by keyboard; logical focus order; the chat confirm Approve/Cancel is keyboard-operable. |
| **2.4.1** Bypass blocks | Skip link | "Skip to content" before the nav. |
| **1.4.12** Text spacing | No clipping | Line-height ≥1.5 body; layouts reflow with user spacing overrides. |
| **2.3.3 / motion** | Respect preference | `prefers-reduced-motion: reduce` disables transitions. |
| **1.4.10** Reflow | 320px, no h-scroll | Single-column; grids collapse 3→2→1; display scales down. |
| **forced-colors** | Windows High Contrast | Honor `forced-colors: active` — keep borders/focus visible, don't rely on custom bg. |
| **4.1.2** Name/role/value | Semantic + ARIA | Landmarks (`header`/`main`/`nav`), labelled controls, `aria-live` on the verdict + chat log. |

### Themes — don't force dark-only
Linear says "don't ship a light-mode page." For a federal tool serving low-vision and
older users (glare, astigmatism, light-sensitivity vary by person), **forcing dark-only
is itself an accessibility risk**. So the system ships the **Linear-inspired dark theme
as default** *and* retains a **508-audited light theme**, honoring
`prefers-color-scheme` with a manual toggle. Both themes meet the same AA bar. This is a
deliberate, documented deviation from Linear's marketing guidance.

---

## Documented deviations from Linear (with rationale)

1. **Verdict semantic colors** beyond the single lavender accent — PASS/FLAG/REVIEW are
   *meaning*, not decoration, and §1.4.1 requires them to be distinct + non-hue-reliant.
2. **Lavender as text uses `--primary-hover` (#828fff)**, not `--primary` — the darker
   lavender fails AA as text (4.44:1).
3. **`--border-interactive`** added — Linear's hairlines (1.2–1.7:1) can't legally bound
   an interactive control (§1.4.11).
4. **Solid full-opacity focus ring** — Linear's 50%-opacity ring would drop below 3:1.
5. **A light theme is retained** and user-selectable (see Themes).
6. **Restrained motion + local fonts** — honor reduced-motion; no runtime font fetch
   (the deploy blocks outbound), so the display font is self-hosted or system-stack.

---

## Voice

Plain, reassuring, second person. "We check the brand, alcohol content, and the
government warning." Never jargon. Errors say what to do next, not just what broke. The
dark, precise chrome should feel like trustworthy instrumentation — calm, not flashy.
