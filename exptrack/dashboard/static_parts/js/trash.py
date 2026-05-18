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

// ── Trash view ──────────────────────────────────────────────────────────────
let _trashCache = [];
let _trashSelected = new Set();

function toggleTrashView() {
  if (document.body.classList.contains('trash-active')) {
    closeTrashView();
  } else {
    openTrashView();
  }
}

function openTrashView() {
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
  const welcome = document.getElementById('welcome-state');
  if (tv) tv.style.display = 'none';
  if (welcome) welcome.style.display = '';
}

async function loadTrashList() {
  const container = document.getElementById('trash-view');
  if (!container) return;
  let rows;
  try {
    rows = await api('/api/trash');
  } catch (e) {
    container.innerHTML = '<div class="trash-empty">Could not load Trash: ' + esc(String(e)) + '</div>';
    return;
  }
  _trashCache = Array.isArray(rows) ? rows : [];
  _trashSelected = new Set([..._trashSelected].filter(id => _trashCache.find(r => r.id === id)));
  _renderTrashView();
  _refreshTrashCount();
}

function _renderTrashView() {
  const container = document.getElementById('trash-view');
  if (!container) return;
  const rows = _trashCache;
  let html = '<div class="trash-header">' +
    '<h2>Trash <span style="color:var(--muted);font-weight:400;font-size:14px">(' + rows.length + ')</span></h2>' +
    '<div class="trash-actions">' +
      (rows.length ? '<button class="dc-button" onclick="_trashSelectAll(this)">' +
        (_trashSelected.size === rows.length ? 'Deselect all' : 'Select all') + '</button>' : '') +
      (_trashSelected.size ? '<button class="dc-button primary" onclick="trashBulkRestore()">Restore (' + _trashSelected.size + ')</button>' : '') +
      (_trashSelected.size ? '<button class="dc-button danger" onclick="trashBulkPermanent()">Permanently delete (' + _trashSelected.size + ')</button>' : '') +
      '<button class="dc-button" onclick="closeTrashView()">Close</button>' +
    '</div>' +
  '</div>' +
  '<p class="trash-blurb">Soft-deleted experiments live here. They are hidden from the dashboard and stats, ' +
    'but their database rows and files are untouched. Restore them, or use <b>Permanently delete</b> to remove the DB record. ' +
    'A checkbox in the permanent-delete confirm lets you also remove files on disk.</p>';

  if (!rows.length) {
    html += '<div class="trash-empty">Trash is empty.</div>';
    container.innerHTML = html;
    return;
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
  html += '</tbody></table>';
  container.innerHTML = html;
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
  if (_trashSelected.size === _trashCache.length) _trashSelected.clear();
  else _trashSelected = new Set(_trashCache.map(r => r.id));
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
    const n = (stats && stats.trashed) || 0;
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
