"""CSS for the toolbox drawers: todos and commands notepad."""

CSS_TOOLBOX = """
  /* ── Toolbox drawer (shared by Todos & Commands) ─────────────────────── */
  .toolbox-btn {
    font-family: inherit; font-size: 13px; background: var(--code-bg);
    border: 1px solid var(--border); padding: 6px 12px; cursor: pointer;
    border-radius: 4px; color: var(--muted);
  }
  .toolbox-btn:hover { background: var(--border); color: var(--fg); }
  .toolbox-btn.active { background: var(--blue); color: #fff; border-color: var(--blue); }

  .toolbox-overlay {
    position: fixed; top: 0; left: 0; right: 0; bottom: 0;
    background: rgba(0,0,0,0.3); z-index: 999;
    opacity: 0; pointer-events: none; transition: opacity 0.2s;
  }
  .toolbox-overlay.visible { opacity: 1; pointer-events: auto; }

  .toolbox-drawer {
    position: fixed; top: 0; right: -480px; bottom: 0; width: 460px;
    background: var(--card-bg); border-left: 1px solid var(--border);
    box-shadow: -4px 0 20px rgba(0,0,0,0.12); z-index: 1000;
    display: flex; flex-direction: column;
    transition: right 0.25s ease;
  }
  .toolbox-drawer.visible { right: 0; }

  .toolbox-header {
    display: flex; justify-content: space-between; align-items: center;
    padding: 14px 20px; border-bottom: 1px solid var(--border); flex-shrink: 0;
  }
  .toolbox-header h3 { font-size: 15px; font-weight: 600; margin: 0; }

  .toolbox-tabs {
    display: flex; gap: 0; border-bottom: 1px solid var(--border); flex-shrink: 0;
  }
  .toolbox-tab {
    flex: 1; font-family: inherit; font-size: 13px; font-weight: 500;
    background: none; border: none; padding: 10px 16px; cursor: pointer;
    color: var(--muted); border-bottom: 2px solid transparent;
    margin-bottom: -1px; text-transform: uppercase; letter-spacing: 0.5px;
  }
  .toolbox-tab:hover { background: var(--code-bg); color: var(--fg); }
  .toolbox-tab.active { color: var(--fg); border-bottom-color: var(--blue); font-weight: 600; }

  .toolbox-close {
    background: none; border: none; font-size: 20px; cursor: pointer;
    color: var(--muted); padding: 4px 8px; border-radius: 3px; font-family: inherit;
  }
  .toolbox-close:hover { background: var(--code-bg); color: var(--fg); }

  .toolbox-body { flex: 1; overflow-y: auto; }
  .toolbox-panel { display: none; padding: 16px 20px; }
  .toolbox-panel.active { display: block; }

  /* ── Shared add-form inputs ──────────────────────────────────────────── */
  .todo-add-form, .cmd-add-form {
    display: flex; flex-direction: column; gap: 8px; margin-bottom: 16px;
    padding-bottom: 14px; border-bottom: 1px solid var(--border);
  }
  .todo-add-row, .cmd-add-row { display: flex; gap: 6px; align-items: center; }
  .cmd-add-row { justify-content: flex-end; }

  .todo-add-form input[type="text"], .todo-add-form input[type="date"], .cmd-add-form input[type="text"] {
    flex: 1; font-family: inherit; font-size: 13px;
    border: 1px solid var(--border); padding: 7px 10px; border-radius: 4px;
    background: var(--card-bg); color: var(--fg);
  }
  .todo-add-form input[type="text"]:focus, .todo-add-form input[type="date"]:focus, .cmd-add-form input[type="text"]:focus {
    outline: none; border-color: var(--blue);
  }
  .todo-add-form input[type="text"]::placeholder, .cmd-add-form input[type="text"]::placeholder { color: var(--muted); }

  .todo-add-btn, .cmd-add-btn {
    font-family: inherit; font-size: 13px; padding: 7px 14px;
    border: 1px solid var(--blue); background: var(--blue); color: #fff;
    cursor: pointer; border-radius: 4px; white-space: nowrap;
  }
  .todo-add-btn:hover, .cmd-add-btn:hover { opacity: 0.9; }

  .toolbox-meta-row {
    display: flex; gap: 6px; align-items: center; flex-wrap: wrap; min-height: 28px;
  }
  .toolbox-chip-area {
    display: flex; gap: 4px; flex-wrap: wrap; align-items: center;
  }
  .toolbox-chip {
    display: inline-flex; align-items: center; gap: 3px; cursor: default;
  }
  .toolbox-chip-x {
    cursor: pointer; font-size: 13px; line-height: 1; opacity: 0.6;
    margin-left: 2px;
  }
  .toolbox-chip-x:hover { opacity: 1; color: var(--red, #e55); }
  .toolbox-study-display { display: inline-flex; align-items: center; }

  .cmd-add-form textarea {
    font-family: 'SFMono-Regular', 'Consolas', 'Liberation Mono', 'Menlo', monospace;
    font-size: 12px; border: 1px solid var(--border); padding: 8px 10px;
    border-radius: 4px; background: var(--code-bg); color: var(--fg);
    resize: vertical; min-height: 40px; line-height: 1.5;
  }
  .cmd-add-form textarea:focus { outline: none; border-color: var(--blue); }
  .cmd-add-form textarea::placeholder { color: var(--muted); }

  /* ── Filters (shared) ────────────────────────────────────────────────── */
  .todo-filters, .cmd-filters {
    display: flex; gap: 4px; margin-bottom: 12px; flex-wrap: wrap; align-items: center;
  }
  .todo-filter-btn {
    font-family: inherit; font-size: 12px; background: var(--code-bg);
    border: 1px solid var(--border); padding: 4px 10px; cursor: pointer;
    border-radius: 3px; color: var(--muted);
  }
  .todo-filter-btn:hover { background: var(--border); color: var(--fg); }
  .todo-filter-btn.active { background: var(--fg); color: var(--bg); }

  .todo-count { font-size: 11px; color: var(--muted); margin-left: auto; }

  /* ── Todos ───────────────────────────────────────────────────────────── */
  .todo-list { display: flex; flex-direction: column; gap: 2px; }

  .todo-item {
    display: flex; align-items: flex-start; gap: 8px;
    padding: 8px 10px; border-radius: 4px; transition: background 0.1s;
  }
  .todo-item:hover { background: var(--code-bg); }
  .todo-item.done .todo-text { text-decoration: line-through; color: var(--muted); }

  .todo-check {
    margin-top: 2px; cursor: pointer; accent-color: var(--blue);
    width: 15px; height: 15px; flex-shrink: 0;
  }

  .todo-content { flex: 1; min-width: 0; }
  .todo-text { font-size: 13px; line-height: 1.4; word-break: break-word; }
  .todo-meta, .cmd-meta {
    display: flex; gap: 4px; margin-top: 4px; flex-wrap: wrap; align-items: center;
  }
  .cmd-meta { margin-top: 0; }
  .toolbox-tag {
    font-size: 11px; padding: 1px 7px; border-radius: 3px;
    background: var(--code-bg); color: var(--fg);
  }
  .toolbox-study {
    font-size: 11px; padding: 1px 7px; border-radius: 3px;
    background: rgba(44,90,160,0.1); color: var(--blue);
  }

  .todo-due {
    font-size: 11px; margin-left: 6px; padding: 1px 6px;
    border-radius: 3px; background: var(--code-bg); white-space: nowrap;
  }

  .todo-delete {
    cursor: pointer; color: var(--muted); font-size: 14px;
    padding: 2px 4px; border-radius: 3px; opacity: 0;
    transition: opacity 0.1s; flex-shrink: 0; background: none; border: none;
    font-family: inherit; line-height: 1;
  }
  .todo-item:hover .todo-delete { opacity: 0.6; }
  .todo-delete:hover { opacity: 1 !important; color: var(--red, #e55); }

  .todo-empty, .cmd-empty {
    text-align: center; color: var(--muted); font-size: 13px;
    padding: 24px 16px; line-height: 1.5;
  }

  /* ── Commands Notepad ────────────────────────────────────────────────── */
  .cmd-list { display: flex; flex-direction: column; gap: 8px; }

  .cmd-item {
    border: 1px solid var(--border); border-radius: 6px;
    overflow: hidden; transition: border-color 0.15s;
  }
  .cmd-item:hover { border-color: color-mix(in srgb, var(--border) 50%, var(--blue) 50%); }

  .cmd-item-header {
    display: flex; align-items: center; gap: 8px;
    padding: 8px 12px; background: var(--code-bg); flex-wrap: wrap;
  }
  .cmd-label {
    font-size: 13px; font-weight: 600;
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  }
  .cmd-actions {
    display: flex; gap: 2px; opacity: 0; transition: opacity 0.1s; margin-left: auto;
  }
  .cmd-item:hover .cmd-actions { opacity: 1; }
  .cmd-action-btn {
    background: none; border: none; font-size: 12px; cursor: pointer;
    color: var(--muted); padding: 2px 6px; border-radius: 3px; font-family: inherit;
  }
  .cmd-action-btn:hover { color: var(--fg); background: var(--card-bg); }
  .cmd-action-btn.cmd-del:hover { color: var(--red, #e55); }

  .cmd-code-wrap { position: relative; padding: 0; }
  .cmd-code {
    display: block; padding: 10px 12px 24px; padding-right: 70px;
    font-family: 'SFMono-Regular', 'Consolas', 'Liberation Mono', 'Menlo', monospace;
    font-size: 12px; line-height: 1.5; color: var(--fg);
    white-space: pre-wrap; word-break: break-all;
    margin: 0; background: transparent; outline: none;
    border-top: 1px solid transparent; transition: border-color 0.15s;
  }
  .cmd-code:focus { border-top-color: var(--blue); background: rgba(44,90,160,0.03); }
  .cmd-copy-btn {
    position: absolute; top: 6px; right: 6px;
    font-family: inherit; font-size: 11px; padding: 4px 10px;
    border: 1px solid var(--border); background: var(--card-bg);
    cursor: pointer; border-radius: 3px; color: var(--muted);
    transition: all 0.15s;
  }
  .cmd-copy-btn:hover { border-color: var(--blue); color: var(--blue); }
  .cmd-copy-btn.copied { border-color: var(--green, #059669); color: var(--green, #059669); }

  .cmd-modified {
    position: absolute; bottom: 5px; left: 12px;
    font-size: 12px; color: var(--blue); cursor: pointer;
    font-family: inherit;
  }
  .cmd-modified:hover { text-decoration: underline; }

  /* Edit mode for commands */
  .cmd-edit-form {
    padding: 10px 12px; display: flex; flex-direction: column; gap: 6px;
  }
  .cmd-edit-form input {
    font-family: inherit; font-size: 13px; border: 1px solid var(--blue);
    padding: 6px 8px; border-radius: 4px; background: var(--card-bg); color: var(--fg);
  }
  .cmd-edit-form textarea {
    font-family: 'SFMono-Regular', 'Consolas', 'Liberation Mono', 'Menlo', monospace;
    font-size: 12px; border: 1px solid var(--blue); padding: 6px 8px;
    border-radius: 4px; background: var(--code-bg); color: var(--fg);
    resize: vertical; min-height: 40px;
  }
  .cmd-edit-actions { display: flex; gap: 6px; justify-content: flex-end; }
  .cmd-edit-actions button {
    font-family: inherit; font-size: 12px; padding: 5px 12px;
    border: 1px solid var(--border); background: var(--code-bg);
    cursor: pointer; border-radius: 4px; color: var(--muted);
  }
  .cmd-edit-actions button:hover { background: var(--border); color: var(--fg); }
  .cmd-edit-actions button.primary { background: var(--blue); color: #fff; border-color: var(--blue); }
"""
