"""CSS for diff views, code changes, and variable displays."""

CSS_CODE = """
  .diff-view {
    background: var(--code-bg); padding: 16px; font-size: 13px;
    overflow-x: auto; max-height: 500px; overflow-y: auto;
    white-space: pre; border: 1px solid var(--border); border-radius: 4px;
  }
  .diff-add { color: var(--green); }
  .diff-del { color: var(--red); }
  .diff-hunk { color: var(--blue); font-weight: 600; }

  /* Shared Python token colors (IDE-ish), theme-aware. Used by the Sessions
     cell viewer and every code/diff surface in the experiment detail view.
     Unscoped on purpose: .tok-* only ever appears inside highlighted code. */
  .tok-kw  { color: var(--tok-kw); font-weight: 600; }
  .tok-str { color: var(--tok-str); }
  .tok-com { color: var(--muted); font-style: italic; }
  .tok-num { color: var(--tok-num); }
  .tok-fn  { color: var(--tok-fn); }
  .tok-bi  { color: var(--tok-bi); }
  .tok-dec { color: var(--tok-dec); }

  /* Stale-print flag — a print() with a hardcoded number that's likely a value
     the author meant to interpolate. Shared by the Sessions cell viewer and the
     experiment Timeline. Amber = "warning / look here", distinct from add/del. */
  .stale-print-badge {
    display: inline-block; font-size: 10px; font-weight: 600;
    color: var(--yellow); border: 1px solid var(--yellow);
    border-radius: 3px; padding: 0 5px; margin-left: 6px;
    vertical-align: middle; cursor: help; white-space: nowrap;
  }
  .cl.cl-stale, .stale-line { background: var(--status-warning-soft, rgba(220,160,0,0.10)); }
  .cl-stale-mark, .stale-print-mark { color: var(--yellow); cursor: help; }

  /* Unified diff with tinted lines, a sign gutter, and word-level spotlights.
     Lines carry a background tint + left bar (not just colored text) so syntax
     highlighting and add/del status can coexist. */
  .code-diff {
    font-family: 'IBM Plex Mono', ui-monospace, monospace; font-size: 12.5px;
    line-height: 1.55; border: 1px solid var(--border); border-radius: 4px;
    overflow: auto; max-height: 500px; background: var(--code-bg);
  }
  .code-diff .dl {
    display: flex; align-items: flex-start;
    white-space: pre-wrap; word-break: break-word; padding-right: 8px;
  }
  .code-diff .dl-sign {
    flex: 0 0 20px; text-align: center; user-select: none;
    color: var(--muted); opacity: 0.7;
  }
  .code-diff .dl-text { flex: 1 1 auto; min-width: 0; }
  /* Old/new line-number gutter (only present on .code-diff-numbered). */
  .code-diff .dl-no {
    flex: 0 0 auto; min-width: 64px; box-sizing: border-box;
    display: inline-flex; user-select: none; font-size: 11px;
    color: var(--text-3); border-right: 1px solid var(--border); margin-right: 8px;
  }
  .code-diff .dl-no-o, .code-diff .dl-no-n {
    width: 26px; text-align: right; padding-right: 6px; display: inline-block;
  }
  .code-diff .dl-add { background: var(--diff-add-bg); box-shadow: inset 3px 0 0 var(--diff-add-bar); }
  .code-diff .dl-del { background: var(--diff-del-bg); box-shadow: inset 3px 0 0 var(--diff-del-bar); }
  .code-diff .dl-add .dl-sign { color: var(--green); opacity: 1; }
  .code-diff .dl-del .dl-sign { color: var(--red); opacity: 1; }
  .code-diff .dl-hunk {
    background: var(--diff-hunk-bg); color: var(--blue);
    padding: 1px 8px; font-size: 11px; user-select: none;
  }
  /* The actual changed span within an in-place edit — a medium tint pops against
     the line's own faint add/del wash so the eye lands on the 0.7 → 0.5, but the
     text keeps normal ink (no white-out) so it stays readable when you expand a
     long line. The colored underline carries the add/del signal. */
  .dword-add, .dword-del {
    border-radius: 3px; padding: 0 2px; font-weight: 600;
  }
  .dword-add { background: var(--diff-add-bg); box-shadow: inset 0 -2px 0 var(--diff-add-bar); }
  .dword-del { background: var(--diff-del-bg); box-shadow: inset 0 -2px 0 var(--diff-del-bar); text-decoration: line-through; text-decoration-color: var(--diff-del-bar); }

  /* Inside a diff, color means one thing: added vs. removed. Syntax token colors
     are muted to plain ink here so a green string literal can't read as an
     "added" line — the red/green tints, sign gutter, and word-pills carry all the
     change semantics. (Non-diff code surfaces keep full syntax highlighting.) */
  .code-diff .tok-kw, .code-diff .tok-str, .code-diff .tok-num,
  .code-diff .tok-fn, .code-diff .tok-bi, .code-diff .tok-dec {
    color: var(--text-1); font-weight: inherit;
  }
  .code-diff .tok-com { color: var(--text-3); }

  /* When a .code-diff is dropped into the existing boxed containers, drop the
     inner box so we don't double-frame. */
  .code-changes .code-diff { border: none; background: transparent; max-height: none; }
  .diff-view:has(.code-diff) { padding: 0; border: none; background: transparent; overflow: visible; max-height: none; }
  .tl-diff .code-diff { font-size: 11.5px; max-height: none; }
  .code-changes { background: var(--code-bg); border: 1px solid var(--border); padding: 16px; margin-bottom: 20px; font-size: 13px; border-radius: 4px; }
  .code-changes .change-item { margin-bottom: 10px; }
  .code-changes .change-label { color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 4px; }
  .code-changes .change-diff { white-space: pre-wrap; }
  .var-changes { background: var(--code-bg); border: 1px solid var(--border); padding: 16px; margin-bottom: 20px; font-size: 13px; border-radius: 4px; }
  .var-changes table { width: 100%; table-layout: fixed; }
  .var-changes td { padding: 4px 8px; border-bottom: 1px solid var(--border); vertical-align: top; word-break: break-word; }
  .var-changes td:first-child { width: 30%; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .var-changes .var-name { color: var(--blue); font-weight: 500; }
  .var-changes .var-type { color: var(--muted); font-size: 12px; }
  .var-section-title { font-size: 12px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.5px; margin: 10px 0 6px; }
"""
