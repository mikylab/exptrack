"""Trash + delete-confirm modal.

Provides:
  deleteExp(id, name)         — opens the per-experiment confirm modal
  sidebarBulkDelete()         — opens the bulk confirm modal
  openTrashView() / closeTrashView() / loadTrashList()
  restoreExp(id) / bulkRestore(ids)
"""

JS_TRASH = r"""
// ── Helpers ─────────────────────────────────────────────────────────────────
function _fmtBytes(n) {
  if (!n) return '0 B';
  if (n < 1024) return n + ' B';
  if (n < 1024 * 1024) return (n / 1024).toFixed(1) + ' KB';
  if (n < 1024 * 1024 * 1024) return (n / 1024 / 1024).toFixed(1) + ' MB';
  return (n / 1024 / 1024 / 1024).toFixed(2) + ' GB';
}

function _closeDeleteModal() {
  const overlay = document.getElementById('dc-overlay');
  if (overlay) overlay.remove();
  document.removeEventListener('keydown', _deleteModalEsc);
}

function _deleteModalEsc(ev) {
  if (ev.key === 'Escape') _closeDeleteModal();
}

function _switchDcTab(tab) {
  const trashPane = document.getElementById('dc-pane-trash');
  const permPane = document.getElementById('dc-pane-perm');
  const trashTab = document.getElementById('dc-tab-trash');
  const permTab = document.getElementById('dc-tab-perm');
  const trashBtn = document.getElementById('dc-btn-trash');
  const permBtn = document.getElementById('dc-btn-perm');
  const filesRow = document.getElementById('dc-files-row');
  if (tab === 'perm') {
    trashPane.style.display = 'none';
    permPane.style.display = '';
    trashTab.classList.remove('active');
    permTab.classList.add('active');
    if (trashBtn) trashBtn.style.display = 'none';
    if (permBtn) permBtn.style.display = '';
    if (filesRow) filesRow.style.display = '';
  } else {
    trashPane.style.display = '';
    permPane.style.display = 'none';
    trashTab.classList.add('active');
    permTab.classList.remove('active');
    if (trashBtn) trashBtn.style.display = '';
    if (permBtn) permBtn.style.display = 'none';
    if (filesRow) filesRow.style.display = 'none';
  }
}

// ── Per-experiment confirm ──────────────────────────────────────────────────
async function deleteExp(id, name) {
  owlSpeak('delete');
  let preview;
  try {
    preview = await api('/api/experiment/' + encodeURIComponent(id) + '/delete-preview');
  } catch (e) {
    alert('Could not load delete preview: ' + e);
    return;
  }
  if (preview && preview.error) {
    alert('Could not load delete preview: ' + preview.error);
    return;
  }
  _openDeleteModalSingle(id, name, preview);
}

function _openDeleteModalSingle(id, name, p) {
  _closeDeleteModal();
  const trashSummary = '<p>Move this experiment to Trash. Nothing on disk is touched. ' +
    'You can restore it later from the Trash view.</p>';
  const scopeHtml =
    '<div class="dc-subject">' +
      '<span class="dc-subject-name">' + esc(name || '(unnamed)') + '</span>' +
      '<span class="dc-subject-id">' + esc(String(id).slice(0, 8)) + '</span>' +
    '</div>' +
    '<div class="dc-scope-grid">' +
      '<div class="dc-scope-key">Metrics</div>' +
        '<div class="dc-scope-val">' + p.metrics_count + '</div>' +
      '<div class="dc-scope-key">Params</div>' +
        '<div class="dc-scope-val">' + p.params_count + '</div>' +
      '<div class="dc-scope-key">Timeline events</div>' +
        '<div class="dc-scope-val">' + p.timeline_count + '</div>' +
      '<div class="dc-scope-key">Artifacts</div>' +
        '<div class="dc-scope-val">' + p.artifacts_count +
          ' (' + p.artifacts_existing + ' file' + (p.artifacts_existing === 1 ? '' : 's') +
          ' on disk, ' + _fmtBytes(p.artifact_bytes) + ')</div>' +
      '<div class="dc-scope-key">Output dir</div>' +
        '<div class="dc-scope-val">' +
          (p.output_dir ? esc(p.output_dir) +
            (p.output_dir_exists
              ? ' <span style="color:var(--muted)">(' + p.output_dir_files + ' files, ' + _fmtBytes(p.output_dir_bytes) + ')</span>'
              : ' <span style="color:var(--muted)">(missing)</span>')
            : '<span style="color:var(--muted)">none</span>') +
        '</div>' +
      '<div class="dc-scope-key">Notebook history</div>' +
        '<div class="dc-scope-val">' + p.notebook_history_count + ' snapshot' + (p.notebook_history_count === 1 ? '' : 's') + '</div>' +
    '</div>';
  _renderDeleteModal({
    title: 'Delete experiment',
    trashSummaryHtml: trashSummary,
    permScopeHtml: scopeHtml,
    onTrash: async () => {
      const r = await postApi('/api/experiment/' + encodeURIComponent(id) + '/delete');
      if (!r.ok) { alert(r.error || 'Failed'); return; }
      _closeDeleteModal();
      _afterMutation(id);
    },
    onPermanent: async (deleteFiles) => {
      const r = await postApi('/api/experiment/' + encodeURIComponent(id) + '/delete-permanent',
        { delete_files: !!deleteFiles });
      if (!r.ok) { alert(r.error || 'Failed'); return; }
      _closeDeleteModal();
      _afterMutation(id);
    },
  });
}

// ── Bulk confirm (called from sidebar) ──────────────────────────────────────
async function sidebarBulkDelete() {
  owlSpeak('delete');
  const ids = [...selectedIds];
  if (!ids.length) return;
  let preview;
  try {
    preview = await postApi('/api/bulk-delete-preview', { ids });
  } catch (e) {
    alert('Could not load delete preview: ' + e);
    return;
  }
  if (preview && preview.error) { alert(preview.error); return; }
  _openDeleteModalBulk(ids, preview);
}

function _openDeleteModalBulk(ids, p) {
  _closeDeleteModal();
  const t = p.totals || {};
  const itemRows = (p.items || []).slice(0, 50).map(it =>
    '<div class="dc-bulk-item">' +
      '<div class="dc-bulk-name">' + esc(it.name || it.id) + '</div>' +
      '<div class="dc-bulk-meta">' + it.artifacts + ' art' +
        (it.artifact_bytes ? ' · ' + _fmtBytes(it.artifact_bytes) : '') +
      '</div>' +
    '</div>').join('');
  const moreNote = (p.items || []).length > 50 ?
    '<div style="padding:4px 8px;color:var(--muted);font-size:11px">… ' + ((p.items.length - 50)) + ' more</div>' : '';
  const trashSummary = '<p>Move <b>' + (t.experiments || 0) + '</b> experiments to Trash. ' +
    'Nothing on disk is touched. You can restore them from the Trash view.</p>' +
    '<div class="dc-bulk-list">' + itemRows + moreNote + '</div>';
  const scopeHtml =
    '<div class="dc-scope-grid">' +
      '<div class="dc-scope-key">Experiments</div>' +
        '<div class="dc-scope-val">' + (t.experiments || 0) + '</div>' +
      '<div class="dc-scope-key">Metrics</div>' +
        '<div class="dc-scope-val">' + (t.metrics || 0) + '</div>' +
      '<div class="dc-scope-key">Params</div>' +
        '<div class="dc-scope-val">' + (t.params || 0) + '</div>' +
      '<div class="dc-scope-key">Artifacts</div>' +
        '<div class="dc-scope-val">' + (t.artifacts || 0) +
          ' (' + (t.artifacts_existing || 0) + ' on disk, ' + _fmtBytes(t.artifact_bytes || 0) + ')</div>' +
      '<div class="dc-scope-key">Output dirs</div>' +
        '<div class="dc-scope-val">' + (t.output_dirs_existing || 0) + ' (' +
          (t.output_dir_files || 0) + ' files, ' + _fmtBytes(t.output_dir_bytes || 0) + ')</div>' +
      '<div class="dc-scope-key">Notebook history</div>' +
        '<div class="dc-scope-val">' + (t.notebook_history || 0) + '</div>' +
    '</div>' +
    '<div class="dc-bulk-list" style="margin-top:8px">' + itemRows + moreNote + '</div>';
  _renderDeleteModal({
    title: 'Delete ' + ids.length + ' experiment' + (ids.length === 1 ? '' : 's'),
    trashSummaryHtml: trashSummary,
    permScopeHtml: scopeHtml,
    onTrash: async () => {
      const r = await postApi('/api/bulk-delete', { ids });
      if (!r.ok) { alert(r.error || 'Failed'); return; }
      _closeDeleteModal();
      selectedIds.clear();
      _afterMutation('');
    },
    onPermanent: async (deleteFiles) => {
      const r = await postApi('/api/bulk-delete-permanent',
        { ids, delete_files: !!deleteFiles });
      if (!r.ok) { alert(r.error || 'Failed'); return; }
      _closeDeleteModal();
      selectedIds.clear();
      _afterMutation('');
    },
  });
}

// ── Shared modal renderer ───────────────────────────────────────────────────
function _renderDeleteModal(opts) {
  const overlay = document.createElement('div');
  overlay.className = 'dc-overlay';
  overlay.id = 'dc-overlay';
  overlay.addEventListener('click', (ev) => { if (ev.target === overlay) _closeDeleteModal(); });

  overlay.innerHTML =
    '<div class="dc-dialog">' +
      '<div class="dc-header">' +
        '<h3>' + esc(opts.title) + '</h3>' +
        '<button class="dc-close" onclick="_closeDeleteModal()">&times;</button>' +
      '</div>' +
      '<div class="dc-body">' +
        '<div class="dc-tabs">' +
          '<button class="dc-tab active" id="dc-tab-trash" onclick="_switchDcTab(\'trash\')">Move to Trash</button>' +
          '<button class="dc-tab" id="dc-tab-perm" onclick="_switchDcTab(\'perm\')">Permanently delete…</button>' +
        '</div>' +
        '<div id="dc-pane-trash">' +
          opts.trashSummaryHtml +
          '<div class="dc-info">Files on disk (artifacts and output directories) are not touched. Use the Trash view to restore or permanently delete later.</div>' +
        '</div>' +
        '<div id="dc-pane-perm" style="display:none">' +
          opts.permScopeHtml +
          '<div class="dc-warning"><b>Permanent delete:</b> removes the database record for the experiment (metrics, params, artifact entries, timeline events). This cannot be undone. Files on disk are preserved unless the checkbox below is checked — in which case they go to your system Trash, not <code>rm -rf</code>.</div>' +
        '</div>' +
      '</div>' +
      '<div class="dc-footer">' +
        '<div class="dc-footer-left">' +
          '<label class="dc-files-checkbox" id="dc-files-row" style="display:none">' +
            '<input type="checkbox" id="dc-files-checkbox">' +
            '<span class="dc-files-checkbox-label">Also move files to system Trash' +
              '<span class="dc-files-checkbox-hint">artifact files and the output directory go to your OS Trash (recoverable in Finder/Files), with a <code>.exptrack/trash/</code> fallback if the OS call fails</span>' +
            '</span>' +
          '</label>' +
        '</div>' +
        '<div class="dc-footer-right">' +
          '<button class="dc-button" onclick="_closeDeleteModal()">Cancel</button>' +
          '<button class="dc-button primary" id="dc-btn-trash">Move to Trash</button>' +
          '<button class="dc-button danger" id="dc-btn-perm" style="display:none">Permanently delete</button>' +
        '</div>' +
      '</div>' +
    '</div>';

  document.body.appendChild(overlay);
  document.addEventListener('keydown', _deleteModalEsc);
  document.getElementById('dc-btn-trash').addEventListener('click', () => opts.onTrash());
  document.getElementById('dc-btn-perm').addEventListener('click', () => {
    const cb = document.getElementById('dc-files-checkbox');
    opts.onPermanent(cb && cb.checked);
  });
}

function _afterMutation(id) {
  if (typeof showWelcome === 'function') showWelcome();
  if (typeof loadStats === 'function') loadStats();
  if (typeof loadExperiments === 'function') loadExperiments();
  _refreshTrashCount();
  if (document.body.classList.contains('trash-active')) loadTrashList();
}

// ── Trash view (unified: experiments + session nodes) ───────────────────────
// _trashCache holds the whole unified payload: {experiments:[...], sessions:[...]}.
// _trashSelected tracks the bulk selection for the Experiments section only.
let _trashCache = { experiments: [], sessions: [] };
let _trashSelected = new Set();

function toggleTrashView() {
  if (document.body.classList.contains('trash-active')) {
    closeTrashView();
  } else {
    openTrashView();
  }
}

// Remember where Trash was opened from so closing returns there (not always
// the welcome screen). Currently only the Sessions tab needs restoring.
let _trashReturnView = null;

function openTrashView() {
  _trashReturnView = document.body.classList.contains('sessions-active') ? 'sessions' : null;
  document.body.classList.add('trash-active');
  document.body.classList.remove('sessions-active');
  const tv = document.getElementById('trash-view');
  const welcome = document.getElementById('welcome-state');
  const detail = document.getElementById('detail-view');
  const compare = document.getElementById('compare-view');
  const sessTab = document.getElementById('sessions-tab');
  // Hide everything else FIRST, then show trash. Don't call closeSessionsTab()
  // here — it has a side effect of re-showing #welcome-state, which would sit
  // on top of #trash-view.
  if (welcome) welcome.style.display = 'none';
  if (detail) detail.style.display = 'none';
  if (compare) compare.style.display = 'none';
  if (sessTab) sessTab.style.display = 'none';
  if (tv) tv.style.display = '';
  // Also close the Settings panel if it's open (this is usually how Trash is launched).
  const settings = document.getElementById('settings-panel');
  if (settings && settings.classList.contains('visible')) {
    settings.classList.remove('visible');
  }
  loadTrashList();
}

function closeTrashView() {
  document.body.classList.remove('trash-active');
  const tv = document.getElementById('trash-view');
  if (tv) tv.style.display = 'none';
  // Return to the view Trash was opened from. The Sessions tab needs its own
  // teardown undone (openTrashView hid #sessions-tab + dropped sessions-active);
  // toggleSessionsTab() re-shows it (it opens, since the class was removed).
  if (_trashReturnView === 'sessions' && typeof toggleSessionsTab === 'function') {
    _trashReturnView = null;
    toggleSessionsTab();
    return;
  }
  const welcome = document.getElementById('welcome-state');
  if (welcome) welcome.style.display = '';
}

async function loadTrashList() {
  const container = document.getElementById('trash-view');
  if (!container) return;
  let data;
  try {
    data = await api('/api/trash');
  } catch (e) {
    container.innerHTML = '<div class="trash-empty">Could not load Trash: ' + esc(String(e)) + '</div>';
    return;
  }
  // New unified shape {experiments, sessions}; tolerate the old bare-array shape.
  if (Array.isArray(data)) data = { experiments: data, sessions: [] };
  _trashCache = {
    experiments: (data && data.experiments) || [],
    sessions: (data && data.sessions) || [],
  };
  _trashSelected = new Set([..._trashSelected].filter(
    id => _trashCache.experiments.find(r => r.id === id)));
  _renderTrashView();
  _refreshTrashCount();
}

function _renderTrashView() {
  const container = document.getElementById('trash-view');
  if (!container) return;
  const exps = _trashCache.experiments || [];
  const sessions = _trashCache.sessions || [];
  const nodeTotal = sessions.reduce((a, g) => a + (g.nodes ? g.nodes.length : 0), 0);
  const grandTotal = exps.length + nodeTotal;

  let html = '<div class="trash-header">' +
    '<h2>Trash <span style="color:var(--muted);font-weight:400;font-size:14px">(' + grandTotal + ')</span></h2>' +
    '<div class="trash-actions">' +
      '<button class="dc-button" onclick="closeTrashView()">Close</button>' +
    '</div>' +
  '</div>' +
  '<p class="trash-blurb">Soft-deleted items live here — both experiments and session-tree nodes. ' +
    'They are hidden from the dashboard and stats, but their database rows and files are untouched. ' +
    'Restore them, or use <b>Permanently delete</b> / <b>Delete forever</b> to remove the record. ' +
    'A checkbox in the experiment permanent-delete confirm lets you also remove files on disk; ' +
    'purging a session node moves its by-reference plot files to your OS Trash.</p>';

  if (!grandTotal) {
    html += '<div class="trash-empty">Trash is empty.</div>';
    container.innerHTML = html;
    return;
  }

  html += _renderTrashExpSection(exps);
  html += _renderTrashNodeSection(sessions, nodeTotal);
  container.innerHTML = html;
}

// ── Experiments section ───────────────────────────────────────────────────
function _renderTrashExpSection(rows) {
  let html = '<div class="trash-section">' +
    '<div class="trash-section-head">' +
      '<span class="trash-section-title">Experiments <span class="trash-section-count">(' + rows.length + ')</span></span>' +
      '<div class="trash-actions">' +
        (rows.length ? '<button class="dc-button" onclick="_trashSelectAll(this)">' +
          (_trashSelected.size === rows.length ? 'Deselect all' : 'Select all') + '</button>' : '') +
        (_trashSelected.size ? '<button class="dc-button primary" onclick="trashBulkRestore()">Restore (' + _trashSelected.size + ')</button>' : '') +
        (_trashSelected.size ? '<button class="dc-button danger" onclick="trashBulkPermanent()">Permanently delete (' + _trashSelected.size + ')</button>' : '') +
      '</div>' +
    '</div>';
  if (!rows.length) {
    html += '<div class="trash-empty">No trashed experiments.</div></div>';
    return html;
  }
  html += '<table class="trash-table">' +
    '<thead><tr>' +
      '<th class="trash-row-checkbox"></th>' +
      '<th>Experiment</th>' +
      '<th>Deleted</th>' +
      '<th>Status</th>' +
      '<th>Metrics</th>' +
      '<th>Artifacts</th>' +
      '<th style="text-align:right">Actions</th>' +
    '</tr></thead><tbody>';
  for (const r of rows) {
    const checked = _trashSelected.has(r.id) ? ' checked' : '';
    html += '<tr>' +
      '<td class="trash-row-checkbox"><input type="checkbox"' + checked +
        ' onchange="_trashToggle(\'' + r.id + '\', this.checked)"></td>' +
      '<td>' +
        '<div class="trash-name">' + esc(r.name || '(unnamed)') + '</div>' +
        '<div class="trash-id">' + esc(r.id.slice(0, 12)) + '</div>' +
      '</td>' +
      '<td class="trash-deleted">' + esc(_fmtTrashTime(r.deleted_at)) + '</td>' +
      '<td class="trash-meta">' + esc(r.status || '') + '</td>' +
      '<td class="trash-meta">' + r.metrics_count + '</td>' +
      '<td class="trash-meta">' + r.artifacts_count + '</td>' +
      '<td><div class="trash-row-actions">' +
        '<button class="dc-button" onclick="restoreExp(\'' + r.id + '\')">Restore</button>' +
        '<button class="dc-button danger" onclick="trashPermanent(\'' + r.id + '\',\'' + esc(r.name || '').replace(/\'/g, "\\\\'") + '\')">Delete…</button>' +
      '</div></td>' +
    '</tr>';
  }
  html += '</tbody></table></div>';
  return html;
}

// ── Session-nodes section (grouped by session) ─────────────────────────────
function _renderTrashNodeSection(sessions, nodeTotal) {
  let html = '<div class="trash-section">' +
    '<div class="trash-section-head">' +
      '<span class="trash-section-title">Session nodes <span class="trash-section-count">(' + nodeTotal + ')</span></span>' +
    '</div>';
  if (!nodeTotal) {
    html += '<div class="trash-empty">No trashed session nodes.</div></div>';
    return html;
  }
  for (const g of sessions) {
    const nodes = g.nodes || [];
    if (!nodes.length) continue;
    const sid = g.session.id;
    const sname = g.session.name || '(unnamed session)';
    html += '<div class="trash-session-group">' +
      '<div class="trash-session-head">' +
        '<span class="trash-session-name" onclick="openSessionsTabFor(\'' + sid + '\')" title="Open this session">' +
          esc(sname) + '</span>' +
        (g.session.status ? '<span class="trash-session-status">' + esc(g.session.status) + '</span>' : '') +
        '<button class="dc-button danger" onclick="emptyTrashSession(\'' + sid + '\',\'' +
          esc(sname).replace(/\'/g, "\\\\'") + '\')">Empty (' + nodes.length + ')</button>' +
      '</div>' +
      '<div class="trash-rows">';
    for (const n of nodes) {
      const rel = n.deleted_at ? _fmtNodeTime(n.deleted_at) : '';
      const cb = n.cell_bytes ? ' · ' + n.cell_bytes + ' B of cells' : '';
      html += '<div class="trash-row">' +
        '<div class="trash-row-main">' +
          '<span class="trash-type trash-type-' + esc(n.node_type) + '">' + esc(n.node_type) + '</span>' +
          '<span class="trash-label">' + esc(n.label || '(unlabeled)') + '</span>' +
        '</div>' +
        '<div class="trash-row-meta">deleted ' + esc(rel) + cb + '</div>' +
        '<div class="trash-row-actions">' +
          '<button class="trash-restore-btn" onclick="restoreTrashNode(\'' + sid + '\',\'' + n.id + '\')">Restore</button>' +
          '<button class="trash-purge-btn" onclick="purgeTrashNode(\'' + sid + '\',\'' + n.id + '\',\'' +
            esc(n.label || '').replace(/\'/g, "\\\\'") + '\')">Delete forever</button>' +
        '</div>' +
      '</div>';
    }
    html += '</div></div>';
  }
  html += '</div>';
  return html;
}

function _fmtNodeTime(unixSecs) {
  try {
    if (typeof fmtTimeAgo === 'function') return fmtTimeAgo(unixSecs * 1000);
    return new Date(unixSecs * 1000).toLocaleString();
  } catch (e) { return ''; }
}

// Jump from a trashed-node row to its session in the Sessions tab. The trashed
// node itself won't be in the (live) tree, so we just open the session.
function openSessionsTabFor(sessionId) {
  closeTrashView();
  if (typeof openSessionNode === 'function') openSessionNode(sessionId, null);
}

// ── Session-node actions (call the existing per-session endpoints) ──────────
async function restoreTrashNode(sid, nodeId) {
  const r = await postApi('/api/session/' + encodeURIComponent(sid) + '/restore-node', { node_id: nodeId });
  if (!r || r.error) { alert('Could not restore node: ' + ((r && r.error) || 'unknown error')); return; }
  _afterNodeTrashMutation(sid);
}

async function purgeTrashNode(sid, nodeId, label) {
  if (!confirm('Permanently delete "' + (label || nodeId) + '" and its trashed subtree?\n\n' +
    'This cannot be undone. Linked experiments are preserved; any attached plot files are moved to your OS Trash.')) return;
  const r = await postApi('/api/session/' + encodeURIComponent(sid) + '/purge-node', { node_id: nodeId });
  if (!r || r.error) { alert('Could not delete node: ' + ((r && r.error) || 'unknown error')); return; }
  _reportTrashedImages(r.images);
  _afterNodeTrashMutation(sid);
}

async function emptyTrashSession(sid, name) {
  if (!confirm('Permanently delete EVERY trashed node in session "' + (name || sid) + '"?\n\n' +
    'This cannot be undone. Linked experiments are preserved; any attached plot files are moved to your OS Trash.')) return;
  const r = await postApi('/api/session/' + encodeURIComponent(sid) + '/empty-trash', {});
  if (!r || r.error) { alert('Could not empty trash: ' + ((r && r.error) || 'unknown error')); return; }
  _reportTrashedImages(r.images);
  _afterNodeTrashMutation(sid);
}

function _afterNodeTrashMutation(sid) {
  // The node trees may be showing; drop the cache so a later open re-fetches.
  if (typeof _treeCache === 'object' && _treeCache) delete _treeCache[sid];
  loadTrashList();
  if (typeof loadStats === 'function') loadStats();
  if (typeof loadSessionsList === 'function') loadSessionsList();
}

// Surface how many by-reference plot files were moved to the OS Trash on purge.
function _reportTrashedImages(images) {
  if (!images) return;
  const moved = (images.os_trash || 0) + (images.local_trash || 0);
  const failed = images.failed || 0;
  if (moved) {
    alert('Moved ' + moved + ' attached plot file' + (moved === 1 ? '' : 's') + ' to your OS Trash' +
      (failed ? ' (' + failed + ' could not be removed and were left in place).' : '.'));
  } else if (failed) {
    alert(failed + ' attached plot file' + (failed === 1 ? '' : 's') + ' could not be removed and were left in place.');
  }
}

function _fmtTrashTime(iso) {
  if (!iso) return '';
  try {
    const d = new Date(iso);
    if (typeof formatTimestamp === 'function') return formatTimestamp(iso);
    return d.toLocaleString();
  } catch (e) { return iso; }
}

function _trashToggle(id, on) {
  if (on) _trashSelected.add(id); else _trashSelected.delete(id);
  _renderTrashView();
}

function _trashSelectAll(btn) {
  const exps = _trashCache.experiments || [];
  if (_trashSelected.size === exps.length) _trashSelected.clear();
  else _trashSelected = new Set(exps.map(r => r.id));
  _renderTrashView();
}

async function restoreExp(id) {
  const r = await postApi('/api/experiment/' + encodeURIComponent(id) + '/restore');
  if (!r.ok) { alert(r.error || 'Failed'); return; }
  _trashSelected.delete(id);
  await loadTrashList();
  if (typeof loadStats === 'function') loadStats();
  if (typeof loadExperiments === 'function') loadExperiments();
}

async function trashBulkRestore() {
  if (!_trashSelected.size) return;
  const ids = [..._trashSelected];
  const r = await postApi('/api/bulk-restore', { ids });
  if (!r.ok) { alert(r.error || 'Failed'); return; }
  _trashSelected.clear();
  await loadTrashList();
  if (typeof loadStats === 'function') loadStats();
  if (typeof loadExperiments === 'function') loadExperiments();
}

async function trashPermanent(id, name) {
  let preview;
  try {
    preview = await api('/api/experiment/' + encodeURIComponent(id) + '/delete-preview');
  } catch (e) { alert('Preview failed: ' + e); return; }
  if (preview && preview.error) { alert(preview.error); return; }
  _closeDeleteModal();
  // Render a permanent-only confirm (no Trash tab, since it's already trashed)
  _renderPermanentOnlyModal({
    title: 'Permanently delete: ' + (name || 'experiment'),
    scopeHtml:
      '<div class="dc-subject">' +
        '<span class="dc-subject-name">' + esc(name || '(unnamed)') + '</span>' +
        '<span class="dc-subject-id">' + esc(id.slice(0, 8)) + '</span>' +
      '</div>' +
      _scopeGridHtml(preview),
    onPermanent: async (deleteFiles) => {
      const r = await postApi('/api/experiment/' + encodeURIComponent(id) + '/delete-permanent',
        { delete_files: !!deleteFiles });
      if (!r.ok) { alert(r.error || 'Failed'); return; }
      _closeDeleteModal();
      _trashSelected.delete(id);
      await loadTrashList();
      if (typeof loadStats === 'function') loadStats();
      if (typeof loadExperiments === 'function') loadExperiments();
    },
  });
}

async function trashBulkPermanent() {
  if (!_trashSelected.size) return;
  const ids = [..._trashSelected];
  let preview;
  try {
    preview = await postApi('/api/bulk-delete-preview', { ids });
  } catch (e) { alert('Preview failed: ' + e); return; }
  if (preview && preview.error) { alert(preview.error); return; }
  const t = preview.totals || {};
  const items = preview.items || [];
  const itemRows = items.slice(0, 50).map(it =>
    '<div class="dc-bulk-item">' +
      '<div class="dc-bulk-name">' + esc(it.name || it.id) + '</div>' +
      '<div class="dc-bulk-meta">' + it.artifacts + ' art' +
        (it.artifact_bytes ? ' · ' + _fmtBytes(it.artifact_bytes) : '') +
      '</div>' +
    '</div>').join('');
  const moreNote = items.length > 50 ?
    '<div style="padding:4px 8px;color:var(--muted);font-size:11px">… ' + (items.length - 50) + ' more</div>' : '';
  _renderPermanentOnlyModal({
    title: 'Permanently delete ' + ids.length + ' experiment' + (ids.length === 1 ? '' : 's'),
    scopeHtml: _scopeGridHtmlBulk(t) + '<div class="dc-bulk-list" style="margin-top:8px">' + itemRows + moreNote + '</div>',
    onPermanent: async (deleteFiles) => {
      const r = await postApi('/api/bulk-delete-permanent', { ids, delete_files: !!deleteFiles });
      if (!r.ok) { alert(r.error || 'Failed'); return; }
      _closeDeleteModal();
      _trashSelected.clear();
      await loadTrashList();
      if (typeof loadStats === 'function') loadStats();
      if (typeof loadExperiments === 'function') loadExperiments();
    },
  });
}

function _scopeGridHtml(p) {
  return '<div class="dc-scope-grid">' +
      '<div class="dc-scope-key">Metrics</div><div class="dc-scope-val">' + p.metrics_count + '</div>' +
      '<div class="dc-scope-key">Params</div><div class="dc-scope-val">' + p.params_count + '</div>' +
      '<div class="dc-scope-key">Artifacts</div><div class="dc-scope-val">' + p.artifacts_count +
        ' (' + p.artifacts_existing + ' on disk, ' + _fmtBytes(p.artifact_bytes) + ')</div>' +
      '<div class="dc-scope-key">Output dir</div><div class="dc-scope-val">' +
        (p.output_dir ? esc(p.output_dir) +
          (p.output_dir_exists ? ' <span style="color:var(--muted)">(' + p.output_dir_files +
            ' files, ' + _fmtBytes(p.output_dir_bytes) + ')</span>' : ' <span style="color:var(--muted)">(missing)</span>')
          : '<span style="color:var(--muted)">none</span>') +
      '</div>' +
      '<div class="dc-scope-key">Notebook history</div><div class="dc-scope-val">' +
        p.notebook_history_count + '</div>' +
    '</div>';
}

function _scopeGridHtmlBulk(t) {
  return '<div class="dc-scope-grid">' +
      '<div class="dc-scope-key">Experiments</div><div class="dc-scope-val">' + (t.experiments || 0) + '</div>' +
      '<div class="dc-scope-key">Metrics</div><div class="dc-scope-val">' + (t.metrics || 0) + '</div>' +
      '<div class="dc-scope-key">Params</div><div class="dc-scope-val">' + (t.params || 0) + '</div>' +
      '<div class="dc-scope-key">Artifacts</div><div class="dc-scope-val">' + (t.artifacts || 0) +
        ' (' + (t.artifacts_existing || 0) + ' on disk, ' + _fmtBytes(t.artifact_bytes || 0) + ')</div>' +
      '<div class="dc-scope-key">Output dirs</div><div class="dc-scope-val">' + (t.output_dirs_existing || 0) +
        ' (' + (t.output_dir_files || 0) + ' files, ' + _fmtBytes(t.output_dir_bytes || 0) + ')</div>' +
      '<div class="dc-scope-key">Notebook history</div><div class="dc-scope-val">' + (t.notebook_history || 0) + '</div>' +
    '</div>';
}

function _renderPermanentOnlyModal(opts) {
  _closeDeleteModal();
  const overlay = document.createElement('div');
  overlay.className = 'dc-overlay';
  overlay.id = 'dc-overlay';
  overlay.addEventListener('click', (ev) => { if (ev.target === overlay) _closeDeleteModal(); });
  overlay.innerHTML =
    '<div class="dc-dialog">' +
      '<div class="dc-header">' +
        '<h3>' + esc(opts.title) + '</h3>' +
        '<button class="dc-close" onclick="_closeDeleteModal()">&times;</button>' +
      '</div>' +
      '<div class="dc-body">' +
        opts.scopeHtml +
        '<div class="dc-warning"><b>Permanent delete:</b> removes the DB record (cannot be undone). Files on disk are preserved unless the checkbox below is checked — in which case they go to your system Trash, not <code>rm -rf</code>.</div>' +
      '</div>' +
      '<div class="dc-footer">' +
        '<div class="dc-footer-left">' +
          '<label class="dc-files-checkbox">' +
            '<input type="checkbox" id="dc-files-checkbox">' +
            '<span class="dc-files-checkbox-label">Also move files to system Trash' +
              '<span class="dc-files-checkbox-hint">artifact files and the output directory go to your OS Trash (recoverable in Finder/Files), with a <code>.exptrack/trash/</code> fallback if the OS call fails</span>' +
            '</span>' +
          '</label>' +
        '</div>' +
        '<div class="dc-footer-right">' +
          '<button class="dc-button" onclick="_closeDeleteModal()">Cancel</button>' +
          '<button class="dc-button danger" id="dc-btn-perm-only">Permanently delete</button>' +
        '</div>' +
      '</div>' +
    '</div>';
  document.body.appendChild(overlay);
  document.addEventListener('keydown', _deleteModalEsc);
  document.getElementById('dc-btn-perm-only').addEventListener('click', () => {
    const cb = document.getElementById('dc-files-checkbox');
    opts.onPermanent(cb && cb.checked);
  });
}

// ── Trash count refresh (Settings panel button) ─────────────────────────────
async function _refreshTrashCount() {
  try {
    const stats = await api('/api/stats');
    const btn = document.getElementById('trash-toggle-btn');
    if (!btn) return;
    const n = (stats && (stats.trashed_total != null ? stats.trashed_total : stats.trashed)) || 0;
    if (n > 0) {
      btn.classList.add('has-items');
      btn.innerHTML = '\u{1F5D1} Open Trash <span class="trash-btn-count">' + n + '</span>';
    } else {
      btn.classList.remove('has-items');
      btn.innerHTML = '\u{1F5D1} Open Trash';
    }
  } catch (e) { /* ignore */ }
}

if (typeof window !== 'undefined' && !window._trashBootBound) {
  window._trashBootBound = true;
  window.addEventListener('DOMContentLoaded', () => { setTimeout(_refreshTrashCount, 400); });
  // Also refresh the badge whenever the Settings panel opens — that's where
  // the Trash button lives, and the count would otherwise be stale.
  document.addEventListener('click', (ev) => {
    const t = ev.target;
    if (t && (t.classList.contains('settings-btn') ||
              (t.closest && t.closest('.settings-btn')))) {
      setTimeout(_refreshTrashCount, 50);
    }
  });
}
"""
