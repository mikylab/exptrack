"""State variables, API helpers, dark mode, column settings, and formatting utilities."""

JS_CORE = r"""
// ── Global state variables ──────────────────────────────────────────────────
// These are kept as top-level `let` declarations for backward compatibility
// with the 16+ JS modules that reference them directly.
let currentFilter = '';
let searchQuery = '';
let tagFilter = '';
let studyFilter = '';
let charts = {};
let selectedIds = new Set();
let pinnedIds = new Set(JSON.parse(localStorage.getItem('exptrack-pinned') || '[]'));
let hiddenIds = new Set(JSON.parse(localStorage.getItem('exptrack-hidden') || '[]'));
let allExperiments = [];
let currentDetailId = '';
let sortCol = 'created_at';
let sortDir = 'desc';
let groupBy = 'git_commit';
let collapsedGroups = new Set();
let clickTimer = null;
let currentTimezone = localStorage.getItem('exptrack-tz') || '';
let allKnownTags = []; // {name, count}[]
let allKnownStudies = []; // {name, count}[]
let highlightMode = localStorage.getItem('exptrack-highlight') === 'true';

// Display abbreviations for common metric names (config stores full names)
const METRIC_ABBREV = {
  accuracy: 'acc', precision: 'prec', recall: 'rec', perplexity: 'ppl',
};
function abbrevMetric(key) {
  // Abbreviate the base name (after last /), keep prefix
  const si = key.lastIndexOf('/');
  const prefix = si > 0 ? key.slice(0, si + 1) : '';
  const base = si > 0 ? key.slice(si + 1) : key;
  return prefix + (METRIC_ABBREV[base] || base);
}
let highlightColors = {}; // study -> color mapping

// Column configuration: id, label, default visibility, sortable, min-width
const ALL_COLUMNS = [
  {id: 'pin', label: '', sortable: false, defaultOn: true, width: 28},
  {id: 'cb', label: '', sortable: false, defaultOn: true, width: 32},
  {id: 'id', label: 'ID', sortable: true, defaultOn: true, width: 50},
  {id: 'name', label: 'Name', sortable: true, defaultOn: true, width: 150},
  {id: 'status', label: 'Status', sortable: true, defaultOn: true, width: 62},
  {id: 'tags', label: 'Tags', sortable: true, defaultOn: true, width: 90},
  {id: 'studies', label: 'Studies', sortable: true, defaultOn: true, width: 90},
  {id: 'stage', label: 'Stage', sortable: true, defaultOn: true, width: 80},
  {id: 'notes', label: 'Notes', sortable: false, defaultOn: true, width: 130},
  {id: 'metrics', label: 'Metrics', sortable: false, defaultOn: true, width: 110},
  {id: 'changes', label: 'Changes', sortable: false, defaultOn: false, width: 80},
  {id: 'started', label: 'Started', sortable: true, defaultOn: true, width: 110},
];
let visibleCols = (function() {
  const saved = JSON.parse(localStorage.getItem('exptrack-cols') || 'null');
  const validIds = new Set(ALL_COLUMNS.map(c => c.id));
  if (!saved) return ALL_COLUMNS.filter(c => c.defaultOn).map(c => c.id);
  // Remove stale column ids, merge in new defaults
  const cleaned = saved.filter(id => validIds.has(id));
  const newDefaults = ALL_COLUMNS.filter(c => c.defaultOn && !cleaned.includes(c.id)).map(c => c.id);
  return newDefaults.length ? [...cleaned, ...newDefaults] : cleaned;
})();
let colWidths = JSON.parse(localStorage.getItem('exptrack-col-widths') || '{}');

// ── Consolidated app state object ───────────────────────────────────────────
// Provides a single namespace for all dashboard state. Each property is backed
// by a getter/setter that delegates to the corresponding top-level variable,
// so existing code that reads/writes the globals continues to work unchanged.
const app = {};
Object.defineProperties(app, {
  currentFilter:   { get() { return currentFilter; },   set(v) { currentFilter = v; } },
  searchQuery:     { get() { return searchQuery; },     set(v) { searchQuery = v; } },
  tagFilter:       { get() { return tagFilter; },       set(v) { tagFilter = v; } },
  studyFilter:     { get() { return studyFilter; },     set(v) { studyFilter = v; } },
  charts:          { get() { return charts; },          set(v) { charts = v; } },
  selectedIds:     { get() { return selectedIds; },     set(v) { selectedIds = v; } },
  pinnedIds:       { get() { return pinnedIds; },       set(v) { pinnedIds = v; } },
  hiddenIds:       { get() { return hiddenIds; },       set(v) { hiddenIds = v; } },
  allExperiments:  { get() { return allExperiments; },  set(v) { allExperiments = v; } },
  currentDetailId: { get() { return currentDetailId; }, set(v) { currentDetailId = v; } },
  sortCol:         { get() { return sortCol; },         set(v) { sortCol = v; } },
  sortDir:         { get() { return sortDir; },         set(v) { sortDir = v; } },
  groupBy:         { get() { return groupBy; },         set(v) { groupBy = v; } },
  collapsedGroups: { get() { return collapsedGroups; }, set(v) { collapsedGroups = v; } },
  clickTimer:      { get() { return clickTimer; },      set(v) { clickTimer = v; } },
  currentTimezone: { get() { return currentTimezone; }, set(v) { currentTimezone = v; } },
  allKnownTags:    { get() { return allKnownTags; },    set(v) { allKnownTags = v; } },
  allKnownStudies: { get() { return allKnownStudies; }, set(v) { allKnownStudies = v; } },
  highlightMode:   { get() { return highlightMode; },   set(v) { highlightMode = v; } },
  highlightColors: { get() { return highlightColors; }, set(v) { highlightColors = v; } },
  visibleCols:     { get() { return visibleCols; },     set(v) { visibleCols = v; } },
  colWidths:       { get() { return colWidths; },       set(v) { colWidths = v; } },
});

// Reset transient state to prevent memory leaks (e.g. stale chart instances,
// collapsed-group sets that grow unbounded across navigation).
function resetAppState() {
  // Destroy any existing chart instances to free canvas/bindigs
  if (charts && typeof charts === 'object') {
    for (const key of Object.keys(charts)) {
      try { if (charts[key] && typeof charts[key].destroy === 'function') charts[key].destroy(); } catch(_) {}
    }
  }
  charts = {};
  collapsedGroups = new Set();
  selectedIds = new Set();
  clickTimer = null;
  currentDetailId = '';
  highlightColors = {};
}

function saveColPrefs() {
  localStorage.setItem('exptrack-cols', JSON.stringify(visibleCols));
  localStorage.setItem('exptrack-col-widths', JSON.stringify(colWidths));
}

function getColWidth(colId) {
  const def = ALL_COLUMNS.find(c => c.id === colId);
  return colWidths[colId] || (def ? def.width : 100);
}

function toggleColumnSettings() {
  const panel = document.getElementById('col-settings-panel');
  if (panel.style.display === 'block') { panel.style.display = 'none'; return; }
  let html = '<div class="col-settings-list">';
  for (const col of ALL_COLUMNS) {
    if (col.id === 'cb') continue; // checkbox always visible
    const checked = visibleCols.includes(col.id) ? 'checked' : '';
    const label = col.label || (col.id === 'pin' ? 'Pin' : col.id);
    html += '<label class="col-setting-item"><input type="checkbox" ' + checked + ' onchange="toggleColumn(\'' + col.id + '\',this.checked)"> ' + label + '</label>';
  }
  html += '</div>';
  html += '<div style="border-top:1px solid var(--border);margin-top:8px;padding-top:8px"><button class="col-reset-btn" onclick="resetColumnDefaults()">Reset to defaults</button></div>';
  panel.innerHTML = html;
  panel.style.display = 'block';
  // close on outside click
  setTimeout(() => {
    function closePanel(ev) { if (!panel.contains(ev.target) && !ev.target.closest('.col-settings-btn')) { panel.style.display = 'none'; document.removeEventListener('click', closePanel); } }
    document.addEventListener('click', closePanel);
  }, 0);
}

function resetColumnDefaults() {
  visibleCols = ALL_COLUMNS.filter(c => c.defaultOn).map(c => c.id);
  colWidths = {};
  saveColPrefs();
  renderTableHeader();
  renderExperiments();
  document.getElementById('col-settings-panel').style.display = 'none';
}

function toggleColumn(colId, on) {
  if (on && !visibleCols.includes(colId)) {
    // Insert in canonical order
    const order = ALL_COLUMNS.map(c => c.id);
    visibleCols.push(colId);
    visibleCols.sort((a,b) => order.indexOf(a) - order.indexOf(b));
  } else if (!on) {
    visibleCols = visibleCols.filter(c => c !== colId);
  }
  saveColPrefs();
  renderTableHeader();
  renderExperiments();
}

function renderTableHeader() {
  const thead = document.getElementById('exp-thead');
  if (!thead) return;
  let html = '<tr>';
  for (const colId of visibleCols) {
    const col = ALL_COLUMNS.find(c => c.id === colId);
    if (!col) continue;
    const w = getColWidth(colId);
    const resizer = '<span class="col-resizer" onmousedown="startColResize(event,\'' + colId + '\')"></span>';
    if (colId === 'cb') {
      html += '<th class="cb-col" style="width:' + w + 'px"><input type="checkbox" onclick="selectAllVisible()" title="Select all"></th>';
    } else if (colId === 'pin') {
      html += '<th style="width:' + w + 'px;position:relative">' + resizer + '</th>';
    } else if (col.sortable) {
      html += '<th class="sortable" style="width:' + w + 'px;position:relative" onclick="toggleSort(\'' + (colId === 'started' ? 'created_at' : colId) + '\')">' + col.label + '<span class="sort-arrow"></span>' + resizer + '</th>';
    } else {
      html += '<th style="width:' + w + 'px;position:relative">' + col.label + resizer + '</th>';
    }
  }
  html += '</tr>';
  thead.innerHTML = html;
  updateSortHeaders();
}

// Column resize via drag
let resizeState = null;
function startColResize(ev, colId) {
  ev.preventDefault();
  ev.stopPropagation();
  const th = ev.target.closest('th');
  const startX = ev.clientX;
  const startW = th.offsetWidth;
  resizeState = {colId, th, startX, startW};
  document.addEventListener('mousemove', doColResize);
  document.addEventListener('mouseup', endColResize);
  document.body.style.cursor = 'col-resize';
  document.body.style.userSelect = 'none';
}
function doColResize(ev) {
  if (!resizeState) return;
  const newW = Math.max(40, resizeState.startW + ev.clientX - resizeState.startX);
  resizeState.th.style.width = newW + 'px';
}
function endColResize(ev) {
  if (!resizeState) return;
  const newW = Math.max(40, resizeState.startW + ev.clientX - resizeState.startX);
  colWidths[resizeState.colId] = newW;
  saveColPrefs();
  resizeState = null;
  document.removeEventListener('mousemove', doColResize);
  document.removeEventListener('mouseup', endColResize);
  document.body.style.cursor = '';
  document.body.style.userSelect = '';
  renderTableHeader();
  renderExperiments();
}

// Dark mode
function toggleTheme() {
  document.body.classList.toggle('dark');
  const isDark = document.body.classList.contains('dark');
  localStorage.setItem('exptrack-theme', isDark ? 'dark' : 'light');
  document.getElementById('theme-toggle').innerHTML = isDark ? '&#9788;' : '&#9790;';
}
if (localStorage.getItem('exptrack-theme') === 'dark') {
  document.body.classList.add('dark');
  document.getElementById('theme-toggle').innerHTML = '&#9788;';
}

function togglePin(id) {
  if (pinnedIds.has(id)) pinnedIds.delete(id);
  else pinnedIds.add(id);
  localStorage.setItem('exptrack-pinned', JSON.stringify([...pinnedIds]));
  renderExperiments();
}

function hideSelected() {
  for (const id of selectedIds) hiddenIds.add(id);
  selectedIds.clear();
  localStorage.setItem('exptrack-hidden', JSON.stringify([...hiddenIds]));
  renderExperiments();
  renderExpList();
  renderHiddenPanel();
}

function unhideRow(id) {
  hiddenIds.delete(id);
  localStorage.setItem('exptrack-hidden', JSON.stringify([...hiddenIds]));
  renderExperiments();
  renderExpList();
  renderHiddenPanel();
}

function unhideAll() {
  hiddenIds.clear();
  localStorage.setItem('exptrack-hidden', '[]');
  renderExperiments();
  renderExpList();
  renderHiddenPanel();
}

let hiddenPanelOpen = false;

function toggleHiddenPanel() {
  hiddenPanelOpen = !hiddenPanelOpen;
  renderHiddenPanel();
}

function renderHiddenPanel() {
  let panel = document.getElementById('hidden-panel');
  if (!panel) {
    const tableWrap = document.querySelector('.table-scroll-wrap');
    if (!tableWrap) return;
    panel = document.createElement('div');
    panel.id = 'hidden-panel';
    panel.className = 'hidden-panel';
    tableWrap.parentNode.insertBefore(panel, tableWrap.nextSibling);
  }
  if (hiddenIds.size === 0) { panel.style.display = 'none'; return; }
  panel.style.display = 'block';
  const hiddenExps = allExperiments.filter(e => hiddenIds.has(e.id));
  let html = '<div class="hidden-panel-header" onclick="toggleHiddenPanel()">';
  html += '<span class="hidden-panel-toggle">' + (hiddenPanelOpen ? '\u25BC' : '\u25B6') + '</span> ';
  html += hiddenIds.size + ' hidden row' + (hiddenIds.size > 1 ? 's' : '');
  html += '<button class="hidden-panel-clear" onclick="event.stopPropagation();unhideAll()">Unhide all</button>';
  html += '</div>';
  if (hiddenPanelOpen) {
    html += '<div class="hidden-panel-list">';
    for (const e of hiddenExps) {
      html += '<div class="hidden-panel-item">';
      html += '<span class="hidden-panel-name" title="' + esc(e.id) + '">' + esc(e.name.slice(0, 40)) + '</span>';
      html += '<span class="hidden-panel-status status-' + e.status + '">' + e.status + '</span>';
      html += '<button class="hidden-panel-unhide" onclick="unhideRow(\'' + e.id + '\')" title="Unhide">Unhide</button>';
      html += '</div>';
    }
    html += '</div>';
  }
  panel.innerHTML = html;
}

function renderFilterBar() {
  const bar = document.getElementById('filter-bar');
  if (!bar) return;
  const allTags = new Set();
  const allStudies = new Set();
  allExperiments.forEach(e => {
    (e.tags||[]).forEach(t => allTags.add(t));
    (e.studies||[]).forEach(g => allStudies.add(g));
  });
  if (allTags.size === 0 && allStudies.size === 0) { bar.innerHTML = ''; return; }
  const hasFilter = tagFilter || studyFilter;
  let html = '';
  // Active filter chip
  if (tagFilter) {
    html += '<span class="tag-chip active" style="position:relative;padding-right:18px">';
    html += '<span onclick="tagFilter=\'\';rerender()">#' + esc(tagFilter) + '</span>';
    html += '<span class="tag-delete-x" style="opacity:1" onclick="event.stopPropagation();tagFilter=\'\';rerender()" title="Clear filter">&times;</span>';
    html += '</span>';
  } else if (studyFilter) {
    html += '<span class="tag-chip active" style="position:relative;padding-right:18px">';
    html += '<span onclick="studyFilter=\'\';rerender()">' + esc(studyFilter) + '</span>';
    html += '<span class="tag-delete-x" style="opacity:1" onclick="event.stopPropagation();studyFilter=\'\';rerender()" title="Clear filter">&times;</span>';
    html += '</span>';
  }
  // Searchable dropdown
  html += '<div class="filter-dropdown-wrap">';
  html += '<input type="text" class="filter-search-input" id="filter-search-input" placeholder="' + (hasFilter ? 'Change filter...' : 'Filter by tag/study...') + '" oninput="renderFilterDropdown()" onfocus="renderFilterDropdown()" autocomplete="off">';
  html += '<div class="filter-dropdown-list" id="filter-dropdown-list" style="display:none"></div>';
  html += '</div>';
  if (hasFilter) {
    html += '<span class="tag-chip" style="cursor:pointer" onclick="tagFilter=\'\';studyFilter=\'\';rerender()">&times; Clear</span>';
  }
  bar.innerHTML = html;
  // Close dropdown on outside click
  const input = document.getElementById('filter-search-input');
  if (input) {
    input.addEventListener('blur', () => { setTimeout(() => { const dd = document.getElementById('filter-dropdown-list'); if (dd) dd.style.display = 'none'; }, 150); });
    input.addEventListener('keydown', (ev) => {
      const dd = document.getElementById('filter-dropdown-list');
      if (!dd) return;
      const items = dd.querySelectorAll('.filter-dropdown-item');
      let activeIdx = -1;
      items.forEach((el, i) => { if (el.classList.contains('active')) activeIdx = i; });
      if (ev.key === 'ArrowDown') { ev.preventDefault(); activeIdx = Math.min(activeIdx + 1, items.length - 1); items.forEach((el, i) => el.classList.toggle('active', i === activeIdx)); }
      else if (ev.key === 'ArrowUp') { ev.preventDefault(); activeIdx = Math.max(activeIdx - 1, 0); items.forEach((el, i) => el.classList.toggle('active', i === activeIdx)); }
      else if (ev.key === 'Enter') { ev.preventDefault(); if (activeIdx >= 0 && items[activeIdx]) items[activeIdx].click(); }
      else if (ev.key === 'Escape') { dd.style.display = 'none'; input.blur(); }
    });
  }
}

function renderFilterDropdown() {
  const dd = document.getElementById('filter-dropdown-list');
  const input = document.getElementById('filter-search-input');
  if (!dd || !input) return;
  const q = input.value.trim().toLowerCase();
  const allTags = new Set();
  const allStudies = new Set();
  allExperiments.forEach(e => {
    (e.tags||[]).forEach(t => allTags.add(t));
    (e.studies||[]).forEach(g => allStudies.add(g));
  });
  let items = [];
  for (const t of [...allTags].sort()) {
    const count = allExperiments.filter(e => (e.tags||[]).includes(t)).length;
    if (!q || t.toLowerCase().includes(q)) items.push({type: 'tag', name: t, count});
  }
  for (const g of [...allStudies].sort()) {
    const count = allExperiments.filter(e => (e.studies||[]).includes(g)).length;
    if (!q || g.toLowerCase().includes(q)) items.push({type: 'study', name: g, count});
  }
  if (items.length === 0) { dd.innerHTML = '<div style="padding:6px 10px;color:var(--muted);font-size:12px">No matches</div>'; dd.style.display = 'block'; return; }
  dd.innerHTML = items.map(item =>
    '<div class="filter-dropdown-item" data-type="' + item.type + '" data-name="' + esc(item.name) + '" onmousedown="event.preventDefault();applyFilterFromDropdown(\'' + item.type + '\',\'' + esc(item.name) + '\')">' +
    '<span>' + (item.type === 'tag' ? '<span style="color:var(--muted)">#</span>' : '<span style="color:var(--blue)">\u25CF </span>') + esc(item.name) + '</span>' +
    '<span style="color:var(--muted);font-size:11px">' + item.count + '</span>' +
    '</div>'
  ).join('');
  dd.style.display = 'block';
}

function applyFilterFromDropdown(type, name) {
  if (type === 'tag') { tagFilter = name; studyFilter = ''; }
  else { studyFilter = name; tagFilter = ''; }
  rerender();
}

function rerender() { renderExperiments(); renderExpList(); renderFilterBar(); }

async function api(path) {
  const r = await fetch(path);
  return r.json();
}

async function postApi(path, body = {}) {
  const r = await fetch(path, {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body)
  });
  return r.json();
}

async function deleteTagGlobal(tag) {
  const count = allExperiments.filter(e => (e.tags||[]).includes(tag)).length;
  if (!confirm('Remove #' + tag + ' from ' + count + ' experiment(s)? This cannot be undone.')) return;
  const res = await postApi('/api/delete-tag-global', {tag});
  if (res.ok) {
    if (tagFilter === tag) tagFilter = '';
    await loadAllTags();
    await loadExperiments();
    renderManagePanel();
  }
}

function toggleManageDrawer() {
  const drawer = document.getElementById('manage-drawer');
  const overlay = document.getElementById('manage-overlay');
  if (!drawer) return;
  const isOpen = drawer.classList.contains('visible');
  if (isOpen) {
    closeManageDrawer();
  } else {
    drawer.classList.add('visible');
    overlay.classList.add('visible');
    renderManagePanel();
  }
}

function closeManageDrawer() {
  const drawer = document.getElementById('manage-drawer');
  const overlay = document.getElementById('manage-overlay');
  if (drawer) drawer.classList.remove('visible');
  if (overlay) overlay.classList.remove('visible');
}

function renderManagePanel() {
  const panel = document.getElementById('manage-drawer-body');
  if (!panel) return;
  let html = '';

  // Tags section
  html += '<div class="manage-section"><h4>Tags</h4>';
  if (!allKnownTags.length) {
    html += '<div style="color:var(--muted);font-size:12px;padding:4px 0">No tags yet.</div>';
  } else {
    for (const t of allKnownTags) {
      html += '<div class="tag-manager-row">'
        + '<span class="tm-name-edit" ondblclick="startEditGlobalTag(this,\'' + esc(t.name) + '\')">#' + esc(t.name) + ' <span class="tm-count">(' + t.count + ')</span></span>'
        + '<span class="tm-delete" onclick="deleteTagGlobal(\'' + esc(t.name) + '\')" title="Remove from all experiments">&times;</span>'
        + '</div>';
    }
  }
  html += '</div>';

  // Studies section
  html += '<div class="manage-section"><h4>Studies</h4>';
  if (!allKnownStudies.length) {
    html += '<div style="color:var(--muted);font-size:12px;padding:4px 0">No studies yet.</div>';
  } else {
    for (const g of allKnownStudies) {
      html += '<div class="tag-manager-row">'
        + '<span class="tm-name-edit" ondblclick="startEditGlobalStudy(this,\'' + esc(g.name) + '\')">' + esc(g.name) + ' <span class="tm-count">(' + g.count + ')</span></span>'
        + '<span class="tm-delete" onclick="deleteStudyGlobal(\'' + esc(g.name) + '\')" title="Remove from all experiments">&times;</span>'
        + '</div>';
    }
  }
  if (selectedIds.size > 0) {
    html += '<div class="study-create-form" style="margin-top:8px">';
    html += '<input type="text" id="new-study-name" placeholder="New study for ' + selectedIds.size + ' selected...">';
    html += '<button onclick="createStudyFromPanel()">Create</button>';
    html += '</div>';
  }
  html += '</div>';
  panel.innerHTML = html;
}

async function startEditGlobalTag(el, oldName) {
  const input = document.createElement('input');
  input.type = 'text'; input.className = 'name-edit-input';
  input.value = oldName; input.style.cssText = 'width:120px;font-size:12px;padding:2px 4px';
  el.innerHTML = ''; el.appendChild(input); input.focus(); input.select();
  let saved = false;
  async function doSave() {
    if (saved) return; saved = true;
    const newName = input.value.trim();
    if (newName && newName !== oldName) {
      // Rename tag across all experiments
      for (const e of allExperiments) {
        if ((e.tags||[]).includes(oldName)) {
          await postApi('/api/experiment/' + e.id + '/edit-tag', {old_tag: oldName, new_tag: newName});
        }
      }
      await loadAllTags(); await loadExperiments();
    }
    renderManagePanel();
  }
  input.addEventListener('blur', doSave);
  input.addEventListener('keydown', (ev) => {
    if (ev.key === 'Enter') { ev.preventDefault(); input.blur(); }
    if (ev.key === 'Escape') { saved = true; renderManagePanel(); }
  });
}

async function startEditGlobalStudy(el, oldName) {
  const input = document.createElement('input');
  input.type = 'text'; input.className = 'name-edit-input';
  input.value = oldName; input.style.cssText = 'width:120px;font-size:12px;padding:2px 4px';
  el.innerHTML = ''; el.appendChild(input); input.focus(); input.select();
  let saved = false;
  async function doSave() {
    if (saved) return; saved = true;
    const newName = input.value.trim();
    if (newName && newName !== oldName) {
      // Rename: add new, remove old for each experiment
      for (const e of allExperiments) {
        if ((e.studies||[]).includes(oldName)) {
          await postApi('/api/experiment/' + e.id + '/study', {study: newName});
          await postApi('/api/experiment/' + e.id + '/delete-study', {study: oldName});
        }
      }
      if (studyFilter === oldName) studyFilter = newName;
      await loadAllStudies(); await loadExperiments();
    }
    renderManagePanel();
  }
  input.addEventListener('blur', doSave);
  input.addEventListener('keydown', (ev) => {
    if (ev.key === 'Enter') { ev.preventDefault(); input.blur(); }
    if (ev.key === 'Escape') { saved = true; renderManagePanel(); }
  });
}

function fmtDur(s) {
  if (!s) return '--';
  if (s >= 3600) return Math.floor(s/3600) + 'h' + Math.floor((s%3600)/60) + 'm';
  if (s >= 60) return Math.floor(s/60) + 'm' + Math.floor(s%60) + 's';
  return s.toFixed(1) + 's';
}

function fmtTimeAgo(iso) {
  if (!iso) return '--';
  const now = new Date();
  const then = new Date(iso);
  const diff = Math.floor((now - then) / 1000);
  if (diff < 60) return diff + 's ago';
  if (diff < 3600) return Math.floor(diff / 60) + 'm ago';
  if (diff < 86400) return Math.floor(diff / 3600) + 'h ago';
  return Math.floor(diff / 86400) + 'd ago';
}

function fmtDt(iso) {
  if (!iso) return '--';
  const d = new Date(iso.endsWith('Z') || iso.includes('+') ? iso : iso + 'Z');
  if (currentTimezone) {
    try {
      const parts = new Intl.DateTimeFormat('en-US', {
        timeZone: currentTimezone, month: 'numeric', day: 'numeric',
        hour: '2-digit', minute: '2-digit', hour12: false
      }).formatToParts(d);
      const get = type => (parts.find(p => p.type === type) || {}).value || '';
      return get('month') + '/' + get('day') + ' ' + get('hour') + ':' + get('minute');
    } catch(e) {}
  }
  return (d.getMonth()+1) + '/' + d.getDate() + ' ' +
         String(d.getHours()).padStart(2,'0') + ':' + String(d.getMinutes()).padStart(2,'0');
}

function fmtDtFull(iso) {
  if (!iso) return '--';
  const d = new Date(iso.endsWith('Z') || iso.includes('+') ? iso : iso + 'Z');
  const opts = { month: 'short', day: 'numeric', year: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false };
  if (currentTimezone) opts.timeZone = currentTimezone;
  try { return d.toLocaleString('en-US', opts); } catch(e) {}
  return d.toLocaleString();
}

async function setTimezone(tz) {
  currentTimezone = tz;
  localStorage.setItem('exptrack-tz', tz);
  try { await postApi('/api/config/timezone', {timezone: tz}); } catch(e) {}
  renderExperiments();
  renderExpList();
  if (currentDetailId) refreshDetail(currentDetailId);
  owlSay(tz ? 'Timezone set to ' + tz + '!' : 'Using your browser timezone!');
}

async function loadTimezoneConfig() {
  try {
    const data = await api('/api/config/timezone');
    if (data.timezone) {
      currentTimezone = data.timezone;
      localStorage.setItem('exptrack-tz', data.timezone);
    }
  } catch(e) {}
  const sel = document.getElementById('tz-select');
  if (sel) sel.value = currentTimezone;
}

async function loadMetricSettings() {
  try {
    const data = await api('/api/config/metrics');
    _chartsMaxPoints = data.metric_max_points || 500;
    const keepEl = document.getElementById('settings-keep-every');
    const ptsEl = document.getElementById('settings-max-points');
    if (keepEl) keepEl.value = data.metric_keep_every || 1;
    if (ptsEl) ptsEl.value = data.metric_max_points || 500;
  } catch(e) {}
}

async function saveMetricSettings() {
  const keepEl = document.getElementById('settings-keep-every');
  const ptsEl = document.getElementById('settings-max-points');
  const keepEvery = keepEl ? parseInt(keepEl.value, 10) : 1;
  const maxPoints = ptsEl ? parseInt(ptsEl.value, 10) : 500;
  try {
    const res = await postApi('/api/config/metrics', {
      metric_keep_every: keepEvery,
      metric_max_points: maxPoints
    });
    if (res.ok) {
      _chartsMaxPoints = res.metric_max_points;
      owlSay('Metric settings saved!');
    } else {
      alert(res.error || 'Failed to save');
    }
  } catch(e) { alert('Failed to save settings'); }
}

async function loadAllTags() {
  try {
    const data = await api('/api/all-tags');
    allKnownTags = data.tags || [];
  } catch(e) { allKnownTags = []; }
}

async function loadAllStudies() {
  try {
    const data = await api('/api/all-studies');
    allKnownStudies = data.studies || [];
  } catch(e) { allKnownStudies = []; }
}

function toggleHelp() {
  document.getElementById('help-panel').classList.toggle('visible');
}

// ── Settings panel ─────────────────────────────────────────────────────────

function toggleSettingsPanel() {
  const panel = document.getElementById('settings-panel');
  const isOpen = panel.classList.toggle('visible');
  if (isOpen) loadStorageInfo();
}

// Close settings when clicking outside
document.addEventListener('click', function(e) {
  const panel = document.getElementById('settings-panel');
  if (!panel) return;
  const wrap = panel.closest('.settings-wrap');
  if (panel.classList.contains('visible') && !wrap.contains(e.target)) {
    panel.classList.remove('visible');
  }
});

function fmtBytes(b) {
  if (b < 1024) return b + ' B';
  if (b < 1024*1024) return (b/1024).toFixed(1) + ' KB';
  return (b/(1024*1024)).toFixed(1) + ' MB';
}

async function loadStorageInfo() {
  const el = document.getElementById('settings-storage');
  try {
    const res = await postApi('/api/storage-info');
    if (!res.ok) { el.textContent = 'Could not load'; return; }
    el.innerHTML =
      '<div class="storage-row"><span>DB file</span><span class="storage-val">' + fmtBytes(res.db_bytes) + '</span></div>' +
      '<div class="storage-row"><span>WAL file</span><span class="storage-val">' + fmtBytes(res.wal_bytes) + '</span></div>' +
      '<div class="storage-row"><span>Experiments</span><span class="storage-val">' + res.experiments + '</span></div>' +
      '<div class="storage-row"><span>Params</span><span class="storage-val">' + res.params + '</span></div>' +
      '<div class="storage-row"><span>Metrics</span><span class="storage-val">' + res.metrics + '</span></div>' +
      '<div class="storage-row"><span>Artifacts</span><span class="storage-val">' + res.artifacts + '</span></div>' +
      '<div class="storage-row"><span>Timeline</span><span class="storage-val">' + res.timeline + '</span></div>';
  } catch(e) { el.textContent = 'Error loading storage info'; }
}

async function settingsCleanDb() {
  try {
    const res = await postApi('/api/clean-db');
    if (res.error) { alert('Error: ' + res.error); return; }
    if (res.removed === 0) {
      owlSay('Database is clean — no orphans!');
    } else {
      const parts = Object.entries(res.details).map(([t,n]) => t + ': ' + n).join(', ');
      owlSay('Removed ' + res.removed + ' orphaned row(s)');
      loadExperiments();
    }
    loadStorageInfo();
  } catch(e) { alert('Failed: ' + e.message); }
}

async function settingsVacuumDb() {
  try {
    const res = await postApi('/api/vacuum-db');
    if (!res.ok) { alert('Error: ' + (res.error || 'vacuum failed')); return; }
    owlSay('Database vacuumed — WAL cleared!');
    loadStorageInfo();
  } catch(e) { alert('Failed: ' + e.message); }
}

async function settingsResetDb() {
  if (!confirm('DELETE ALL EXPERIMENTS AND DATA?\\n\\nThis cannot be undone!')) return;
  if (!confirm('Are you really sure? This will permanently erase everything.')) return;
  try {
    const res = await postApi('/api/reset-db');
    if (!res.ok) { alert('Error: ' + (res.error || 'reset failed')); return; }
    owlSay('Database reset — ' + res.deleted_experiments + ' experiment(s) removed');
    loadExperiments();
    loadStorageInfo();
    showWelcome();
  } catch(e) { alert('Failed: ' + e.message); }
}

// Legacy alias (in case anything still references it)
async function cleanDatabase() { settingsCleanDb(); }

"""

# Owl mascot phrases and animation
