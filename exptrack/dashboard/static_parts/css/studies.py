"""CSS for study management panel."""

CSS_STUDIES = """
  .study-panel { background: var(--card-bg); border: 1px solid var(--border); border-radius: 4px; padding: 16px; margin-bottom: 16px; }
  .study-panel h3 { font-size: 14px; margin-bottom: 12px; }
  .study-card { display: flex; justify-content: space-between; align-items: center; padding: 10px 14px; border: 1px solid var(--border); border-radius: 4px; margin-bottom: 4px; }
  .study-card:hover { background: var(--code-bg); }
  .study-card-name { font-weight: 600; font-size: 14px; color: var(--blue); cursor: pointer; }
  .study-card-meta { font-size: 13px; color: var(--muted); }
  .study-card-actions { display: flex; gap: 6px; }
  .study-card-actions button { font-family: inherit; font-size: 12px; padding: 4px 10px; border: 1px solid var(--border); background: var(--card-bg); cursor: pointer; border-radius: 3px; }
  .study-card-actions button.danger:hover { color: var(--red); border-color: var(--red); }
  .study-create-form { display: flex; gap: 8px; margin-top: 8px; }
  .study-create-form input { font-family: inherit; font-size: 14px; border: 1px solid var(--border); padding: 6px 10px; border-radius: 4px; background: var(--card-bg); flex: 1; }
  .study-create-form button { font-family: inherit; font-size: 13px; padding: 6px 14px; border: none; background: var(--blue); color: #fff; cursor: pointer; border-radius: 4px; }
"""
