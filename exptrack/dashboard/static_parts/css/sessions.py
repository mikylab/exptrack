"""
exptrack/dashboard/static_parts/css/sessions.py — Session Trees CSS
"""

CSS_SESSIONS = """
/* ── Session Trees ───────────────────────────────────────────────────────── */
#sessions-tab { display: none; }
body.sessions-active #sessions-tab {
    display: flex;
    flex: 1; min-height: 0; flex-direction: row;
}
body.sessions-active #welcome-state,
body.sessions-active #detail-view,
body.sessions-active #compare-view { display: none !important; }

#sessions-tab {
    flex: 1; min-height: 0; flex-direction: row;
}
#sessions-list {
    width: 280px; min-width: 220px; border-right: 1px solid var(--border);
    overflow-y: auto; padding: 12px;
}
#sessions-list h3 {
    font-size: 12px; text-transform: uppercase; letter-spacing: 0.05em;
    color: var(--muted); margin: 0;
}
.sessions-list-header {
    display: flex; align-items: center; justify-content: space-between;
    margin-bottom: 8px;
}
.sessions-list-actions { display: flex; gap: 4px; }
.sessions-refresh-btn, .sessions-close-btn {
    background: transparent; border: 1px solid var(--border);
    color: var(--muted); cursor: pointer; font-size: 13px;
    width: 22px; height: 22px; border-radius: 3px; padding: 0;
    line-height: 1;
}
.sessions-refresh-btn:hover, .sessions-close-btn:hover {
    color: var(--fg); background: var(--code-bg); border-color: var(--blue);
}
.sessions-updated-stamp {
    font-size: 10px; font-weight: normal; text-transform: none;
    letter-spacing: 0; color: var(--muted); margin-left: 6px;
    font-family: 'IBM Plex Mono', monospace;
}
#sessions-list-items.refreshing { opacity: 0.4; transition: opacity 0.15s; }
.session-card {
    padding: 8px 10px; margin-bottom: 6px;
    border: 1px solid var(--border); border-radius: 6px;
    cursor: pointer; background: var(--card-bg);
    transition: background 0.1s;
}
.session-card:hover { background: var(--code-bg); }
.session-card.active {
    border-color: var(--blue); background: var(--code-bg);
}
.session-card .name {
    font-weight: 600; font-size: 13px;
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
    flex: 1;
}
.session-card-header {
    display: flex; align-items: center; gap: 6px;
}
.session-delete-btn {
    background: transparent; border: none; color: var(--muted);
    cursor: pointer; font-size: 16px; line-height: 1;
    padding: 0 4px; border-radius: 3px;
}
.session-delete-btn:hover { color: var(--red, #c92a2a); background: var(--code-bg); }
.session-card .meta {
    font-size: 11px; color: var(--muted); margin-top: 2px;
}
.session-card .badge {
    display: inline-block; padding: 1px 6px; border-radius: 8px;
    font-size: 10px; font-weight: 600;
}
.session-card .badge.active {
    background: var(--blue); color: white;
}
.session-card .badge.ended { background: var(--muted); color: white; }

#session-tree-view {
    flex: 1; padding: 16px; overflow: auto; min-width: 0;
}
.session-tree-empty {
    color: var(--muted); padding: 24px; line-height: 1.5;
}
.session-tree-empty code {
    background: var(--code-bg); padding: 2px 5px; border-radius: 3px;
    font-family: 'IBM Plex Mono', monospace;
}

.tree-node {
    position: relative; padding: 6px 0 6px 28px;
    border-left: 2px solid var(--border); margin-left: 12px;
}
.tree-node.checkpoint > .node-marker {
    background: var(--blue); width: 12px; height: 12px;
}
.tree-node.branch > .node-marker {
    background: transparent; border: 2px solid var(--blue);
    width: 10px; height: 10px;
}
.tree-node.abandoned > .node-marker {
    background: transparent; border: 2px dashed var(--muted);
    width: 10px; height: 10px;
}
.tree-node.abandoned { opacity: 0.55; border-left-style: dashed; }
.tree-node.root { border-left: none; margin-left: 0; padding-left: 0; }
.tree-node.root > .node-row { font-weight: 600; }

.node-marker {
    position: absolute; left: -7px; top: 12px;
    border-radius: 50%;
}
.node-row {
    display: flex; flex-wrap: wrap; align-items: baseline; gap: 8px;
    cursor: pointer; padding: 2px 6px; border-radius: 4px;
}
.node-row:hover { background: var(--code-bg); }
.node-row.selected { background: var(--code-bg); }
.node-row .node-type {
    font-size: 11px; text-transform: uppercase;
    color: var(--muted); letter-spacing: 0.04em;
}
.node-row .node-label { font-size: 13px; }
.node-row .node-time { font-size: 11px; color: var(--muted); }
.node-row .node-diff {
    font-size: 11px; color: var(--muted);
    font-family: 'IBM Plex Mono', monospace;
}
.node-row .node-exp-badge {
    font-size: 11px; color: var(--blue);
    text-decoration: none; border: 1px solid var(--blue);
    padding: 0 6px; border-radius: 8px;
}
.node-row .node-note-mini {
    font-size: 11px; color: var(--muted); font-style: italic;
}

#session-detail {
    margin-top: 12px; padding: 12px;
    background: var(--card-bg); border: 1px solid var(--border);
    border-radius: 6px; display: none;
}
#session-detail.visible { display: block; }
#session-detail .section-title {
    font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em;
    color: var(--muted); margin: 8px 0 4px 0;
}
/* Theme-aware diff backgrounds — subtle tints rather than wall-of-color. */
:root {
    --diff-add-bg: rgba(45, 125, 70, 0.10);
    --diff-add-bar: rgba(45, 125, 70, 0.55);
    --diff-del-bg: rgba(192, 57, 43, 0.10);
    --diff-del-bar: rgba(192, 57, 43, 0.55);
    --diff-empty-bg: rgba(0, 0, 0, 0.025);
    --diff-hunk-bg: rgba(44, 90, 160, 0.06);
}
body.dark {
    --diff-add-bg: rgba(76, 175, 80, 0.14);
    --diff-add-bar: rgba(76, 175, 80, 0.55);
    --diff-del-bg: rgba(239, 83, 80, 0.14);
    --diff-del-bar: rgba(239, 83, 80, 0.55);
    --diff-empty-bg: rgba(255, 255, 255, 0.03);
    --diff-hunk-bg: rgba(92, 156, 230, 0.08);
}

#session-detail pre.diff.plain {
    max-height: 420px; overflow: auto;
    background: var(--code-bg); padding: 8px;
    font-family: 'IBM Plex Mono', monospace; font-size: 12px;
    line-height: 1.45; border-radius: 4px;
    border: 1px solid var(--border);
    color: var(--fg);
}

/* Section header: title + stats + mode toggle on one line. */
#session-detail .diff-section-head {
    display: flex; align-items: center; gap: 10px; flex-wrap: wrap;
    margin: 12px 0 6px 0;
}
#session-detail .diff-section-head .section-title { margin: 0; }
#session-detail .diff-summary {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 11px; color: var(--muted);
    text-transform: none; letter-spacing: 0;
}
#session-detail .d-stat-add { color: var(--green); font-weight: 600; }
#session-detail .d-stat-del { color: var(--red); font-weight: 600; }

#session-detail .diff-mode-toggle {
    margin-left: auto; display: inline-flex; gap: 0;
    border: 1px solid var(--border); border-radius: 4px; overflow: hidden;
}
#session-detail .diff-mode-btn {
    font-family: inherit; font-size: 12px; padding: 3px 10px;
    background: var(--card-bg); color: var(--muted);
    border: none; cursor: pointer;
    border-right: 1px solid var(--border);
}
#session-detail .diff-mode-btn:last-child { border-right: none; }
#session-detail .diff-mode-btn:hover { color: var(--fg); background: var(--code-bg); }
#session-detail .diff-mode-btn.active {
    background: var(--blue); color: #fff;
}

/* File block: collapsible, GitHub-style. */
#session-detail .diff-file {
    margin: 8px 0; border: 1px solid var(--border); border-radius: 6px;
    background: var(--card-bg); overflow: hidden;
}
#session-detail .diff-file-head {
    cursor: pointer; padding: 8px 12px; user-select: none;
    background: var(--code-bg);
    display: flex; align-items: center; gap: 12px;
    list-style: none;
    font-size: 12px; font-family: 'IBM Plex Mono', monospace;
    border-bottom: 1px solid var(--border);
}
#session-detail .diff-file:not([open]) .diff-file-head { border-bottom: none; }
#session-detail .diff-file-head::-webkit-details-marker { display: none; }
#session-detail .diff-file-head::before {
    content: '▸'; color: var(--muted); font-size: 10px;
    transition: transform 0.1s;
}
#session-detail .diff-file[open] .diff-file-head::before { transform: rotate(90deg); }
#session-detail .diff-file-name { flex: 1; color: var(--fg); font-weight: 600; }
#session-detail .diff-file-stats { font-size: 11px; }

#session-detail .diff-file-body {
    max-height: 480px; overflow: auto;
    background: var(--card-bg);
}
#session-detail .diff-hunk-head {
    background: var(--diff-hunk-bg); color: var(--blue);
    font-family: 'IBM Plex Mono', monospace; font-size: 11px;
    padding: 4px 12px; border-top: 1px solid var(--border);
    border-bottom: 1px solid var(--border);
    white-space: pre; overflow-x: auto;
}
#session-detail .diff-hunk-head:first-child { border-top: none; }

/* Unified view */
#session-detail .diff-unified {
    font-family: 'IBM Plex Mono', monospace; font-size: 12px;
    line-height: 1.5;
}
#session-detail .du-row {
    display: flex; align-items: flex-start;
    padding: 0; min-height: 1.5em;
}
#session-detail .du-sign {
    flex: 0 0 24px; text-align: center; color: var(--muted);
    user-select: none; padding: 0 4px;
    border-right: 1px solid var(--border);
}
#session-detail .du-text {
    flex: 1; padding: 0 8px; white-space: pre-wrap;
    word-break: break-word; color: var(--fg);
}
#session-detail .du-add .du-sign { color: var(--green); font-weight: 600; }
#session-detail .du-del .du-sign { color: var(--red); font-weight: 600; }

/* Split view */
#session-detail table.diff-split {
    width: 100%; border-collapse: collapse; table-layout: fixed;
    font-family: 'IBM Plex Mono', monospace; font-size: 12px;
    line-height: 1.5;
}
#session-detail table.diff-split td {
    width: 50%; vertical-align: top;
    padding: 0 8px; white-space: pre-wrap; word-break: break-word;
    border-right: 1px solid var(--border);
    color: var(--fg);
}
#session-detail table.diff-split td:last-child { border-right: none; }
#session-detail table.diff-split tr:hover td { background: var(--hover-bg, var(--code-bg)); }
#session-detail .du-add, #session-detail .ds-add {
    background: var(--diff-add-bg);
    box-shadow: inset 3px 0 0 var(--diff-add-bar);
}
#session-detail .du-del, #session-detail .ds-del {
    background: var(--diff-del-bg);
    box-shadow: inset 3px 0 0 var(--diff-del-bar);
}
#session-detail .ds-empty { background: var(--diff-empty-bg); }
#session-detail .ds-text { display: block; }
#session-detail .diff-empty {
    padding: 12px; color: var(--muted); font-size: 12px;
}

#session-detail .cell-block {
    margin: 6px 0 10px 0;
    border: 1px solid var(--border); border-radius: 4px;
    background: var(--code-bg);
    overflow: hidden;
}
#session-detail .cell-block summary {
    cursor: pointer; padding: 6px 10px;
    background: var(--code-bg);
    font-size: 11px; user-select: none;
    display: flex; align-items: center; gap: 10px;
    list-style: none;
}
#session-detail .cell-block summary::-webkit-details-marker { display: none; }
#session-detail .cell-block summary::before {
    content: '▸'; color: var(--muted); font-size: 10px;
    transition: transform 0.1s;
}
#session-detail .cell-block[open] summary::before { transform: rotate(90deg); }
#session-detail .cell-block .cell-idx {
    font-weight: 600; color: var(--fg);
    text-transform: uppercase; letter-spacing: 0.04em;
}
#session-detail .cell-block .cell-meta {
    color: var(--muted); font-family: 'IBM Plex Mono', monospace;
}
#session-detail .cell-block pre.cell-code {
    margin: 0; padding: 8px 0;
    max-height: 360px; overflow: auto;
    background: var(--code-bg);
    font-family: 'IBM Plex Mono', monospace; font-size: 12px;
    line-height: 1.5;
}
#session-detail .cell-block pre.cell-code .ln {
    display: inline-block; width: 36px; padding-right: 10px;
    text-align: right; color: var(--muted); opacity: 0.6;
    user-select: none; margin-right: 8px;
    border-right: 1px solid var(--border);
}
#session-detail .note-edit {
    width: 100%; min-height: 48px; padding: 6px 8px;
    border: 1px solid var(--border); border-radius: 4px;
    background: var(--card-bg); color: var(--fg);
    font-family: inherit; font-size: 12px;
    margin-bottom: 6px;
    resize: vertical;
}
#session-detail button {
    font-family: inherit; font-size: 12px;
    padding: 4px 12px; border: 1px solid var(--border);
    background: var(--code-bg); color: var(--muted);
    border-radius: 4px; cursor: pointer;
}
#session-detail button:hover {
    color: var(--fg); border-color: var(--fg); background: var(--card-bg);
}
"""
