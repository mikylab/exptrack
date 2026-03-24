"""CSS for compare view, side-by-side diffs, and reproduce box."""

CSS_COMPARE = """
  .compare-main-btn { font-family: inherit; font-size: 13px; padding: 7px 16px; border: 1px solid var(--border); background: var(--card-bg); cursor: pointer; color: var(--fg); white-space: nowrap; transition: background 0.15s, border-color 0.15s; border-radius: 4px; }
  .compare-main-btn:hover { background: var(--code-bg); border-color: var(--blue); color: var(--blue); }
  .compare-header { margin-bottom: 12px; }
  .compare-header h3 { font-size: 18px; }
  .back-link { font-family: inherit; font-size: 14px; background: none; border: none; color: var(--blue); cursor: pointer; padding: 2px 0; }
  .back-link:hover { text-decoration: underline; }
  .compare-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 24px; }
  .compare-input { display: flex; gap: 10px; margin-bottom: 20px; align-items: flex-end; flex-wrap: wrap; }
  .compare-selector { display: flex; flex-direction: column; gap: 4px; }
  .compare-label { font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; color: var(--muted); }
  .compare-input select, .compare-input input {
    font-family: inherit; font-size: 14px;
    border: 1px solid var(--border); padding: 8px 14px; min-width: 260px;
    background: var(--card-bg); border-radius: 4px;
  }
  .compare-input button {
    font-family: inherit; font-size: 14px;
    background: var(--fg); color: var(--bg); border: none;
    padding: 8px 18px; cursor: pointer; border-radius: 4px;
  }
  .compare-input button.primary { background: var(--blue); color: #fff; }
  .compare-input .vs-label { font-weight: 600; color: var(--muted); font-size: 16px; padding-bottom: 6px; }
  .differs { color: var(--yellow); font-weight: 600; }
  .diff-added { color: var(--green, #3fb950); background: rgba(63,185,80,0.1); }
  .diff-removed { color: var(--red, #f85149); background: rgba(248,81,73,0.1); }
  .only-differs-toggle { font-family: inherit; font-size: 13px; margin-left: 12px; cursor: pointer; }
  .compare-charts-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(400px, 1fr)); gap: 16px; margin: 12px 0; }
  .source-badge { display: inline-block; font-size: 10px; font-weight: 600; padding: 1px 6px; border-radius: 8px; text-transform: uppercase; letter-spacing: 0.3px; vertical-align: middle; }
  .source-badge.auto { background: rgba(44,90,160,0.15); color: var(--blue); }
  .source-badge.manual { background: rgba(212,130,15,0.15); color: var(--tl-metric); }
  .source-badge.pipeline { background: rgba(63,185,80,0.15); color: var(--green); }
  .source-badge.mixed { background: rgba(142,68,173,0.15); color: #8e44ad; }
  .reproduce-box { background: var(--code-bg); border: 1px solid var(--border); border-radius: 6px; padding: 8px 12px; margin: 8px 0 12px; }
  .reproduce-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px; }
  .reproduce-cmd { font-size: 13px; word-break: break-all; white-space: pre-wrap; display: block; }
  .copy-btn { font-family: inherit; font-size: 11px; padding: 2px 8px; cursor: pointer; background: var(--card-bg); border: 1px solid var(--border); border-radius: 4px; color: var(--fg); }
  .copy-btn:hover { background: var(--blue); color: #fff; }
  .multi-compare-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(350px, 1fr)); gap: 16px; margin: 12px 0; }
  .multi-compare-image-group { margin-bottom: 16px; }
  .multi-compare-image-row { display: flex; gap: 12px; overflow-x: auto; padding: 4px 0 8px; }
  .multi-compare-image-cell { flex: 0 0 auto; min-width: 160px; max-width: 280px; }
  .multi-compare-image-cell img { width: 100%; border-radius: 4px; border: 1px solid var(--border); cursor: pointer; transition: transform 0.15s; }
  .multi-compare-image-cell img:hover { transform: scale(1.03); border-color: var(--blue); }
"""
