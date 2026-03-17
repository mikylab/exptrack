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
