

// ── Sidebar ──────────────────────────────────────────────────────────────────
// Honour the collapsed/open state toggleSidebar() persists. Without this the
// write was dead: the sidebar always booted collapsed regardless of how the
// user last left it. Absent/unknown value keeps the collapsed default.
function restoreSidebarState() {
  const sb = document.getElementById('exp-sidebar');
  if (!sb) return;
  sb.classList.toggle('collapsed', localStorage.getItem('exptrack-sidebar') !== 'open');
}

function toggleSidebar() {
  const sb = document.getElementById('exp-sidebar');
  sb.classList.toggle('collapsed');
  localStorage.setItem('exptrack-sidebar', sb.classList.contains('collapsed') ? 'collapsed' : 'open');
  const countEl = document.getElementById('sidebar-count');
  if (countEl) countEl.textContent = allExperiments.length + ' experiments';
}

function renderStatusChips() {
  const el = document.getElementById('status-chips');
  if (!el) return;
  const chips = [
    {label: 'All', val: ''},
    {label: 'Done', val: 'done'},
    {label: 'Failed', val: 'failed'},
    {label: 'Running', val: 'running'}
  ];
  el.innerHTML = chips.map(c =>
    '<button class="' + (currentFilter===c.val?'active':'') + '" onclick="filterExps(\'' + c.val + '\')">' + c.label + '</button>'
  ).join('');
}

function _renderExpCard(e) {
  const active = currentDetailId === e.id ? ' active' : '';
  const statusCls = 'status-' + e.status;
  const isSelected = selectedIds.has(e.id);
  const cbHtml = '<label style="display:inline-flex;align-items:center;cursor:pointer;padding:2px" onclick="event.stopPropagation()"><input type="checkbox" class="exp-card-cb" ' + (isSelected?'checked':'') +
    ' onclick="toggleSelection(\'' + e.id + '\')" title="Select"></label>';
  const tagsHtml = (e.tags||[]).length ? '<div class="exp-card-tags">' + (e.tags||[]).map(t=>'<span class="tag">#'+esc(t)+'</span>').join('') + '</div>' : '';
  const cardStudiesHtml = (e.studies||[]).length ? '<div class="exp-card-tags">' + (e.studies||[]).map(g=>'<span class="tag" style="background:rgba(44,90,160,0.1);color:var(--blue)">'+esc(g)+'</span>').join('') + '</div>' : '';
  const cardHl = getHighlightStudy(e);
  const cardHlStyle = cardHl ? ' style="border-left:3px solid ' + cardHl.border + ';background:' + cardHl.bg + '"' : '';
  return '<div class="exp-card' + active + '"' + cardHlStyle + ' onclick="showDetail(\'' + e.id + '\')">' +
    '<div class="exp-card-row1">' + cbHtml +
    '<span class="status-dot ' + statusCls + '"></span>' +
    (e.name_is_auto ? '<span class="auto-name-badge" title="Auto-generated name — double-click to rename">auto</span>' : '') +
    '<span class="exp-card-name" data-rename-slot="' + e.id + '" onclick="event.stopPropagation();onRowClick(\'' + e.id + '\')" ondblclick="event.stopPropagation();cancelRowClick();startInlineRename(\'' + e.id + '\',this)">' + esc(e.name) + '</span></div>' +
    '<div class="exp-card-meta">' +
      esc(e.git_branch || '') + ' &middot; ' + fmtDur(e.duration_s) + ' &middot; ' + fmtDt(e.created_at) +
    '</div>' +
    tagsHtml + cardStudiesHtml +
  '</div>';
}

// One descriptor per sidebar grouping mode, in menu order — the *view-specific*
// half only: the button's icon and tooltip, the menu label, and this mode's own
// collapse state. How a run is keyed and labelled comes from the shared
// GROUP_MODES table in core.js, so the rail and the main table can never key or
// name the same group differently.
//
// `set` is a function, not the Set itself: these are module-level `let`s in
// core.js, and capturing the value at load time would freeze this table against
// whatever the sets are replaced with later. Each mode gets its own set so
// collapsing a date cannot silently collapse a study of the same name.
const SIDEBAR_GROUP_MODES = [
  { id: '', icon: '☷', title: 'Group runs', menuLabel: 'None' },
  { id: 'study', icon: '☷', title: 'Grouped by study', menuLabel: 'Study',
    storageKey: 'exptrack-expanded-studies', set: () => expandedStudyGroups },
  { id: 'script', icon: '\u{1F4C4}', title: 'Grouped by script', menuLabel: 'Script',
    storageKey: 'exptrack-expanded-scripts', set: () => expandedScriptGroups },
  { id: 'day', icon: '\u{1F4C5}', title: 'Grouped by day', menuLabel: 'Day',
    storageKey: 'exptrack-expanded-days', set: () => expandedDayGroups },
  { id: 'git_branch', icon: '⑂', title: 'Grouped by git branch', menuLabel: 'Git branch',
    storageKey: 'exptrack-expanded-branches', set: () => expandedBranchGroups },
];

function _sidebarGroupMode(mode) {
  return SIDEBAR_GROUP_MODES.find(m => m.id === mode) || SIDEBAR_GROUP_MODES[0];
}

function renderExpList() {
  // Scoped to the list this render owns — see renderExperiments().
  const restoreRename = _preserveActiveRename('exp-list');
  const list = document.getElementById('exp-list');
  if (!list) { restoreRename(); return; }
  const filtered = getFilteredExperiments();

  const mode = _sidebarGroupMode(sidebarGroupBy);
  const btn = document.getElementById('sidebar-group-btn');
  if (btn) {
    btn.classList.toggle('active', !!sidebarGroupBy);
    btn.title = mode.title;
    btn.textContent = mode.icon;
  }

  const moreBtn = expHasMore
    ? '<button class="btn-secondary exp-loadmore-btn" onclick="loadMoreExperiments()">Load more</button>'
    : '';

  if (!sidebarGroupBy) {
    list.innerHTML = filtered.map(_renderExpCard).join('') + moreBtn;
  } else {
    const expandedSet = mode.set();
    const groups = new Map();
    for (const e of filtered) {
      const key = GROUP_MODES[mode.id].keyOf(e);
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(e);
    }
    let html = '';
    for (const [key, items] of groups) {
      const isCollapsed = !expandedSet.has(key);
      const arrow = isCollapsed ? '▶' : '▼';
      const label = groupLabelHtml(mode.id, key, items);
      html += '<div class="sidebar-study-header' + (isCollapsed ? ' collapsed' : '') + '" onclick="toggleStudyGroup(\'' + escJsAttr(key) + '\')">' +
        '<span class="sidebar-study-toggle">' + arrow + '</span>' +
        '<span class="sidebar-study-name">' + label + '</span>' +
        '<span class="sidebar-study-count">' + items.length + '</span>' +
      '</div>';
      if (!isCollapsed) {
        html += items.map(_renderExpCard).join('');
      }
    }
    list.innerHTML = html + moreBtn;
  }

  // Update sidebar count
  const countEl = document.getElementById('sidebar-count');
  if (countEl) countEl.textContent = filtered.length + ' exp';

  // Render sidebar actions bar
  renderSidebarActionsBar();
  restoreRename();
}

// The button opens a menu rather than cycling. With two modes a cycle was
// fine; with five, reaching "Git branch" from "Study" meant clicking blind
// through three groupings you did not want, each one re-rendering the list.
function toggleSidebarGroupMenu() {
  const menu = document.getElementById('sidebar-group-menu');
  if (!menu) return;
  if (menu.style.display !== 'none') { closeSidebarGroupMenu(); return; }
  menu.innerHTML = SIDEBAR_GROUP_MODES.map(m =>
    '<div class="sgm-item' + (m.id === sidebarGroupBy ? ' active' : '') + '"' +
    ' onclick="setSidebarGroupBy(\'' + escJsAttr(m.id) + '\')">' +
    '<span class="sgm-icon">' + m.icon + '</span>' +
    '<span>' + esc(m.menuLabel || 'None') + '</span></div>').join('');
  menu.style.display = 'block';
  _dismissOnOutsideClick(menu, '#sidebar-group-btn', closeSidebarGroupMenu);
}

function closeSidebarGroupMenu() {
  const menu = document.getElementById('sidebar-group-menu');
  if (menu) menu.style.display = 'none';
}

function setSidebarGroupBy(mode) {
  sidebarGroupBy = mode;
  localStorage.setItem('exptrack-sidebar-group-by', sidebarGroupBy);
  closeSidebarGroupMenu();
  renderExpList();
}

function toggleStudyGroup(key) {
  const mode = _sidebarGroupMode(sidebarGroupBy);
  if (!mode.set) return;   // ungrouped: there are no headers to click
  const expandedSet = mode.set();
  if (expandedSet.has(key)) expandedSet.delete(key);
  else expandedSet.add(key);
  localStorage.setItem(mode.storageKey, JSON.stringify([...expandedSet]));
  renderExpList();
}

function renderSidebarActionsBar() {
  const bar = document.getElementById('sidebar-actions-bar');
  if (!bar) return;
  const n = selectedIds.size;
  if (n === 0) {
    bar.innerHTML = '';
    return;
  }
  let html = '<div class="sidebar-actions-bar">';
  html += '<button class="export-btn" onclick="deselectAll()" style="font-weight:500">&times; Deselect All</button>';
  html += '<div class="action-count">' + n + ' selected</div>';
  if (n >= 2) {
    html += '<button class="primary" onclick="compareSelected()">Compare (' + n + ')</button>';
  } else if (n === 1) {
    html += '<button class="primary" style="opacity:0.5" disabled title="Select 2+ to compare">Compare (need 2+)</button>';
  }
  html += '<button class="export-btn" onclick="promptBulkAddToStudy()">Add to Study</button>';
  html += _buildExportDropdown(n);
  html += _buildCopyDropdown(n);
  html += '<button onclick="bulkCompact()">Compact</button>';
  html += '<button class="danger" onclick="sidebarBulkDelete()">Delete (' + n + ')</button>';
  html += '</div>';
  bar.innerHTML = html;
}

// ── View switching ───────────────────────────────────────────────────────────
function showWelcome() {
  currentDetailId = '';
  stopAutoRefresh();
  // Make sure the Sessions tab isn't holding the canvas
  if (typeof closeSessionsTab === 'function') closeSessionsTab();
  if (typeof closeTrashView === 'function') closeTrashView();
  document.getElementById('welcome-state').style.display = '';
  document.getElementById('detail-view').style.display = 'none';
  document.getElementById('compare-view').style.display = 'none';
  document.getElementById('exp-sidebar').classList.add('collapsed');
  renderExpList();
  if (allExperiments.length === 0) owlSpeak('empty');
}

function showCompareView() {
  stopAutoRefresh();
  document.getElementById('welcome-state').style.display = 'none';
  document.getElementById('detail-view').style.display = 'none';
  document.getElementById('compare-view').style.display = '';
  populateCompareDropdowns();
}

function showDetailView() {
  // The Sessions tab overlays the canvas and hides #detail-view with
  // `display:none !important` while body.sessions-active is set, so a node's
  // "→ exp" badge would fetch the experiment but never show it. Drop the
  // overlay first (mirrors showWelcome) so exp navigation actually lands.
  if (typeof closeSessionsTab === 'function') closeSessionsTab();
  document.getElementById('welcome-state').style.display = 'none';
  document.getElementById('detail-view').style.display = '';
  document.getElementById('compare-view').style.display = 'none';
}

// ── Unified selection ─────────────────────────────────────────────────────────
function toggleSelection(id) {
  if (selectedIds.has(id)) selectedIds.delete(id);
  else selectedIds.add(id);
  renderExpList();
  renderExperiments();
}

function selectAllVisible() {
  const visibleExps = getFilteredExperiments();
  if (selectedIds.size === visibleExps.length) {
    selectedIds.clear();
  } else {
    visibleExps.forEach(e => selectedIds.add(e.id));
  }
  renderExpList();
  renderExperiments();
}

function deselectAll() {
  selectedIds.clear();
  renderExpList();
  renderExperiments();
}

function toggleHighlightMode(checked) {
  highlightMode = checked;
  localStorage.setItem('exptrack-highlight', highlightMode ? 'true' : 'false');
  if (highlightMode) {
    buildHighlightColors();
  } else {
    highlightColors = {};
  }
  renderHighlightLegend();
  renderExpList();
  renderExperiments();
}

function buildHighlightColors() {
  const palette = [
    'rgba(124,58,237,0.10)', 'rgba(44,90,160,0.10)', 'rgba(45,125,70,0.10)',
    'rgba(212,130,15,0.10)', 'rgba(192,57,43,0.10)', 'rgba(255,193,7,0.10)',
    'rgba(0,150,136,0.10)', 'rgba(233,30,99,0.10)'
  ];
  const borderPalette = [
    '#7c3aed', '#2c5aa0', '#2d7d46', '#d4820f',
    '#c0392b', '#b8860b', '#009688', '#e91e63'
  ];
  highlightColors = {};
  const studies = new Set();
  for (const e of allExperiments) {
    if (e.studies && e.studies.length) {
      e.studies.forEach(g => studies.add(g));
    }
  }
  let i = 0;
  for (const g of [...studies].sort()) {
    highlightColors[g] = { bg: palette[i % palette.length], border: borderPalette[i % borderPalette.length] };
    i++;
  }
}

function getHighlightStudy(e) {
  if (!highlightMode) return null;
  if (e.studies && e.studies.length) {
    const s = e.studies[0];
    return highlightColors[s] || null;
  }
  return null;
}

function renderHighlightLegend() {
  const el = document.getElementById('highlight-legend');
  if (!el) return;
  if (!highlightMode || Object.keys(highlightColors).length === 0) {
    el.innerHTML = '';
    return;
  }
  let html = '';
  for (const [grp, col] of Object.entries(highlightColors)) {
    html += '<span class="highlight-legend-item"><span class="highlight-legend-swatch" style="background:' + col.border + '"></span>' + esc(grp) + '</span>';
  }
  el.innerHTML = html;
}

function syncHighlightCheckbox() {
  const cb = document.getElementById('highlight-toggle');
  if (cb) cb.checked = highlightMode;
}
