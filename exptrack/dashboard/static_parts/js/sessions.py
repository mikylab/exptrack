"""
exptrack/dashboard/static_parts/js/sessions.py — Session Trees UI logic.
"""

JS_SESSIONS = r"""
// ── Session Trees ──────────────────────────────────────────────────────────

let _sessionsCache = [];
let _activeSessionId = null;
let _selectedNodeId = null;
let _treeCache = {};  // sessionId -> last-fetched tree (avoid re-fetch per click)
let _lastSessionsLoad = 0;
let _compareMode = false;          // when on, clicking nodes toggles compare set
let _compareNodes = [];            // ordered list of node ids chosen to compare

function toggleSessionsTab() {
  // If already active, refresh instead of closing — closing is rarely what the
  // user wants and a stale list is the most common reason they re-click.
  const wasActive = document.body.classList.contains('sessions-active');
  if (wasActive) {
    loadSessionsList();
    return;
  }
  document.body.classList.add('sessions-active');
  const tab = document.getElementById('sessions-tab');
  const welcome = document.getElementById('welcome-state');
  const detail = document.getElementById('detail-view');
  const compare = document.getElementById('compare-view');
  if (tab) tab.style.display = 'flex';
  if (welcome) welcome.style.display = 'none';
  if (detail) detail.style.display = 'none';
  if (compare) compare.style.display = 'none';
  loadSessionsList();
}

function closeSessionsTab() {
  document.body.classList.remove('sessions-active');
  const tab = document.getElementById('sessions-tab');
  const welcome = document.getElementById('welcome-state');
  if (tab) tab.style.display = 'none';
  if (welcome) welcome.style.display = '';
}

// Auto-refresh the sessions list when the dashboard tab regains focus
// (the most common moment a session was just created in the notebook).
if (typeof window !== 'undefined' && !window._sessionsFocusBound) {
  window._sessionsFocusBound = true;
  // Both focus and visibilitychange can fire on tab switches; debounce so the
  // pair doesn't trigger two HTTP calls back-to-back.
  const _maybeReload = () => {
    if (!document.body.classList.contains('sessions-active')) return;
    if (Date.now() - _lastSessionsLoad < 500) return;
    loadSessionsList();
  };
  window.addEventListener('focus', _maybeReload);
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') _maybeReload();
  });
}

async function loadSessionsList() {
  _lastSessionsLoad = Date.now();
  _treeCache = {};  // explicit refresh always re-fetches the tree
  const root = document.getElementById('sessions-list-items');
  if (root) root.classList.add('refreshing');
  const data = await api('/api/sessions');
  _sessionsCache = (data && data.sessions) || [];
  renderSessionsList();
  // Stamp the header so the user can see the refresh actually ran
  const stamp = document.getElementById('sessions-updated-stamp');
  if (stamp) {
    const now = new Date();
    const t = now.toTimeString().slice(0, 8);
    stamp.textContent = 'updated ' + t;
  }
  if (root) {
    setTimeout(() => root.classList.remove('refreshing'), 300);
  }
  if (_sessionsCache.length && !_activeSessionId) {
    selectSession(_sessionsCache[0].id);
  } else if (_activeSessionId) {
    renderSessionTree(_activeSessionId);
  }
}

function renderSessionsList() {
  const root = document.getElementById('sessions-list-items');
  if (!root) return;
  if (!_sessionsCache.length) {
    root.innerHTML = '<div style="color:var(--muted);font-size:12px;padding:8px">No sessions yet.</div>';
    return;
  }
  const html = _sessionsCache.map(s => {
    const cls = (s.id === _activeSessionId) ? 'session-card active' : 'session-card';
    const status = s.status || 'active';
    const rel = s.created_at ? fmtTimeAgo(s.created_at * 1000) : '';
    const cps = s.checkpoints || 0;
    const promoted = s.promoted || 0;
    const promotedStr = promoted ? ` · ${promoted} exp` : '';
    return `<div class="${cls}" onclick="selectSession('${s.id}')">
      <div class="session-card-header">
        <div class="name">${escapeHtml(s.name || '(unnamed)')}</div>
        <span class="pill pill-${status}">${status}</span>
        <button class="session-delete-btn" title="Delete session"
          onclick="event.stopPropagation();deleteSession('${s.id}','${escapeHtml(s.name||'')}')">&times;</button>
      </div>
      <div class="session-card-sub">
        <span class="sc-notebook" title="${escapeHtml(s.notebook || '')}">${escapeHtml(s.notebook || '(no notebook)')}</span>
        <span class="sc-meta-tail">${cps} checkpoint${cps===1?'':'s'}${promotedStr}${rel ? ' · ' + rel : ''}</span>
      </div>
    </div>`;
  }).join('');
  root.innerHTML = html;
}


async function deleteSession(id, name) {
  if (!confirm(`Delete session "${name || id}"?\n\nLinked experiments are preserved (their session_node_id is cleared).`)) return;
  const r = await postApi('/api/session/' + id + '/delete', {});
  if (r && r.ok) {
    if (_activeSessionId === id) {
      _activeSessionId = null;
      _selectedNodeId = null;
      const view = document.getElementById('session-tree-view');
      if (view) view.innerHTML = '';
    }
    loadSessionsList();
  } else {
    alert('Could not delete session: ' + ((r && r.error) || 'unknown error'));
  }
}

function selectSession(id) {
  _activeSessionId = id;
  _selectedNodeId = null;
  // Reset compare selection — node ids don't carry across sessions.
  _compareMode = false;
  _compareNodes = [];
  document.body.classList.remove('session-compare-mode');
  renderSessionsList();
  renderSessionTree(id);
}

async function renderSessionTree(sid) {
  const view = document.getElementById('session-tree-view');
  if (!view) return;
  view.innerHTML = '<div style="color:var(--muted);padding:12px">Loading...</div>';
  const data = await api('/api/session/' + sid);
  if (!data || data.error) {
    view.innerHTML = '<div style="color:var(--muted);padding:12px">' +
      escapeHtml((data && data.error) || 'Could not load session') + '</div>';
    return;
  }
  _treeCache[sid] = data;
  const s = data.session || {};
  const root = data.root || null;
  const headerHtml = `
    <div class="session-view-header" style="margin-bottom:12px">
      <h2 style="margin:0 0 4px 0">${escapeHtml(s.name || '')}</h2>
      <div style="color:var(--muted);font-size:12px">
        ${escapeHtml(s.notebook || '(no notebook)')}
        ${s.git_branch ? '· branch ' + escapeHtml(s.git_branch) : ''}
        ${s.git_commit ? '· ' + escapeHtml(s.git_commit) : ''}
        ${s.status ? '· ' + escapeHtml(s.status) : ''}
      </div>
      <div class="session-view-actions">
        <button class="session-compare-toggle" id="session-compare-toggle" onclick="toggleCompareMode()">
          ⇄ Compare branches
        </button>
        <button class="session-trash-toggle" onclick="toggleSessionTrash()">
          🗑 Trash<span id="session-trash-count"></span>
        </button>
      </div>
    </div>`;
  const treeHtml = root ? renderTreeNode(root, true) : '<div style="color:var(--muted)">(empty tree)</div>';
  view.innerHTML = headerHtml +
    '<div id="session-trash-panel" style="display:none"></div>' +
    '<div id="session-compare-bar" style="display:none"></div>' +
    '<div id="session-tree-container">' + treeHtml + '</div>' +
    '<div id="session-compare" style="display:none"></div>' +
    '<div id="session-detail"></div>';
  document.body.classList.toggle('session-compare-mode', _compareMode);
  // Refresh the count chip in the background — doesn't block tree render.
  _refreshTrashCount();
}

async function _refreshTrashCount() {
  if (!_activeSessionId) return;
  const data = await api('/api/session/' + _activeSessionId + '/trash');
  const n = (data && data.nodes && data.nodes.length) || 0;
  const chip = document.getElementById('session-trash-count');
  if (chip) chip.textContent = n ? ' (' + n + ')' : '';
}

async function toggleSessionTrash() {
  const panel = document.getElementById('session-trash-panel');
  if (!panel || !_activeSessionId) return;
  if (panel.style.display !== 'none') {
    panel.style.display = 'none';
    return;
  }
  panel.style.display = 'block';
  renderTrashPanel();
}

// Fetch + render the trash panel in place (no toggle side effects), so
// mutations like purge/empty can refresh the list directly.
async function renderTrashPanel() {
  const panel = document.getElementById('session-trash-panel');
  if (!panel || !_activeSessionId) return;
  panel.innerHTML = '<div style="color:var(--muted);padding:8px">Loading trash…</div>';
  const data = await api('/api/session/' + _activeSessionId + '/trash');
  const nodes = (data && data.nodes) || [];
  if (!nodes.length) {
    panel.innerHTML = `<div class="session-trash-empty">
      Trash is empty for this session.
    </div>`;
    return;
  }
  const rows = nodes.map(n => {
    const rel = n.deleted_at ? fmtTimeAgo(n.deleted_at * 1000) : '';
    const cellBytes = n.cell_bytes || 0;
    const sizeBits = cellBytes ? ` · ${cellBytes} B of cells` : '';
    return `<div class="trash-row" data-trash-id="${escapeHtml(n.id)}">
      <div class="trash-row-main">
        <span class="trash-type trash-type-${escapeHtml(n.node_type)}">${escapeHtml(n.node_type)}</span>
        <span class="trash-label">${escapeHtml(n.label || '(unlabeled)')}</span>
      </div>
      <div class="trash-row-meta">
        deleted ${escapeHtml(rel)}${sizeBits}
      </div>
      <div class="trash-row-actions">
        <button class="trash-restore-btn" onclick="restoreNode('${n.id}')">Restore</button>
        <button class="trash-purge-btn" onclick="purgeNode('${n.id}','${escapeHtml(n.label||'')}')">Delete forever</button>
      </div>
    </div>`;
  }).join('');
  panel.innerHTML = `
    <div class="session-trash-head">
      <span class="section-title">Session trash</span>
      <button class="trash-empty-btn" onclick="emptySessionTrash()">Empty trash (${nodes.length})</button>
      <span class="trash-help">Restore brings the node and its trashed subtree back. <b>Delete forever</b> / Empty trash permanently removes nodes — no undo. Linked experiments are preserved either way.</span>
    </div>
    <div class="trash-rows">${rows}</div>`;
}

async function purgeNode(nodeId, label) {
  if (!_activeSessionId) return;
  if (!confirm(`Permanently delete "${label || nodeId}" and its trashed subtree?\n\nThis cannot be undone. Linked experiments are preserved; any attached plot files are moved to your OS Trash.`)) return;
  const r = await postApi('/api/session/' + _activeSessionId + '/purge-node', {node_id: nodeId});
  if (!r || r.error) {
    alert('Could not delete node: ' + ((r && r.error) || 'unknown error'));
    return;
  }
  _reportTrashedImages(r.images);
  _refreshTrashCount();
  renderTrashPanel();
}

// Surface how many by-reference plot files were moved to the OS Trash.
function _reportTrashedImages(images) {
  if (!images) return;
  const moved = (images.os_trash || 0) + (images.local_trash || 0);
  const failed = images.failed || 0;
  if (moved) {
    alert(`Moved ${moved} attached plot file${moved === 1 ? '' : 's'} to your OS Trash` +
      (failed ? ` (${failed} could not be removed and were left in place).` : '.'));
  } else if (failed) {
    alert(`${failed} attached plot file${failed === 1 ? '' : 's'} could not be removed and were left in place.`);
  }
}

async function emptySessionTrash() {
  if (!_activeSessionId) return;
  if (!confirm('Permanently delete EVERY node in the session trash?\n\nThis cannot be undone. Linked experiments are preserved; any attached plot files are moved to your OS Trash.')) return;
  const r = await postApi('/api/session/' + _activeSessionId + '/empty-trash', {});
  if (!r || r.error) {
    alert('Could not empty trash: ' + ((r && r.error) || 'unknown error'));
    return;
  }
  _reportTrashedImages(r.images);
  _refreshTrashCount();
  const panel = document.getElementById('session-trash-panel');
  if (panel) panel.innerHTML = `<div class="session-trash-empty">Trash is empty for this session.</div>`;
}

async function restoreNode(nodeId) {
  if (!_activeSessionId) return;
  const r = await postApi('/api/session/' + _activeSessionId + '/restore-node',
    {node_id: nodeId});
  if (!r || r.error) {
    alert('Could not restore node: ' + ((r && r.error) || 'unknown error'));
    return;
  }
  delete _treeCache[_activeSessionId];
  // Re-render tree + reload trash panel + refresh card counts.
  renderSessionTree(_activeSessionId);
  loadSessionsList();
  // The tree render replaces the panel container; reopen it so the user
  // sees the row vanish from the trash list.
  setTimeout(() => toggleSessionTrash(), 0);
}

function renderTreeNode(node, isRoot) {
  const t = node.node_type || 'root';
  const cls = 'tree-node ' + t + (isRoot ? ' root' : '');
  const time = node.created_at ? new Date(node.created_at * 1000).toLocaleTimeString() : '';
  const diffSummary = summarizeDiff(node.git_diff);
  const cellCount = node.cell_source
    ? node.cell_source.split(/\n\n# ── cell ──\n\n/).length : 0;
  const expBadge = node.exp_id
    ? `<a class="node-exp-badge" href="#" onclick="event.stopPropagation();showDetail('${node.exp_id}');return false">→ exp ${escapeHtml(node.exp_id.slice(0,8))}</a>`
    : '';
  const abandonedPill = t === 'abandoned'
    ? '<span class="pill pill-abandoned">abandoned</span>' : '';
  const note = node.note ? `<div class="node-note-mini">${escapeHtml(truncate(node.note, 120))}</div>` : '';
  const _latest = _getLatestOutput(node);
  const resultMini = _latest
    ? `<div class="node-result-mini" title="${escapeHtml(_latest)}">⤷ ${escapeHtml(truncate(_latest.replace(/\s+/g, ' '), 100))}</div>`
    : '';
  const childrenHtml = (node.children || []).map(ch => renderTreeNode(ch, false)).join('');
  const labelText = isRoot ? ('session start: ' + (node.label || '')) : (node.label || '(unlabeled)');
  const imgCount = _validImages(node).length;
  const metaBits = [];
  if (time) metaBits.push(`<span class="nm-time">${time}</span>`);
  if (cellCount) metaBits.push(`<span class="nm-cells">${cellCount} cell${cellCount===1?'':'s'}</span>`);
  if (imgCount) metaBits.push(`<span class="nm-imgs" title="${imgCount} plot${imgCount===1?'':'s'}">🖼 ${imgCount}</span>`);
  if (diffSummary) metaBits.push(`<span class="nm-diff">${diffSummary}</span>`);
  const metaLine = metaBits.length
    ? `<div class="node-meta">${metaBits.join('<span class="nm-sep">·</span>')}</div>` : '';
  const isEmpty = !cellCount && !(node.children && node.children.length)
    && (t === 'branch' || t === 'checkpoint');
  const awaitingLine = isEmpty
    ? '<div class="node-awaiting">awaiting first cell…</div>' : '';
  // While comparing, suppress the single-select highlight so it can't be
  // mistaken for a pick — the only blue accent in compare mode is a pick.
  const pickIdx = _compareNodes.indexOf(node.id);
  const selectedCls = (!_compareMode && node.id === _selectedNodeId ? ' selected' : '')
    + (pickIdx >= 0 ? ' compare-picked' : '');
  const pickBadge = pickIdx >= 0
    ? `<span class="compare-pick-num">${pickIdx + 1}</span>` : '';
  const deleteBtn = isRoot ? '' :
    `<button class="node-delete-btn" title="Delete this node and all descendants"
       onclick="event.stopPropagation();confirmDeleteNode('${node.id}')">&times;</button>`;
  return `<div class="${cls}" data-node-id="${escapeHtml(node.id)}">
    ${isRoot ? '' : '<span class="node-marker"></span>'}
    <div class="node-row${selectedCls}" data-node-id="${escapeHtml(node.id)}" onclick="selectNode('${node.id}')">
      <div class="node-row-main">
        ${pickBadge}
        <span class="node-label">${escapeHtml(labelText)}</span>
        ${abandonedPill}
        ${expBadge}
        ${deleteBtn}
      </div>
      ${metaLine}
      ${awaitingLine}
      ${resultMini}
      ${note}
    </div>
    ${childrenHtml}
  </div>`;
}

function summarizeDiff(diff) {
  if (!diff) return '';
  let plus = 0, minus = 0;
  const lines = diff.split('\n');
  for (const ln of lines) {
    if (ln.startsWith('+') && !ln.startsWith('+++')) plus++;
    else if (ln.startsWith('-') && !ln.startsWith('---')) minus++;
  }
  if (!plus && !minus) return '';
  return `+${plus} −${minus}`;
}

function truncate(s, n) {
  if (!s) return '';
  return s.length > n ? s.slice(0, n - 1) + '…' : s;
}

function selectNode(nodeId) {
  if (_compareMode) { toggleCompareNode(nodeId); return; }
  _selectedNodeId = nodeId;
  const view = document.getElementById('session-tree-view');
  if (!view || !_activeSessionId) return;
  document.querySelectorAll('.node-row.selected').forEach(el => el.classList.remove('selected'));
  const target = view.querySelector('.node-row[data-node-id="' + CSS.escape(nodeId) + '"]');
  if (target) target.classList.add('selected');
  renderSelectedNodeDetail(nodeId);
}

// ── Branch comparison ──────────────────────────────────────────────────────

// Re-render the tree from the cached data so picked/selected marks and the
// pick-order badges all reflect current state in one pass (removing a middle
// pick renumbers the rest, which a per-row class toggle can't do).
function _rerenderTreeContainer() {
  const data = _treeCache[_activeSessionId];
  const container = document.getElementById('session-tree-container');
  if (container && data && data.root) {
    container.innerHTML = renderTreeNode(data.root, true);
  }
}

function toggleCompareMode() {
  _compareMode = !_compareMode;
  _compareNodes = [];
  const btn = document.getElementById('session-compare-toggle');
  if (btn) btn.classList.toggle('active', _compareMode);
  document.body.classList.toggle('session-compare-mode', _compareMode);
  // Hide single-node detail while comparing; re-render so the prior selection
  // accent and any pick marks reset together.
  const detail = document.getElementById('session-detail');
  if (detail) detail.classList.remove('visible');
  _rerenderTreeContainer();
  _renderCompareBar();
  const panel = document.getElementById('session-compare');
  if (panel) { panel.style.display = 'none'; panel.innerHTML = ''; }
}

function toggleCompareNode(nodeId) {
  const i = _compareNodes.indexOf(nodeId);
  if (i >= 0) _compareNodes.splice(i, 1);
  else _compareNodes.push(nodeId);
  _rerenderTreeContainer();  // renumber badges across all rows
  _renderCompareBar();
}

function _renderCompareBar() {
  const bar = document.getElementById('session-compare-bar');
  if (!bar) return;
  if (!_compareMode) { bar.style.display = 'none'; bar.innerHTML = ''; return; }
  bar.style.display = 'flex';
  const n = _compareNodes.length;
  bar.innerHTML = `
    <span class="compare-bar-hint">${n
      ? n + ' node' + (n === 1 ? '' : 's') + ' selected — pick checkpoints/branches to compare'
      : 'Click nodes to add them to the comparison'}</span>
    <span class="compare-bar-actions">
      <button onclick="runCompare()" ${n < 2 ? 'disabled' : ''}>Compare ${n || ''}</button>
      <button class="ghost" onclick="clearCompare()" ${n ? '' : 'disabled'}>Clear</button>
    </span>`;
}

function clearCompare() {
  _compareNodes = [];
  _rerenderTreeContainer();
  _renderCompareBar();
  const panel = document.getElementById('session-compare');
  if (panel) { panel.style.display = 'none'; panel.innerHTML = ''; }
}

function runCompare() {
  const data = _treeCache[_activeSessionId];
  if (!data || _compareNodes.length < 2) return;
  const nodes = _compareNodes
    .map(id => findNodeInTree(data.root, id))
    .filter(Boolean);
  const panel = document.getElementById('session-compare');
  if (!panel) return;
  const cols = nodes.map(node => {
    const latest = _getLatestOutput(node);
    const cellCount = node.cell_source ? node.cell_source.split(_CELL_SEP_RE).length : 0;
    const diff = summarizeDiff(node.git_diff);
    const expBadge = node.exp_id
      ? `<a href="#" onclick="showDetail('${node.exp_id}');return false">→ exp ${escapeHtml(node.exp_id.slice(0,8))}</a>`
      : '<span class="cmp-noexp">not promoted</span>';
    const ci = _imgThumbs(node);
    const imgRow = ci.count
      ? `<div class="cmp-result-label">Plots</div>${ci.html}` : '';
    return `<div class="cmp-col">
      <div class="cmp-col-head">
        <span class="cmp-type cmp-type-${escapeHtml(node.node_type)}">${escapeHtml(node.node_type)}</span>
        <span class="cmp-label">${escapeHtml(node.label || '(unlabeled)')}</span>
      </div>
      <div class="cmp-meta">${cellCount} cell${cellCount===1?'':'s'}${diff ? ' · ' + diff : ''} · ${expBadge}</div>
      <div class="cmp-result-label">Result</div>
      <pre class="cmp-result">${latest ? escapeHtml(latest) : '<span class="cmp-empty">(no captured output)</span>'}</pre>
      ${imgRow}
    </div>`;
  }).join('');
  panel.innerHTML = `
    <div class="cmp-head">
      <span class="section-title">Comparing ${nodes.length} nodes</span>
      <button class="ghost" onclick="clearCompare()">Close</button>
    </div>
    <div class="cmp-grid" style="grid-template-columns:repeat(${nodes.length}, minmax(220px, 1fr))">${cols}</div>`;
  panel.style.display = 'block';
  panel.scrollIntoView({behavior: 'smooth', block: 'nearest'});
}

async function renderSelectedNodeDetail(nodeId) {
  const detail = document.getElementById('session-detail');
  if (!detail) return;
  let data = _treeCache[_activeSessionId];
  if (!data) {
    data = await api('/api/session/' + _activeSessionId);
    if (data && !data.error) _treeCache[_activeSessionId] = data;
  }
  const node = findNodeInTree(data && data.root, nodeId);
  if (!node) { detail.classList.remove('visible'); return; }
  detail.classList.add('visible');
  const noteVal = node.note || '';
  const expLink = node.exp_id
    ? `<div><span class="section-title">Promoted experiment</span>
        <a href="#" onclick="showDetail('${node.exp_id}');return false">${escapeHtml(node.exp_id)}</a></div>`
    : '';
  const latest = _getLatestOutput(node);
  const resultBlock = latest
    ? `<div><span class="section-title">Latest result</span>
        <pre class="node-latest-result">${escapeHtml(latest)}</pre></div>`
    : '';
  const _imgs = _imgThumbs(node);
  const imgBlock = _imgs.count
    ? `<div><span class="section-title">Plots (${_imgs.count})</span>${_imgs.html}</div>`
    : '';
  const renameable = node.node_type !== 'root';
  const labelHtml = renameable
    ? `<span class="node-label-text" id="node-label-text" title="Double-click to rename"
         ondblclick="startNodeRename('${node.id}')">${escapeHtml(node.label || '')}</span>`
    : escapeHtml(node.label || '');
  detail.innerHTML = `
    <div><span class="section-title">${escapeHtml(node.node_type || '')}: ${labelHtml}</span></div>
    ${expLink}
    ${resultBlock}
    ${imgBlock}
    <div><span class="section-title">Note</span>
      <textarea class="note-edit" id="node-note-input" placeholder="(no note)">${escapeHtml(noteVal)}</textarea>
      <div class="note-actions">
        <button id="node-note-save" onclick="saveNodeNote('${node.id}')" disabled>Save note</button>
        <span class="note-save-status" id="node-note-status"></span>
      </div>
    </div>
    ${renderNodeCells(node)}
    ${renderDiffSection(node.git_diff, _diffTitleForNode(node))}
  `;
  const ta = document.getElementById('node-note-input');
  const btn = document.getElementById('node-note-save');
  if (ta && btn) {
    const orig = ta.value;
    ta.addEventListener('input', () => {
      btn.disabled = (ta.value === orig);
      const s = document.getElementById('node-note-status');
      if (s) s.textContent = '';
    });
  }
}

const _CELL_SEP_RE = /\n\n# ── cell ──\n\n/;

// Split the SEP-joined outputs blob into a list aligned 1:1 with cells.
function _nodeOutputs(node) {
  if (!node.cell_outputs) return [];
  return node.cell_outputs.split(_CELL_SEP_RE);
}

// The most recent non-empty cell output for a node, or '' if none.
function _getLatestOutput(node) {
  const outs = _nodeOutputs(node).map(o => (o || '').trim()).filter(Boolean);
  return outs.length ? outs[outs.length - 1] : '';
}

// Images attached to a node that can actually be served (have a url).
function _validImages(node) {
  return (node.images || []).filter(im => im && im.url);
}

// Render a node's attached plots (captured by reference from savefig) as a
// thumbnail grid. Returns {count, html}; count excludes images outside the
// project root (can't be served). Missing-on-disk images degrade to a caption.
function _imgThumbs(node) {
  const all = node.images || [];
  const imgs = _validImages(node);
  if (!imgs.length) return {count: 0, html: ''};
  const thumbs = imgs.map(im => {
    const src = fileUrl(im.url);
    const cap = im.label || im.url.split('/').pop();
    return `<figure class="node-img">
      <a href="${src}" target="_blank" rel="noopener" title="${escapeHtml(im.path || im.url)}">
        <img src="${src}" alt="${escapeHtml(cap)}" loading="lazy"
          onerror="this.closest('.node-img').classList.add('img-missing')">
      </a>
      <figcaption>${escapeHtml(truncate(cap, 40))}</figcaption>
    </figure>`;
  }).join('');
  const missing = all.length - imgs.length;
  const note = missing
    ? `<div class="node-img-note">${missing} plot file${missing === 1 ? '' : 's'} outside the project root (not shown)</div>`
    : '';
  return {count: imgs.length, html: `<div class="node-img-grid">${thumbs}</div>${note}`};
}

// Python syntax highlighting (_highlightPy) + word-level diff helpers now live
// in the shared js/highlight.py module — used here and by the experiment view.

function renderNodeCells(node) {
  if (!node.cell_source) return '';
  const cells = node.cell_source.split(_CELL_SEP_RE);
  const outputs = _nodeOutputs(node);
  const collapseThreshold = 3;
  const hiddenCount = cells.length > collapseThreshold ? cells.length - collapseThreshold : 0;
  const blocks = cells.map((c, i) => {
    const srcLines = c.split('\n');
    const open = !(cells.length > collapseThreshold && i < cells.length - collapseThreshold);
    const numbered = srcLines.map((ln, k) =>
      `<span class="cl"><span class="ln">${k + 1}</span>${_highlightPy(ln)}</span>`
    ).join('');
    const out = (outputs[i] || '').trim();
    const outHtml = out
      ? `<div class="cell-output-label">Out</div><pre class="cell-output">${escapeHtml(out)}</pre>`
      : '';
    return `<details class="cell-block"${open ? ' open' : ''}>
      <summary>
        <span class="cell-idx">cell ${i + 1}${cells.length > 1 ? ' / ' + cells.length : ''}</span>
        <span class="cell-meta">${srcLines.length} line${srcLines.length === 1 ? '' : 's'}${out ? ' · has output' : ''}</span>
      </summary>
      <pre class="cell-code">${numbered}</pre>
      ${outHtml}
    </details>`;
  }).join('');
  const collapseHint = hiddenCount
    ? `<div class="cells-collapsed-hint" onclick="_expandAllCells(this)">
         <span class="cch-chevron">▸</span>
         ${hiddenCount} earlier cell${hiddenCount === 1 ? '' : 's'} collapsed — expand all
       </div>`
    : '';
  const heading = cells.length > 1
    ? `Cells run since previous node (${cells.length})`
    : 'Cell run since previous node';
  return `<div><span class="section-title">${heading}</span>${collapseHint}${blocks}</div>`;
}

function _expandAllCells(el) {
  const parent = el.parentNode;
  if (!parent) return;
  parent.querySelectorAll('details.cell-block').forEach(d => { d.open = true; });
  el.remove();
}

function _diffTitleForNode(node) {
  const t = node.node_type;
  if (t === 'branch') return 'Diff vs parent checkpoint';
  if (t === 'checkpoint') return 'Diff since previous checkpoint';
  return 'Git diff';
}

function _diffMode() {
  return localStorage.getItem('exptrack-diff-mode') || 'split';
}
function setDiffMode(mode) {
  localStorage.setItem('exptrack-diff-mode', mode);
  if (_selectedNodeId) renderSelectedNodeDetail(_selectedNodeId);
}

function _parseDiff(diff) {
  const files = [];
  let curFile = null;
  let curHunk = null;
  let totalAdd = 0, totalDel = 0;
  const newFile = (header) => {
    curFile = { header: header || '', hunks: [], plus: 0, minus: 0 };
    files.push(curFile);
    curHunk = null;
  };
  for (const ln of diff.split('\n')) {
    if (ln.startsWith('diff --git')) { newFile(ln); continue; }
    if (ln.startsWith('--- ') || ln.startsWith('+++ ')
        || ln.startsWith('index ') || ln.startsWith('new file')
        || ln.startsWith('deleted file') || ln.startsWith('similarity')
        || ln.startsWith('rename ')) {
      if (!curFile) newFile('');
      curFile.header += (curFile.header ? '\n' : '') + ln;
      continue;
    }
    if (ln.startsWith('@@')) {
      if (!curFile) newFile('');
      curHunk = { header: ln, rows: [] };
      curFile.hunks.push(curHunk);
      continue;
    }
    if (!curHunk) continue;
    let kind = 'ctx';
    if (ln.startsWith('+')) { kind = 'add'; curFile.plus++; totalAdd++; }
    else if (ln.startsWith('-')) { kind = 'del'; curFile.minus++; totalDel++; }
    curHunk.rows.push({ kind, text: ln.length ? ln.slice(1) : '' });
  }
  return { files, plus: totalAdd, minus: totalDel };
}

function _pairHunkRows(rows) {
  const pairs = [];
  let i = 0;
  while (i < rows.length) {
    const r = rows[i];
    if (r.kind === 'ctx') {
      pairs.push({ left: r, right: r });
      i++;
      continue;
    }
    const dels = [], adds = [];
    while (i < rows.length && rows[i].kind === 'del') { dels.push(rows[i]); i++; }
    while (i < rows.length && rows[i].kind === 'add') { adds.push(rows[i]); i++; }
    const n = Math.max(dels.length, adds.length);
    for (let k = 0; k < n; k++) {
      pairs.push({ left: dels[k] || null, right: adds[k] || null });
    }
  }
  return pairs;
}

function _shortFileLabel(header) {
  if (!header) return '(file)';
  const m = header.match(/^diff --git a\/(.+?) b\/(.+)$/m);
  if (m) return m[1] === m[2] ? m[1] : m[1] + ' → ' + m[2];
  const mm = header.match(/^\+\+\+ b\/(.+)$/m);
  if (mm) return mm[1];
  return header.split('\n')[0].slice(0, 80);
}

function renderDiffSection(diff, title) {
  if (!diff) return '';
  const parsed = _parseDiff(diff);
  if (!parsed.files.length) {
    return `<div><span class="section-title">${escapeHtml(title)}</span>
      <pre class="diff plain">${escapeHtml(diff)}</pre></div>`;
  }
  const mode = _diffMode();
  const summary = parsed.plus || parsed.minus
    ? `<span class="diff-summary"><span class="d-stat-add">+${parsed.plus}</span> <span class="d-stat-del">−${parsed.minus}</span></span>` : '';
  const toggle = `
    <span class="diff-mode-toggle">
      <button class="diff-mode-btn ${mode==='split'?'active':''}" onclick="setDiffMode('split')">Split</button>
      <button class="diff-mode-btn ${mode==='unified'?'active':''}" onclick="setDiffMode('unified')">Unified</button>
    </span>`;
  const openByDefault = parsed.files.length <= 4;
  const filesHtml = parsed.files.map(f =>
    _renderFileBlock(f, mode, openByDefault)
  ).join('');
  return `<div class="diff-section">
    <div class="diff-section-head">
      <span class="section-title">${escapeHtml(title)}</span>
      ${summary}
      ${toggle}
    </div>
    ${filesHtml}
  </div>`;
}

function _renderFileBlock(f, mode, openByDefault) {
  const label = _shortFileLabel(f.header);
  const head = `<summary class="diff-file-head">
    <span class="diff-file-name">${escapeHtml(label)}</span>
    <span class="diff-file-stats">
      <span class="d-stat-add">+${f.plus}</span>
      <span class="d-stat-del">−${f.minus}</span>
    </span>
  </summary>`;
  const body = f.hunks.map(h =>
    mode === 'split' ? _renderHunkSplit(h) : _renderHunkUnified(h)
  ).join('');
  return `<details class="diff-file"${openByDefault ? ' open' : ''}>${head}
    <div class="diff-file-body">${body || '<div class="diff-empty">(no hunks)</div>'}</div>
  </details>`;
}

function _renderHunkUnified(h) {
  const rows = h.rows.map(r => {
    const cls = 'du-' + r.kind;
    const sign = r.kind === 'add' ? '+' : r.kind === 'del' ? '−' : ' ';
    return `<div class="du-row ${cls}">
      <span class="du-sign">${sign}</span>
      <span class="du-text">${escapeHtml(r.text) || '&nbsp;'}</span>
    </div>`;
  }).join('');
  return `<div class="diff-hunk-head">${escapeHtml(h.header)}</div>
    <div class="diff-unified">${rows}</div>`;
}

function _renderHunkSplit(h) {
  const cell = (r) => {
    if (!r) return `<td class="ds-cell ds-empty"></td>`;
    return `<td class="ds-cell ds-${r.kind}"><span class="ds-text">${escapeHtml(r.text) || '&nbsp;'}</span></td>`;
  };
  const rowsHtml = _pairHunkRows(h.rows).map(p =>
    `<tr>${cell(p.left)}${cell(p.right)}</tr>`
  ).join('');
  return `<div class="diff-hunk-head">${escapeHtml(h.header)}</div>
    <table class="diff-split"><tbody>${rowsHtml}</tbody></table>`;
}

function findNodeInTree(root, id) {
  if (!root) return null;
  if (root.id === id) return root;
  for (const ch of (root.children || [])) {
    const found = findNodeInTree(ch, id);
    if (found) return found;
  }
  return null;
}

async function saveNodeNote(nodeId) {
  const ta = document.getElementById('node-note-input');
  if (!ta || !_activeSessionId) return;
  const btn = document.getElementById('node-note-save');
  const status = document.getElementById('node-note-status');
  if (btn) btn.disabled = true;
  if (status) status.textContent = 'Saving…';
  const r = await postApi('/api/session/' + _activeSessionId + '/note-node',
    {node_id: nodeId, text: ta.value});
  if (r && r.ok) {
    delete _treeCache[_activeSessionId];
    if (status) {
      const t = new Date().toTimeString().slice(0, 5);
      status.textContent = 'Saved · ' + t;
      status.classList.add('ok');
    }
    // Refresh the tree silently — but keep the detail open with the new value.
    const data = await api('/api/session/' + _activeSessionId);
    if (data && !data.error) {
      _treeCache[_activeSessionId] = data;
      // Re-render just the tree, not the detail (preserves saved indicator).
      const container = document.getElementById('session-tree-container');
      if (container && data.root) {
        container.innerHTML = renderTreeNode(data.root, true);
      }
    }
  } else {
    if (status) {
      status.textContent = 'Error: ' + ((r && r.error) || 'save failed');
      status.classList.remove('ok');
      status.classList.add('err');
    }
    if (btn) btn.disabled = false;
  }
}

// Inline-rename a node label from the detail header (double-click). Mirrors
// the experiment inline-edit pattern: Enter/blur saves, Escape cancels.
function startNodeRename(nodeId) {
  const span = document.getElementById('node-label-text');
  if (!span) return;
  const cur = span.textContent;
  const input = document.createElement('input');
  input.type = 'text';
  input.value = cur;
  input.className = 'node-label-input';
  span.replaceWith(input);
  input.focus();
  input.select();
  let done = false;
  const finish = async (save) => {
    if (done) return;
    done = true;
    const val = input.value.trim();
    if (!save || !val || val === cur) { renderSelectedNodeDetail(nodeId); return; }
    const r = await postApi('/api/session/' + _activeSessionId + '/rename-node',
      {node_id: nodeId, label: val});
    if (!r || r.error) {
      alert('Could not rename node: ' + ((r && r.error) || 'unknown error'));
      renderSelectedNodeDetail(nodeId);
      return;
    }
    // Refresh the cached tree so both the tree and detail show the new label.
    delete _treeCache[_activeSessionId];
    const data = await api('/api/session/' + _activeSessionId);
    if (data && !data.error) _treeCache[_activeSessionId] = data;
    _rerenderTreeContainer();
    renderSelectedNodeDetail(nodeId);
  };
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { e.preventDefault(); finish(true); }
    else if (e.key === 'Escape') { e.preventDefault(); finish(false); }
  });
  input.addEventListener('blur', () => finish(true));
}

async function confirmDeleteNode(nodeId) {
  if (!_activeSessionId) return;
  const preview = await postApi('/api/session/' + _activeSessionId + '/delete-node-preview',
    {node_id: nodeId});
  if (!preview || preview.error) {
    alert('Could not preview delete: ' + ((preview && preview.error) || 'unknown error'));
    return;
  }
  if (preview.is_root) {
    alert('Cannot delete the session root — use the session delete button instead.');
    return;
  }
  const label = preview.label || '(unlabeled)';
  const nodes = preview.nodes || 0;
  const desc = preview.descendants || 0;
  const exps = preview.experiments || 0;
  const lines = [];
  lines.push(`Delete ${preview.node_type} "${label}"?`);
  lines.push('');
  if (desc > 0) {
    lines.push(`This will also remove ${desc} descendant node${desc === 1 ? '' : 's'} ` +
               `(${nodes} total).`);
  } else {
    lines.push('This node has no descendants.');
  }
  if (exps > 0) {
    lines.push(`${exps} linked experiment${exps === 1 ? '' : 's'} will be preserved ` +
               '(their session_node_id is cleared).');
  }
  const imgs = preview.images || 0;
  if (imgs > 0) {
    lines.push(`${imgs} attached plot file${imgs === 1 ? '' : 's'} stay on disk for now — ` +
               'they move to your OS Trash only if you later permanently delete (purge) the node.');
  }
  lines.push('');
  lines.push('Moves the node(s) to this session\'s Trash — restore from the Trash panel.');
  if (!confirm(lines.join('\n'))) return;
  const r = await postApi('/api/session/' + _activeSessionId + '/delete-node',
    {node_id: nodeId});
  if (r && r.ok) {
    if (_selectedNodeId === nodeId) {
      _selectedNodeId = null;
      const detail = document.getElementById('session-detail');
      if (detail) { detail.innerHTML = ''; detail.classList.remove('visible'); }
    }
    delete _treeCache[_activeSessionId];
    renderSessionTree(_activeSessionId);
    // Refresh session card counts (checkpoint/exp totals).
    loadSessionsList();
  } else {
    alert('Could not delete node: ' + ((r && r.error) || 'unknown error'));
  }
}

function escapeHtml(s) {
  if (s == null) return '';
  return String(s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}
"""
