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
    const ts = s.created_at ? new Date(s.created_at * 1000).toLocaleString() : '';
    return `<div class="${cls}" onclick="selectSession('${s.id}')">
      <div class="session-card-header">
        <div class="name">${escapeHtml(s.name || '(unnamed)')}</div>
        <button class="session-delete-btn" title="Delete session"
          onclick="event.stopPropagation();deleteSession('${s.id}','${escapeHtml(s.name||'')}')">&times;</button>
      </div>
      <div class="meta">
        <span class="badge ${status}">${status}</span>
        ${s.checkpoints || 0} checkpoint${(s.checkpoints||0)===1?'':'s'} · ${s.promoted || 0} exp
      </div>
      <div class="meta">${escapeHtml(s.notebook || '')} ${ts ? '· ' + ts : ''}</div>
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
    <div style="margin-bottom:12px">
      <h2 style="margin:0 0 4px 0">${escapeHtml(s.name || '')}</h2>
      <div style="color:var(--muted);font-size:12px">
        ${escapeHtml(s.notebook || '(no notebook)')}
        ${s.git_branch ? '· branch ' + escapeHtml(s.git_branch) : ''}
        ${s.git_commit ? '· ' + escapeHtml(s.git_commit) : ''}
        ${s.status ? '· ' + escapeHtml(s.status) : ''}
      </div>
    </div>`;
  const treeHtml = root ? renderTreeNode(root, true) : '<div style="color:var(--muted)">(empty tree)</div>';
  view.innerHTML = headerHtml +
    '<div id="session-tree-container">' + treeHtml + '</div>' +
    '<div id="session-detail"></div>';
}

function renderTreeNode(node, isRoot) {
  const t = node.node_type || 'root';
  const cls = 'tree-node ' + t + (isRoot ? ' root' : '');
  const time = node.created_at ? new Date(node.created_at * 1000).toLocaleTimeString() : '';
  const diffSummary = summarizeDiff(node.git_diff);
  const cellCount = node.cell_source
    ? node.cell_source.split(/\n\n# ── cell ──\n\n/).length : 0;
  const cellsBadge = cellCount
    ? `<span class="node-diff">${cellCount} cell${cellCount===1?'':'s'}</span>` : '';
  const expBadge = node.exp_id
    ? `<a class="node-exp-badge" href="#" onclick="event.stopPropagation();showDetail('${node.exp_id}');return false">exp ${escapeHtml(node.exp_id.slice(0,8))}</a>`
    : '';
  const note = node.note ? `<span class="node-note-mini">${escapeHtml(truncate(node.note, 60))}</span>` : '';
  const childrenHtml = (node.children || []).map(ch => renderTreeNode(ch, false)).join('');
  const labelText = isRoot ? ('session start: ' + (node.label || '')) : (node.label || '');
  return `<div class="${cls}">
    ${isRoot ? '' : '<span class="node-marker"></span>'}
    <div class="node-row" onclick="selectNode('${node.id}')">
      <span class="node-type">${escapeHtml(t)}</span>
      <span class="node-label">${escapeHtml(labelText)}</span>
      ${time ? `<span class="node-time">${time}</span>` : ''}
      ${diffSummary ? `<span class="node-diff">${diffSummary}</span>` : ''}
      ${cellsBadge}
      ${expBadge}
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
  _selectedNodeId = nodeId;
  // Find node in cached tree
  const view = document.getElementById('session-tree-view');
  if (!view || !_activeSessionId) return;
  document.querySelectorAll('.node-row.selected').forEach(el => el.classList.remove('selected'));
  document.querySelectorAll('.node-row').forEach(el => {
    if (el.getAttribute('onclick') && el.getAttribute('onclick').indexOf(nodeId) !== -1) {
      el.classList.add('selected');
    }
  });
  renderSelectedNodeDetail(nodeId);
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
  detail.innerHTML = `
    <div><span class="section-title">${escapeHtml(node.node_type || '')}: ${escapeHtml(node.label || '')}</span></div>
    ${expLink}
    <div><span class="section-title">Note</span>
      <textarea class="note-edit" id="node-note-input" placeholder="(no note)">${escapeHtml(noteVal)}</textarea>
      <button onclick="saveNodeNote('${node.id}')">Save note</button>
    </div>
    ${renderNodeCells(node)}
    ${renderDiffSection(node.git_diff, _diffTitleForNode(node))}
  `;
}

function renderNodeCells(node) {
  if (!node.cell_source) return '';
  const cells = node.cell_source.split(/\n\n# ── cell ──\n\n/);
  const blocks = cells.map((c, i) => {
    const srcLines = c.split('\n');
    const open = !(cells.length > 3 && i < cells.length - 3);
    const numbered = srcLines.map((ln, k) =>
      `<span class="ln">${k + 1}</span>${escapeHtml(ln)}`
    ).join('\n');
    return `<details class="cell-block"${open ? ' open' : ''}>
      <summary>
        <span class="cell-idx">cell ${i + 1}${cells.length > 1 ? ' / ' + cells.length : ''}</span>
        <span class="cell-meta">${srcLines.length} line${srcLines.length === 1 ? '' : 's'}</span>
      </summary>
      <pre class="cell-code">${numbered}</pre>
    </details>`;
  }).join('');
  const heading = cells.length > 1
    ? `Cells run since previous node (${cells.length})`
    : 'Cell run since previous node';
  return `<div><span class="section-title">${heading}</span>${blocks}</div>`;
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
  const r = await postApi('/api/session/' + _activeSessionId + '/note-node',
    {node_id: nodeId, text: ta.value});
  if (r && r.ok) {
    delete _treeCache[_activeSessionId];
    renderSessionTree(_activeSessionId);
  }
}

function escapeHtml(s) {
  if (s == null) return '';
  return String(s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}
"""
