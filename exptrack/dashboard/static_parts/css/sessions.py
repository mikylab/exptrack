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
    flex: 1; min-width: 0;
}
.session-card-header {
    display: flex; align-items: center; gap: 6px;
}
.session-card-sub {
    display: flex; align-items: baseline; gap: 6px; margin-top: 4px;
    font-size: 11px; color: var(--muted);
    overflow: hidden; white-space: nowrap;
}
.session-card-sub .sc-notebook {
    overflow: hidden; text-overflow: ellipsis;
    font-family: 'IBM Plex Mono', monospace;
    color: var(--fg); opacity: 0.75;
    flex: 0 1 auto; min-width: 0;
}
.session-card-sub .sc-meta-tail {
    flex: 0 0 auto; color: var(--muted);
}
.session-delete-btn {
    background: transparent; border: none; color: var(--muted);
    cursor: pointer; font-size: 16px; line-height: 1;
    padding: 0 4px; border-radius: 3px;
}
.session-delete-btn:hover { color: var(--red, #c92a2a); background: var(--code-bg); }
/* Shared pill base used across the Sessions tab. */
.session-card .pill,
#session-tree-view .pill {
    display: inline-block; padding: 1px 7px; border-radius: 9px;
    font-size: 10px; font-weight: 600; line-height: 1.6;
    letter-spacing: 0.02em; text-transform: lowercase;
    white-space: nowrap;
}
.pill-active { background: var(--blue); color: #fff; }
.pill-ended { background: var(--muted); color: #fff; opacity: 0.85; }
.pill-abandoned {
    background: rgba(217, 119, 6, 0.15);
    color: #b45309; border: 1px solid rgba(217, 119, 6, 0.45);
}
body.dark .pill-abandoned {
    background: rgba(245, 158, 11, 0.18);
    color: #fbbf24; border-color: rgba(245, 158, 11, 0.55);
}
.pill-setup {
    background: var(--surface-2, #eee); color: var(--text-3, #777);
    border: 1px solid var(--border, #ddd);
}
body.dark .pill-setup {
    background: rgba(255, 255, 255, 0.06); color: var(--text-3, #999);
    border-color: var(--border-strong, #444);
}

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

/* ── Branch graph (git-graph lane rail) ──────────────────────────────────── */
/* Each row is [rail | content]. The rail draws colored lane lines + fork curves
   (an SVG that stretches vertically to the row) with the node marker as an
   overlaid round dot. The content cell is the same .node-row as before, so
   selection / compare / actions styling is unchanged. */
/* Graph legend — explains the marks so colors/dots aren't a mystery. */
.tree-legend {
    display: flex; flex-wrap: wrap; align-items: center; gap: 6px 14px;
    margin: 0 0 10px 2px; padding: 6px 10px;
    border: 1px solid var(--border); border-radius: 6px;
    background: var(--surface-2, var(--card-bg));
    font-size: 11px; color: var(--muted);
}
.tree-legend .tl-k { display: inline-flex; align-items: center; gap: 5px; white-space: nowrap; }
.tree-legend .tl-dot { width: 11px; height: 11px; border-radius: 50%; box-sizing: border-box; flex: 0 0 auto; }
.tree-legend .tl-dot.cp { background: var(--branch-c0); }
.tree-legend .tl-dot.br { background: transparent; border: 2px solid var(--branch-c1); }
.tree-legend .tl-dot.ab { background: transparent; border: 2px dashed var(--branch-ab); }
.tree-legend .tl-note { color: var(--text-3); font-style: italic; }

#session-tree-graph { display: flex; flex-direction: column; }
.tree-row {
    display: grid; grid-template-columns: auto 1fr; align-items: stretch;
}
.tree-rail { position: relative; flex: 0 0 auto; align-self: stretch; }
/* Straight lane lines are pixel-anchored divs (junction at a fixed px from the
   top, so it lands on the node's title line); only the fork sprout is an SVG. */
.tree-rail .rail-v {
    position: absolute; width: 2px; margin-left: -1px;
    background: var(--rc, var(--border));
}
.tree-rail .rail-fork {
    position: absolute; left: 0; width: 100%; overflow: visible;
}
.tree-rail .rail-fork .rail-line { stroke: var(--rc, var(--border)); stroke-width: 2; fill: none; }
/* Bounded, state-based lane color: the spine is neutral, every branch shares
   one calm teal, abandoned dead-ends are amber. Lane POSITION (not color)
   tells branches apart, so the palette never grows with the number of branches. */
.tc-spine  { --rc: var(--branch-c0); }
.tc-branch { --rc: var(--branch-c1); }
.tc-ab     { --rc: var(--branch-ab); }
/* Dot = node TYPE (shape + fill), independent of the lane color, so a checkpoint
   is ALWAYS a neutral filled dot — even when it sits on a colored branch line —
   and a branch is always an open ring. (shape = what · color of line = which.)
   Anchored to the title line via an inline top:<px>; centered with translate. */
.rail-dot {
    position: absolute; transform: translate(-50%, -50%);
    width: 12px; height: 12px; border-radius: 50%;
    background: var(--branch-c0); box-sizing: border-box;
}
.rail-dot.checkpoint, .rail-dot.root { background: var(--branch-c0); }
.rail-dot.branch { background: var(--bg); border: 2px solid var(--branch-c1); }
.rail-dot.abandoned { background: var(--bg); border: 2px dashed var(--branch-ab); }
.rail-dot.root { width: 13px; height: 13px; }
/* A divergence point (a checkpoint that forks) gets a neutral ring halo so the
   split is easy to spot — kept grey, not violet, so it never reads as a compare
   pick (purple stays reserved for picks). The ⑂ badge labels it too. */
.rail-dot.diverge { box-shadow: 0 0 0 3px var(--border-strong); }

.node-row {
    display: flex; flex-direction: column; gap: 2px;
    cursor: pointer; padding: 5px 8px; border-radius: 4px;
    border-left: 3px solid transparent; margin-left: 2px;
    transition: background 0.1s, border-color 0.1s;
}
.node-row:hover { background: var(--code-bg); }
.node-row.selected {
    background: var(--code-bg);
    border-left-color: var(--blue);
}
.tree-row.root .node-row { font-weight: 600; }
.tree-row.abandoned .node-row { background: var(--diff-empty-bg); }
.tree-row.abandoned .node-row .node-label {
    color: var(--muted); text-decoration: line-through;
    text-decoration-color: rgba(217, 119, 6, 0.4);
}
.tree-row.abandoned .node-row.selected { border-left-color: var(--branch-ab); }

/* Divergence badge, "← latest" frontier tag, collapse caret, hidden-count. */
.tree-diverge-badge {
    font-size: 10.5px; font-weight: 600; color: var(--compare-accent);
    border: 1px solid var(--compare-accent); border-radius: 8px;
    padding: 0 6px; white-space: nowrap;
}
.node-latest-tag {
    font-size: 10.5px; font-weight: 600; color: var(--accent);
    background: var(--accent-soft, var(--code-bg)); border-radius: 8px;
    padding: 0 6px; white-space: nowrap;
}
.node-collapse-btn {
    background: transparent; border: none; color: var(--muted);
    cursor: pointer; font-size: 11px; line-height: 1; padding: 0 2px;
    flex: 0 0 auto;
}
.node-collapse-btn:hover { color: var(--fg); }
.node-hidden-hint { font-size: 11px; color: var(--muted); font-style: italic; }

/* Inline code trace on tree nodes: the defining-change line, the ⟨⟩ toggle, and
   the expandable full-source block. */
.node-defining {
    font-family: 'IBM Plex Mono', monospace; font-size: 11.5px;
    color: var(--text-2, var(--fg)); margin-top: 2px;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.node-defining::first-letter { color: var(--accent); }
.node-row .node-code-toggle {
    background: transparent; border: 1px solid transparent; color: var(--muted);
    cursor: pointer; font-size: 12px; line-height: 1.2; font-family: 'IBM Plex Mono', monospace;
    padding: 0 5px; border-radius: 6px; flex: 0 0 auto;
    opacity: 0; transition: opacity 0.1s, color 0.1s, border-color 0.1s, background 0.1s;
}
.node-row:hover .node-code-toggle,
.node-row.selected .node-code-toggle { opacity: 0.8; }
.node-row .node-code-toggle:hover,
.node-row .node-code-toggle.open {
    opacity: 1; color: var(--accent); border-color: var(--accent); background: var(--code-bg);
}
.node-code {
    margin-top: 4px; border: 1px solid var(--border); border-radius: 4px;
    background: var(--code-bg); overflow: auto; max-height: 320px; resize: vertical;
}
.node-code-pre {
    margin: 0; padding: 8px 10px; font-family: 'IBM Plex Mono', monospace;
    font-size: 12px; line-height: 1.5; white-space: pre; color: var(--fg);
}
.node-row-main {
    display: flex; flex-wrap: wrap; align-items: center; gap: 8px;
}
.node-row .node-label { font-size: 13px; color: var(--fg); }
.node-row .node-meta {
    display: flex; flex-wrap: wrap; align-items: baseline;
    gap: 6px; font-size: 11px; color: var(--muted);
}
.node-row .node-meta .nm-diff,
.node-row .node-meta .nm-time {
    font-family: 'IBM Plex Mono', monospace;
}
.node-row .node-meta .nm-sep { opacity: 0.6; }
.node-row .node-exp-badge {
    font-size: 11px; color: var(--blue);
    text-decoration: none; border: 1px solid var(--blue);
    padding: 0 6px; border-radius: 8px;
}
/* Action buttons (compare pin / promote / delete) cluster at the right edge. */
.node-row .node-actions {
    margin-left: auto;
    display: flex; align-items: center; gap: 4px; flex-shrink: 0;
}
.node-row .node-delete-btn {
    background: transparent; border: none; color: var(--muted);
    cursor: pointer; font-size: 15px; line-height: 1;
    padding: 0 6px; border-radius: 3px;
    opacity: 0; transition: opacity 0.1s, color 0.1s, background 0.1s;
}
.node-row:hover .node-delete-btn,
.node-row.selected .node-delete-btn { opacity: 0.7; }
.node-row .node-delete-btn:hover {
    opacity: 1; color: var(--red, #c92a2a);
    background: var(--code-bg);
}
/* Pill-style hover buttons — promote (blue accent) and the compare pin (violet
   compare-accent) share a base; only the hover/picked accent differs. */
.node-row .node-promote-btn,
.node-row .node-compare-btn {
    background: transparent; border: 1px solid transparent; color: var(--muted);
    cursor: pointer; font-size: 11px; line-height: 1.3;
    padding: 1px 7px; border-radius: 10px; white-space: nowrap;
    opacity: 0; transition: opacity 0.1s, color 0.1s, background 0.1s, border-color 0.1s;
}
.node-row:hover .node-promote-btn,
.node-row.selected .node-promote-btn,
.node-row:hover .node-compare-btn,
.node-row.selected .node-compare-btn { opacity: 0.8; }
.node-row .node-promote-btn:hover {
    opacity: 1; color: var(--accent, #2563eb);
    border-color: var(--accent, #2563eb); background: var(--code-bg);
}
.node-row .node-compare-btn:hover {
    opacity: 1; color: var(--compare-accent, #7c3aed);
    border-color: var(--compare-accent, #7c3aed); background: var(--code-bg);
}
.node-row .node-compare-btn.picked {
    opacity: 1; color: #fff;
    background: var(--compare-accent, #7c3aed);
    border-color: var(--compare-accent, #7c3aed);
}
/* %%setup prep cells: recorded but dimmed so they read as secondary. */
.setup-section { margin-top: 10px; }
details.cell-block.setup-cell { opacity: 0.78; }
details.cell-block.setup-cell > summary { border-left: 2px solid var(--border-strong, #bbb); }
.nm-setup { white-space: nowrap; }
.node-row .node-note-mini {
    font-size: 11.5px; color: var(--muted); font-style: italic;
    margin-top: 2px; line-height: 1.4;
}
.node-row .node-awaiting {
    font-size: 11px; color: var(--muted); opacity: 0.7;
    font-style: italic; margin-top: 2px;
    font-family: 'IBM Plex Mono', monospace;
}

/* Per-session outcome summary in the tree header — what this session produced. */
.session-outcomes {
    display: flex; flex-wrap: wrap; align-items: center; gap: 6px;
    margin: 8px 0 2px 0;
}
.session-outcomes .section-title {
    font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em;
    color: var(--muted); margin: 0;
}
.session-outcomes .outcome-chips { display: inline-flex; flex-wrap: wrap; gap: 4px; }
.session-outcomes .outcome-chip {
    font-size: 11px; text-decoration: none; color: var(--blue);
    border: 1px solid var(--border); border-radius: 10px; padding: 1px 8px;
    background: var(--card-bg); white-space: nowrap;
}
.session-outcomes .outcome-chip:hover { border-color: var(--blue); background: var(--code-bg); }
.session-outcomes .outcome-none { font-size: 11px; color: var(--muted); font-style: italic; }
.session-outcomes .outcome-counts { font-size: 11px; color: var(--muted); }

/* Clickable lineage breadcrumb in the node detail header. */
.node-lineage {
    display: flex; flex-wrap: wrap; align-items: center; gap: 4px;
    font-size: 11.5px; margin-bottom: 6px;
}
.node-lineage a { color: var(--blue); text-decoration: none; }
.node-lineage a:hover { text-decoration: underline; }
.node-lineage .bc-sep { color: var(--muted); opacity: 0.7; }
.node-lineage .bc-current { color: var(--muted); font-weight: 600; }

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
/* Diff/compare color tokens now live centrally in css/reset.py. */

#session-detail pre.diff.plain {
    max-height: 420px; overflow: auto;
    background: var(--code-bg); padding: 8px;
    font-family: 'IBM Plex Mono', monospace; font-size: 12px;
    line-height: 1.45; border-radius: 4px;
    border: 1px solid var(--border);
    color: var(--fg);
}

/* Section header: title + stats + mode toggle on one line, sticky so the
   Split / Unified toggle stays reachable while scrolling a long diff. */
#session-detail .diff-section {
    margin-top: 12px;
}
#session-detail .diff-section-head {
    display: flex; align-items: center; gap: 10px; flex-wrap: wrap;
    margin: 0 0 6px 0; padding: 6px 8px;
    position: sticky; top: 0; z-index: 2;
    background: var(--card-bg);
    border-bottom: 1px solid var(--border);
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
    /* No height cap — long cells expand fully so nothing is cut off when
       copying or reading; drag the bottom edge to shrink if a cell is huge. */
    overflow: auto; resize: vertical;
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
/* Soft-wrap long lines so wide code stays readable without horizontal scroll;
   the line-number gutter hangs to the left of the wrapped block. */
#session-detail .cell-block pre.cell-code {
    white-space: pre-wrap; word-break: break-word;
}
#session-detail .cell-block pre.cell-code .cl {
    display: block; padding-left: 52px; text-indent: -52px;
    position: relative;
}
#session-detail .cell-block pre.cell-code .cl .ln { text-indent: 0; }
/* Per-line copy button — quiet until the line is hovered. Anchored at the right
   edge with a code-bg backing so it sits over the end of the line cleanly. */
#session-detail .cell-block pre.cell-code .cl .cl-copy {
    position: absolute; right: 2px; top: 0;
    opacity: 0; transition: opacity 0.12s;
    border: none; background: var(--code-bg); color: var(--muted);
    font-size: 11px; line-height: 1.5; padding: 0 4px;
    cursor: pointer; text-indent: 0; border-radius: 3px;
}
#session-detail .cell-block pre.cell-code .cl:hover .cl-copy { opacity: 0.8; }
#session-detail .cell-block pre.cell-code .cl .cl-copy:hover { opacity: 1; color: var(--fg); }
#session-detail .cell-block pre.cell-code .cl .cl-copy.copied { color: var(--green); opacity: 1; }

/* Python token colors (.tok-*) are defined unscoped in css/code.py so the
   Sessions cell viewer and the experiment detail view share one palette. */
/* Inline node-label rename (double-click the detail header label). */
#session-detail .node-label-text {
    cursor: text; border-bottom: 1px dashed transparent;
}
#session-detail .node-label-text:hover { border-bottom-color: var(--border); }
#session-detail .node-label-input {
    font-family: inherit; font-size: inherit; font-weight: inherit;
    color: var(--fg); background: var(--card-bg);
    border: 1px solid var(--blue); border-radius: 3px;
    padding: 1px 6px; min-width: 160px;
}
#session-detail .note-edit {
    width: 100%; min-height: 48px; padding: 6px 8px;
    border: 1px solid var(--border); border-radius: 4px;
    background: var(--card-bg); color: var(--fg);
    font-family: inherit; font-size: 12px;
    margin-bottom: 6px;
    resize: vertical;
}
#session-detail .note-actions {
    display: flex; align-items: center; gap: 10px;
}
#session-detail .note-save-status {
    font-size: 11px; color: var(--muted);
    transition: opacity 0.2s;
}
#session-detail .note-save-status.ok { color: var(--green); }
#session-detail .note-save-status.err { color: var(--red); }
#session-detail .cells-collapsed-hint {
    padding: 6px 10px; margin: 4px 0;
    border: 1px dashed var(--border); border-radius: 4px;
    background: var(--code-bg); color: var(--muted);
    font-size: 11px; cursor: pointer; user-select: none;
    display: flex; align-items: center; gap: 8px;
}
#session-detail .cells-collapsed-hint:hover {
    border-color: var(--blue); color: var(--fg);
}
#session-detail .cells-collapsed-hint .cch-chevron {
    color: var(--muted); font-size: 10px;
}
#session-detail button:disabled {
    opacity: 0.5; cursor: not-allowed;
}
/* "Promote to experiment" — accented so it reads as a primary action on a
   node that isn't linked to a run yet. */
#session-detail .node-materialize-btn {
    color: var(--accent, var(--blue)); border-color: var(--accent, var(--blue));
}
#session-detail .node-materialize-btn:hover {
    color: #fff; background: var(--accent, var(--blue));
    border-color: var(--accent, var(--blue));
}
/* Generic form buttons in the detail panel — excludes the quiet utility
   copy button, which carries its own (lower-weight) styling. */
#session-detail button:not(.sess-copy-btn) {
    font-family: inherit; font-size: 12px;
    padding: 4px 12px; border: 1px solid var(--border);
    background: var(--code-bg); color: var(--muted);
    border-radius: 4px; cursor: pointer;
}
#session-detail button:not(.sess-copy-btn):hover {
    color: var(--fg); border-color: var(--fg); background: var(--card-bg);
}

/* Per-session Trash panel (soft-deleted nodes). */
.session-view-actions {
    margin-top: 6px; display: flex; align-items: center; gap: 6px; flex-wrap: wrap;
}
/* End-session button (UI equivalent of `%exptrack session end`). */
.session-end-btn {
    font-family: inherit; font-size: 12px;
    padding: 4px 10px; border: 1px solid var(--border);
    background: var(--card-bg); color: var(--muted);
    border-radius: 4px; cursor: pointer;
}
.session-end-btn:hover {
    color: var(--y, #b58900); border-color: var(--y, #b58900); background: var(--code-bg);
}
.session-ended-tag {
    font-size: 11px; color: var(--y, #b58900);
    border: 1px solid var(--y, #b58900); border-radius: 4px;
    padding: 2px 8px; background: var(--code-bg);
}
/* Node-detail "Linked experiment" block + inline picker. */
.node-exp-link {
    display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 4px;
}
.node-exp-link .section-title { margin: 0; }
.node-exp-link .node-exp-none { font-size: 12px; color: var(--muted); }
.node-exp-link-btn {
    font-family: inherit; font-size: 11px;
    padding: 2px 9px; border: 1px solid var(--border);
    background: var(--card-bg); color: var(--accent, #2563eb);
    border-radius: 10px; cursor: pointer;
}
.node-exp-link-btn:hover {
    border-color: var(--accent, #2563eb); background: var(--code-bg);
}
.node-exp-link-btn.ghost { color: var(--muted); }
.node-exp-link-btn.ghost:hover { color: var(--red, #c92a2a); border-color: var(--red, #c92a2a); }
.link-exp-select {
    font-family: inherit; font-size: 12px; max-width: 320px;
    padding: 3px 6px; border: 1px solid var(--border); border-radius: 4px;
    background: var(--card-bg); color: var(--fg);
}
.session-trash-toggle {
    font-family: inherit; font-size: 12px;
    padding: 4px 10px; border: 1px solid var(--border);
    background: var(--card-bg); color: var(--muted);
    border-radius: 4px; cursor: pointer;
}
.session-trash-toggle:hover {
    color: var(--fg); border-color: var(--blue); background: var(--code-bg);
}
/* The trashed-node row styles below are now consumed by the unified Trash view
   (js/trash.py); the old per-session trash *panel* container/head/empty styles
   were removed when that panel moved into the unified Trash. */
.trash-help { font-size: 11px; color: var(--muted); }
.trash-rows { display: flex; flex-direction: column; gap: 4px; }
.trash-row {
    display: grid; grid-template-columns: 1fr auto;
    grid-template-areas: "main actions" "meta actions";
    gap: 2px 12px; align-items: center;
    padding: 6px 8px; border: 1px solid var(--border); border-radius: 4px;
    background: var(--code-bg);
}
.trash-row-main { grid-area: main; display: flex; gap: 8px; align-items: center; }
.trash-row-meta {
    grid-area: meta; font-size: 11px; color: var(--muted);
    font-family: 'IBM Plex Mono', monospace;
}
.trash-row-actions { grid-area: actions; }
.trash-type {
    font-size: 10px; text-transform: uppercase; letter-spacing: 0.05em;
    padding: 1px 6px; border-radius: 3px; border: 1px solid var(--border);
    color: var(--muted); background: var(--card-bg);
}
.trash-type-checkpoint { color: var(--blue); border-color: var(--blue); }
.trash-type-branch     { color: var(--blue); border-color: var(--blue); opacity: 0.85; }
.trash-type-abandoned  { color: var(--y, #b58900); border-color: var(--y, #b58900); }
.trash-label { font-size: 13px; color: var(--fg); }
.trash-restore-btn {
    font-family: inherit; font-size: 12px;
    padding: 3px 10px; border: 1px solid var(--border);
    background: var(--card-bg); color: var(--blue);
    border-radius: 3px; cursor: pointer;
}
.trash-restore-btn:hover {
    border-color: var(--blue); background: var(--code-bg);
}
.trash-row-actions { display: flex; gap: 6px; }
.trash-purge-btn {
    font-family: inherit; font-size: 12px;
    padding: 3px 10px; border: 1px solid var(--border);
    background: var(--card-bg); color: var(--red, #dc322f);
    border-radius: 3px; cursor: pointer;
}
.trash-purge-btn:hover { border-color: var(--red, #dc322f); background: var(--code-bg); }
.trash-empty-btn {
    font-family: inherit; font-size: 12px; margin-left: auto;
    padding: 3px 10px; border: 1px solid var(--red, #dc322f);
    background: var(--card-bg); color: var(--red, #dc322f);
    border-radius: 3px; cursor: pointer;
}
.trash-empty-btn:hover { background: var(--red, #dc322f); color: #fff; }
.session-trash-head { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }

/* ── Per-cell output capture ──────────────────────────────────────────── */
.cell-output-label, .cmp-result-label {
    font-size: 10px; text-transform: uppercase; letter-spacing: 0.06em;
    color: var(--muted); margin: 6px 0 2px;
    display: flex; align-items: center; gap: 8px;
}
/* "⧉ Copy" affordance on cell source / output / result blocks. The generic
   `#session-detail button` rule excludes `.sess-copy-btn`, so a single-class
   selector styles it everywhere (detail panel and compare columns alike). */
.sess-copy-btn {
    margin-left: auto; flex-shrink: 0;
    background: transparent; border: 1px solid var(--border);
    color: var(--muted); cursor: pointer;
    font-family: inherit; font-size: 10px; line-height: 1.4;
    padding: 1px 8px; border-radius: 10px; white-space: nowrap;
    text-transform: none; letter-spacing: 0;
    opacity: 0.55; transition: opacity 0.1s, color 0.1s, background 0.1s, border-color 0.1s;
}
.sess-copy-btn:hover {
    opacity: 1; color: var(--accent, #2563eb);
    border-color: var(--accent, #2563eb); background: var(--code-bg);
}
.sess-copy-btn.copied {
    opacity: 1; color: var(--green, #2f9e44); border-color: var(--green, #2f9e44);
}
/* In a cell summary the copy button sits on the right without forcing a wrap. */
#session-detail .cell-block summary .sess-copy-btn { margin-left: auto; }
/* A section-title holding a copy button (e.g. "Latest result") becomes a flex
   row so the button right-aligns. */
#session-detail .section-title:has(.sess-copy-btn) {
    display: flex; align-items: center;
}
.cell-output, .node-latest-result, .cmp-result {
    font-family: 'IBM Plex Mono', monospace; font-size: 12px;
    white-space: pre-wrap; word-break: break-word;
    background: var(--code-bg); border: 1px solid var(--border);
    /* Neutral bar — green means "added" in diffs, so don't reuse it for output. */
    border-left: 3px solid var(--border-strong);
    border-radius: 3px; padding: 6px 8px; margin: 0;
    /* No height cap — output expands fully so it's never cut off; drag the
       bottom edge to shrink a long block. */
    overflow: auto; resize: vertical;
}
.node-result-mini {
    font-family: 'IBM Plex Mono', monospace; font-size: 11px;
    color: var(--text-2); margin-top: 2px;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}

/* ── Per-node plot thumbnails (savefig captured by reference) ──────────── */
.node-img-grid {
    display: flex; flex-wrap: wrap; gap: 8px; margin: 2px 0 4px;
}
.node-img {
    margin: 0; width: 150px;
    border: 1px solid var(--border); border-radius: 4px;
    background: var(--code-bg); overflow: hidden;
}
.node-img a { display: block; line-height: 0; }
.node-img img {
    width: 100%; height: 104px; object-fit: contain;
    background: #fff; display: block;
}
.node-img figcaption {
    font-size: 10px; color: var(--muted); padding: 3px 5px;
    font-family: 'IBM Plex Mono', monospace;
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.node-img.img-missing img { display: none; }
.node-img.img-missing::after {
    content: '⚠ image missing on disk'; display: block;
    font-size: 10px; color: var(--y, #b58900); padding: 8px 6px;
    text-align: center;
}
.node-img-note { font-size: 11px; color: var(--muted); margin-top: 2px; }
.node-row .node-meta .nm-imgs { font-family: 'IBM Plex Mono', monospace; }
.cmp-col .node-img { width: 100%; }

/* ── Branch comparison ────────────────────────────────────────────────── */
.session-compare-toggle {
    font-family: inherit; font-size: 12px;
    padding: 3px 10px; border: 1px solid var(--border);
    background: var(--card-bg); color: var(--fg);
    border-radius: 3px; cursor: pointer; margin-right: 6px;
}
.session-compare-toggle.active {
    border-color: var(--compare-accent); color: var(--compare-accent);
    background: var(--compare-bg);
}
#session-compare-bar {
    display: flex; align-items: center; justify-content: space-between;
    gap: 12px; padding: 6px 10px; margin-bottom: 8px;
    border: 1px dashed var(--compare-accent); border-radius: 4px;
    background: var(--compare-bg);
    /* Sticky so you can pick nodes deep in a long tree and still reach
       Compare / Clear / Done without scrolling back to the top. */
    position: sticky; top: 0; z-index: 20;
}
.compare-bar-hint { font-size: 12px; color: var(--muted); }
.compare-bar-actions { display: flex; gap: 6px; }
.compare-bar-actions button {
    font-family: inherit; font-size: 12px; padding: 3px 12px;
    border: 1px solid var(--compare-accent); background: var(--compare-accent); color: #fff;
    border-radius: 3px; cursor: pointer;
}
.compare-bar-actions button:disabled { opacity: 0.45; cursor: default; }
.compare-bar-actions button.ghost { background: var(--card-bg); color: var(--compare-accent); }
body.session-compare-mode .node-row { cursor: copy; }
/* A picked node must be unmistakable next to the plain hover/selected accent
   (both blue, a thin 3px bar): use a violet 6px bar + matching tint so
   "picked for compare" never reads as "just clicked". */
.node-row.compare-picked {
    background: var(--compare-bg);
    box-shadow: inset 6px 0 0 var(--compare-accent);
    border-left-color: transparent;
}
/* Ordinal badge — shows the pick order (compare columns render in this order). */
.node-row .compare-pick-num {
    display: inline-flex; align-items: center; justify-content: center;
    width: 18px; height: 18px; border-radius: 50%;
    background: var(--compare-accent); color: #fff;
    font-size: 11px; font-weight: 700; line-height: 1;
    flex: 0 0 auto;
}
/* Compare columns: violet top accent ties them to the picked nodes. */
.cmp-col { border-top: 2px solid var(--compare-accent); }
#session-compare { margin-top: 12px; }
.cmp-head { display: flex; align-items: center; gap: 12px; margin-bottom: 8px; }
.cmp-head .ghost {
    font-family: inherit; font-size: 12px; padding: 2px 10px;
    border: 1px solid var(--border); background: var(--card-bg);
    color: var(--muted); border-radius: 3px; cursor: pointer; margin-left: auto;
}
.cmp-grid { display: grid; gap: 10px; }
.cmp-col {
    border: 1px solid var(--border); border-radius: 4px;
    padding: 8px; background: var(--card-bg); min-width: 0;
}
.cmp-col-head { display: flex; gap: 6px; align-items: baseline; margin-bottom: 4px; }
.cmp-type {
    font-size: 10px; text-transform: uppercase; letter-spacing: 0.05em;
    padding: 1px 6px; border-radius: 3px; border: 1px solid var(--border);
    color: var(--muted);
}
.cmp-type-checkpoint { color: var(--blue); border-color: var(--blue); }
.cmp-type-branch { color: var(--blue); border-color: var(--blue); opacity: 0.85; }
.cmp-label { font-size: 13px; font-weight: 600; color: var(--fg); word-break: break-word; }
.cmp-meta { font-size: 11px; color: var(--muted); margin-bottom: 6px;
    font-family: 'IBM Plex Mono', monospace; }
.cmp-meta a { color: var(--blue); text-decoration: none; }
.cmp-noexp { color: var(--muted); font-style: italic; }
.cmp-empty { color: var(--muted); font-style: italic; }
"""
