"""CSS variables, theme definitions, and base reset styles.

This module is the single source of truth for the dashboard's design tokens —
color, typography, spacing, and radius. Other CSS modules reference the semantic
aliases defined here (e.g. --accent, --surface, --text-2, --status-danger,
--diff-add) rather than raw hex/rgba values. The legacy variable names
(--fg, --muted, --green, --blue, ...) are kept as thin aliases so older modules
keep working unchanged.
"""

CSS_RESET = """
  @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&display=swap');
  * { margin: 0; padding: 0; box-sizing: border-box; }
  :root {
    color-scheme: light;

    /* --- Neutrals: three genuinely distinct surfaces --- */
    --bg: #f4f2ee;            /* page background */
    --surface: #ffffff;       /* cards, panels, table */
    --surface-2: #ebe8e2;     /* inset/code blocks, hover */
    --border: #d9d6d0;        /* default hairline */
    --border-strong: #b8b4ac; /* emphasized dividers */

    /* --- Text --- */
    --text-1: #1a1a1a;        /* primary */
    --text-2: #5a5a5a;        /* secondary (darker than the old #777) */
    --text-3: #8a8a8a;        /* faint / disabled only */

    /* --- One primary accent (links, selection, key actions) --- */
    --accent: #2c5aa0;
    --accent-soft: rgba(44, 90, 160, 0.10);

    /* --- Semantic status (one meaning each) + soft tints --- */
    --status-success: #2d7d46;
    --status-success-soft: rgba(45, 125, 70, 0.12);
    --status-danger: #c0392b;
    --status-danger-soft: rgba(192, 57, 43, 0.10);
    --status-warning: #b8860b;
    --status-warning-soft: rgba(184, 134, 11, 0.12);

    /* --- Diff (relocated here from css/sessions.py) --- */
    --diff-add: var(--status-success);
    --diff-add-bg: rgba(45, 125, 70, 0.10);
    --diff-add-bar: rgba(45, 125, 70, 0.55);
    --diff-del: var(--status-danger);
    --diff-del-bg: rgba(192, 57, 43, 0.10);
    --diff-del-bar: rgba(192, 57, 43, 0.55);
    --diff-empty-bg: rgba(0, 0, 0, 0.025);
    --diff-hunk-bg: rgba(44, 90, 160, 0.06);

    /* --- Compare: the one remaining distinct hue, so a "picked" node is never
       confusable with the blue hover/selected accent. --- */
    --compare-accent: #7c3aed;
    --compare-bg: rgba(124, 58, 237, 0.10);

    /* --- Session-tree rail. A tree's branches never merge, so lane POSITION
       already separates them — color carries STATE, not identity, and stays
       bounded: --branch-c0 (neutral) = the checkpoint spine, --branch-c1 (one
       calm teal) = every branch line, --branch-ab (amber) = abandoned. No
       per-branch rainbow. Kept clear of accent-blue and violet --compare-accent
       so a branch line never reads as a selection/pick. --- */
    --branch-c0: var(--text-2);
    --branch-c1: #0f766e;
    --branch-ab: #d97706;

    /* --- Timeline event types. Distinguished primarily by icon + label;
       color is kept mostly neutral with the accent reserved. --- */
    --tl-cell: var(--accent);
    --tl-var: var(--text-2);
    --tl-artifact: var(--text-2);
    --tl-metric: var(--status-warning);
    --tl-obs: var(--text-3);

    /* --- Python syntax tokens: a calm, small palette --- */
    --tok-kw: #8250df;
    --tok-str: #b45309;   /* strings & numbers share one "literal" amber so green is reserved for added/new */
    --tok-num: #b45309;
    --tok-fn: var(--accent);
    --tok-bi: var(--accent);
    --tok-dec: #b45309;

    /* --- Type scale --- */
    --text-xs: 11px;          /* floor — no 9px */
    --text-sm: 12px;
    --text-base: 15px;
    --text-md: 17px;
    --text-lg: 20px;
    --font-ui: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
    --font-mono: 'IBM Plex Mono', ui-monospace, monospace;

    /* --- Spacing (4px base) --- */
    --space-1: 4px; --space-2: 8px; --space-3: 12px;
    --space-4: 16px; --space-5: 24px; --space-6: 32px;

    /* --- Radius --- */
    --radius-sm: 3px; --radius: 6px;

    /* --- Legacy aliases (so existing modules render unchanged) --- */
    --fg: var(--text-1);
    --muted: var(--text-2);
    --card-bg: var(--surface);
    --code-bg: var(--surface-2);
    --green: var(--status-success);
    --red: var(--status-danger);
    --yellow: var(--status-warning);
    --blue: var(--accent);
    --purple: var(--compare-accent);
    --y: var(--status-warning);
  }
  body.dark {
    color-scheme: dark;

    --bg: #1a1a1a;
    --surface: #252525;
    --surface-2: #2d2d2d;
    --border: #444;
    --border-strong: #5a5a5a;

    --text-1: #e0e0e0;
    --text-2: #b0b0b0;
    --text-3: #888;

    --accent: #5c9ce6;
    --accent-soft: rgba(92, 156, 230, 0.14);

    --status-success: #4caf50;
    --status-success-soft: rgba(76, 175, 80, 0.16);
    --status-danger: #ef5350;
    --status-danger-soft: rgba(239, 83, 80, 0.16);
    --status-warning: #ffc107;
    --status-warning-soft: rgba(255, 193, 7, 0.16);

    --diff-add: var(--status-success);
    --diff-add-bg: rgba(76, 175, 80, 0.14);
    --diff-add-bar: rgba(76, 175, 80, 0.55);
    --diff-del: var(--status-danger);
    --diff-del-bg: rgba(239, 83, 80, 0.14);
    --diff-del-bar: rgba(239, 83, 80, 0.55);
    --diff-empty-bg: rgba(255, 255, 255, 0.03);
    --diff-hunk-bg: rgba(92, 156, 230, 0.08);

    --compare-accent: #a78bfa;
    --compare-bg: rgba(167, 139, 250, 0.18);

    /* Branch rail — brighter variants for the dark canvas; spine stays neutral,
       one calm teal for every branch line, amber for abandoned. */
    --branch-c0: var(--text-2);
    --branch-c1: #2dd4bf;
    --branch-ab: #f59e0b;

    --tl-cell: var(--accent);
    --tl-var: var(--text-2);
    --tl-artifact: var(--text-2);
    --tl-metric: var(--status-warning);
    --tl-obs: var(--text-3);

    --tok-kw: #d2a8ff;
    --tok-str: #fbbf24;   /* strings & numbers share one "literal" amber; green stays reserved for added/new */
    --tok-num: #fbbf24;
    --tok-fn: var(--accent);
    --tok-bi: var(--accent);
    --tok-dec: #fbbf24;

    /* Legacy aliases MUST be redeclared here too. A custom property whose value
       is `var(--other)` resolves at the scope where it's declared and inherits
       that frozen value — so an alias defined only in :root keeps its LIGHT
       value in dark mode even though the primitive it points at is overridden
       above. Without these, every surface/card/text using --card-bg/--fg/etc.
       stays light on a dark page (the classic "white cards, dark background"). */
    --fg: var(--text-1);
    --muted: var(--text-2);
    --card-bg: var(--surface);
    --code-bg: var(--surface-2);
    --green: var(--status-success);
    --red: var(--status-danger);
    --yellow: var(--status-warning);
    --blue: var(--accent);
    --purple: var(--compare-accent);
    --y: var(--status-warning);
  }
  body {
    font-family: var(--font-ui);
    background: var(--bg); color: var(--fg);
    margin: 0; padding: 0;
    font-size: var(--text-base); line-height: 1.5;
    overflow: hidden; height: 100vh;
  }
  /* Code, diffs, and raw values stay monospace even though the UI is sans-serif. */
  pre, code,
  .diff-view, .code-diff, .source-view, .tl-code-preview,
  .code-changes, .var-changes, .reproduce-cmd, .cmd-code,
  .export-panel pre {
    font-family: var(--font-mono);
  }
"""
