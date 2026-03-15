"""
exptrack/dashboard/static_parts/scripts.py — All JavaScript

Split from static.py for maintainability.
Each section is a separate constant for easy navigation.
"""

# State variables, API helpers, formatting utilities
JS_CORE = r"""
let currentFilter = '';
let searchQuery = '';
let tagFilter = '';
let groupFilter = '';
let charts = {};
let selectedIds = new Set();
let pinnedIds = new Set(JSON.parse(localStorage.getItem('exptrack-pinned') || '[]'));
let allExperiments = [];
let currentDetailId = '';
let sortCol = 'created_at';
let sortDir = 'desc';
let groupBy = 'git_commit';
let collapsedGroups = new Set();
let clickTimer = null;
let currentTimezone = localStorage.getItem('exptrack-tz') || '';
let allKnownTags = []; // {name, count}[]
let allKnownGroups = []; // {name, count}[]
let highlightMode = false;
let highlightColors = {}; // group -> color mapping

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

function renderFilterBar() {
  const bar = document.getElementById('filter-bar');
  if (!bar) return;
  const allTags = new Set();
  const allGroups = new Set();
  allExperiments.forEach(e => {
    (e.tags||[]).forEach(t => allTags.add(t));
    (e.groups||[]).forEach(g => allGroups.add(g));
  });
  if (allTags.size === 0 && allGroups.size === 0) { bar.innerHTML = ''; return; }
  const hasFilter = tagFilter || groupFilter;
  let html = '<span style="font-size:11px;color:var(--muted);margin-right:4px">Filter:</span>';
  // Active filter chip (always visible)
  if (tagFilter) {
    html += '<span class="tag-chip active" style="position:relative;padding-right:18px">';
    html += '<span onclick="tagFilter=\'\';rerender()">#' + esc(tagFilter) + '</span>';
    html += '<span class="tag-delete-x" style="opacity:1" onclick="event.stopPropagation();tagFilter=\'\';rerender()" title="Clear filter">&times;</span>';
    html += '</span>';
  } else if (groupFilter) {
    html += '<span class="tag-chip group-chip active" style="position:relative;padding-right:18px">';
    html += '<span onclick="groupFilter=\'\';rerender()">' + esc(groupFilter) + '</span>';
    html += '<span class="tag-delete-x" style="opacity:1" onclick="event.stopPropagation();groupFilter=\'\';rerender()" title="Clear filter">&times;</span>';
    html += '</span>';
  }
  // Searchable dropdown trigger
  html += '<div class="filter-dropdown-wrap" style="display:inline-block;position:relative">';
  html += '<input type="text" class="filter-search-input" id="filter-search-input" placeholder="' + (hasFilter ? 'Change filter...' : 'Search tags/groups...') + '" oninput="renderFilterDropdown()" onfocus="renderFilterDropdown()" autocomplete="off">';
  html += '<div class="filter-dropdown-list" id="filter-dropdown-list" style="display:none"></div>';
  html += '</div>';
  if (hasFilter) {
    html += ' <span class="tag-chip" style="cursor:pointer" onclick="tagFilter=\'\';groupFilter=\'\';rerender()">Clear</span>';
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
  const allGroups = new Set();
  allExperiments.forEach(e => {
    (e.tags||[]).forEach(t => allTags.add(t));
    (e.groups||[]).forEach(g => allGroups.add(g));
  });
  let items = [];
  for (const t of [...allTags].sort()) {
    const count = allExperiments.filter(e => (e.tags||[]).includes(t)).length;
    if (!q || t.toLowerCase().includes(q)) items.push({type: 'tag', name: t, count});
  }
  for (const g of [...allGroups].sort()) {
    const count = allExperiments.filter(e => (e.groups||[]).includes(g)).length;
    if (!q || g.toLowerCase().includes(q)) items.push({type: 'group', name: g, count});
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
  if (type === 'tag') { tagFilter = name; groupFilter = ''; }
  else { groupFilter = name; tagFilter = ''; }
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

function toggleManagePanel() {
  const panel = document.getElementById('manage-panel');
  if (!panel) return;
  if (panel.style.display === 'none') {
    panel.style.display = 'block';
    renderManagePanel();
  } else {
    panel.style.display = 'none';
  }
}

function renderManagePanel() {
  const panel = document.getElementById('manage-panel');
  if (!panel || panel.style.display === 'none') return;
  let html = '';

  // Tags section
  html += '<div class="manage-section"><h4>Tags</h4>';
  if (!allKnownTags.length) {
    html += '<div style="color:var(--muted);font-size:12px">No tags yet.</div>';
  } else {
    for (const t of allKnownTags) {
      html += '<div class="tag-manager-row">'
        + '<span class="tm-name-edit" ondblclick="startEditGlobalTag(this,\'' + esc(t.name) + '\')">#' + esc(t.name) + ' <span class="tm-count">(' + t.count + ')</span></span>'
        + '<span class="tm-delete" onclick="deleteTagGlobal(\'' + esc(t.name) + '\')" title="Remove from all experiments">&times;</span>'
        + '</div>';
    }
  }
  html += '</div>';

  // Groups section
  html += '<div class="manage-section"><h4>Groups</h4>';
  if (!allKnownGroups.length) {
    html += '<div style="color:var(--muted);font-size:12px">No groups yet.</div>';
  } else {
    for (const g of allKnownGroups) {
      html += '<div class="tag-manager-row">'
        + '<span class="tm-name-edit" ondblclick="startEditGlobalGroup(this,\'' + esc(g.name) + '\')">' + esc(g.name) + ' <span class="tm-count">(' + g.count + ')</span></span>'
        + '<span class="tm-delete" onclick="deleteGroupGlobal(\'' + esc(g.name) + '\')" title="Remove from all experiments">&times;</span>'
        + '</div>';
    }
  }
  if (selectedIds.size > 0) {
    html += '<div class="group-create-form" style="margin-top:8px">';
    html += '<input type="text" id="new-group-name" placeholder="New group for ' + selectedIds.size + ' selected...">';
    html += '<button onclick="createGroupFromPanel()">Create</button>';
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

async function startEditGlobalGroup(el, oldName) {
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
        if ((e.groups||[]).includes(oldName)) {
          await postApi('/api/experiment/' + e.id + '/group', {group: newName});
          await postApi('/api/experiment/' + e.id + '/delete-group', {group: oldName});
        }
      }
      if (groupFilter === oldName) groupFilter = newName;
      await loadAllGroups(); await loadExperiments();
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

async function loadAllTags() {
  try {
    const data = await api('/api/all-tags');
    allKnownTags = data.tags || [];
  } catch(e) { allKnownTags = []; }
}

async function loadAllGroups() {
  try {
    const data = await api('/api/all-groups');
    allKnownGroups = data.groups || [];
  } catch(e) { allKnownGroups = []; }
}

function toggleHelp() {
  document.getElementById('help-panel').classList.toggle('visible');
}

"""

# Owl mascot phrases and animation
JS_OWL = r"""
// ── Owl mascot ──────────────────────────────────────────────────────────────
const owlPhrases = [
  'Hoo hoo! Track all the things!',
  'Another experiment? Wise choice.',
  'Remember to tag your best runs!',
  'I never forget a metric.',
  'Did you try a lower learning rate?',
  'Diff your code, diff your life.',
  'Compare runs to find the signal.',
  'Notes help future-you understand past-you.',
  'Zero dependencies, infinite wisdom.',
  'Local-first, always.',
  'Reproducibility is a superpower!',
  'Git diff captured. You\'re welcome.',
  'Have you tried turning it off and on again?',
  'Every experiment teaches something!',
  'Science is organized curiosity.',
  'Log it or lose it!',
  'Hyperparameters are just suggestions.',
];
const owlContextPhrases = {
  delete: ['Are you sure? I\'ll miss that one...', 'Cleaning house? Smart owl.', 'Gone but not forgotten... actually, gone.'],
  compare: ['Let\'s see who wins!', 'Side by side, insight arrives.', 'May the best model win!'],
  export: ['Sharing is caring!', 'Data to go!', 'Knowledge wants to be free!'],
  tag: ['Good labeling, wise human!', 'Tags make finding things a hoot!', 'Organized minds run better experiments.'],
  empty: ['No experiments yet? Go run something!', 'An empty lab is full of potential.', 'The best experiment is the next one!'],
  welcome: ['Welcome back! What shall we track today?', 'Hoo! Good to see you!', 'Ready to science? Let\'s go!'],
  rename: ['A good name tells a story.', 'Identity matters!'],
  note: ['Write it down before you forget!', 'Future you will thank present you.'],
  artifact: ['Artifacts secured!', 'Saving your treasures.'],
  filter: ['Narrowing it down? Smart move.', 'Finding the needle in the haystack!'],
  click: ['Hoo?', '*tilts head*', '*blinks curiously*', 'Yes?', '*ruffles feathers*', '*does a little dance*'],
};
let owlSpeechTimer = null;

function owlSay(msg, anim) {
  const el = document.getElementById('owl-speech');
  if (!el) return;
  el.textContent = msg;
  el.classList.add('visible');
  if (owlSpeechTimer) clearTimeout(owlSpeechTimer);
  owlSpeechTimer = setTimeout(() => el.classList.remove('visible'), 3500);
  // Trigger animation
  const mascot = document.querySelector('.owl-mascot');
  if (mascot && anim) {
    mascot.classList.remove('owl-bounce', 'owl-wiggle');
    void mascot.offsetWidth; // force reflow
    mascot.classList.add(anim);
    setTimeout(() => mascot.classList.remove(anim), 600);
  }
}

function owlSpeak(context) {
  const phrases = context && owlContextPhrases[context] ? owlContextPhrases[context] : owlPhrases;
  const anim = context === 'delete' ? 'owl-wiggle' : 'owl-bounce';
  owlSay(phrases[Math.floor(Math.random() * phrases.length)], anim);
}
"""

# Sidebar, view switching, selection
JS_SIDEBAR = r"""

// ── Sidebar ──────────────────────────────────────────────────────────────────
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

function renderExpList() {
  const list = document.getElementById('exp-list');
  if (!list) return;
  const filtered = getFilteredExperiments();
  list.innerHTML = filtered.map(e => {
    const active = currentDetailId === e.id ? ' active' : '';
    const statusCls = 'status-' + e.status;
    const metrics = Object.entries(e.metrics || {}).slice(0, 2)
      .map(([k,v]) => k.split('/').pop() + '=' + (typeof v === 'number' ? v.toFixed(3) : v)).join('  ');
    const isSelected = selectedIds.has(e.id);
    const cbHtml = '<label style="display:inline-flex;align-items:center;cursor:pointer;padding:2px" onclick="event.stopPropagation()"><input type="checkbox" class="exp-card-cb" ' + (isSelected?'checked':'') +
      ' onclick="toggleSelection(\'' + e.id + '\')" title="Select"></label>';
    const tagsHtml = (e.tags||[]).length ? '<div class="exp-card-tags">' + (e.tags||[]).map(t=>'<span class="tag">#'+esc(t)+'</span>').join('') + '</div>' : '';
    const cardGroupsHtml = (e.groups||[]).length ? '<div class="exp-card-tags">' + (e.groups||[]).map(g=>'<span class="tag" style="background:rgba(44,90,160,0.1);color:var(--blue)">'+esc(g)+'</span>').join('') + '</div>' : '';
    const cardHl = getHighlightGroup(e);
    const cardHlStyle = cardHl ? ' style="border-left:3px solid ' + cardHl.border + ';background:' + cardHl.bg + '"' : '';
    return '<div class="exp-card' + active + '"' + cardHlStyle + ' onclick="showDetail(\'' + e.id + '\')">' +
      '<div class="exp-card-row1">' + cbHtml +
      '<span class="status-dot ' + statusCls + '"></span>' +
      '<span class="exp-card-name" ondblclick="event.stopPropagation();startInlineRename(\'' + e.id + '\',this)">' + esc(e.name) + '</span></div>' +
      '<div class="exp-card-meta">' +
        esc(e.git_branch || '') + ' &middot; ' + fmtDur(e.duration_s) + ' &middot; ' + fmtDt(e.created_at) +
      '</div>' +
      (metrics ? '<div class="exp-card-metrics">' + esc(metrics) + '</div>' : '') +
      tagsHtml + cardGroupsHtml +
    '</div>';
  }).join('');

  // Update sidebar count
  const countEl = document.getElementById('sidebar-count');
  if (countEl) countEl.textContent = filtered.length + ' exp';

  // Render sidebar actions bar
  renderSidebarActionsBar();
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
  if (n === 2) {
    html += '<button class="primary" onclick="compareSelected()">Compare (2)</button>';
  } else if (n === 1) {
    html += '<button class="primary" style="opacity:0.5" disabled title="Select 2 to compare">Compare (need 2)</button>';
  }
  html += '<button class="export-btn" style="color:var(--purple);border-color:var(--purple)' + (highlightMode ? ';background:var(--purple);color:#fff' : '') + '" onclick="toggleHighlightMode()">\u2588 Highlight</button>';
  html += '<button class="export-btn" onclick="promptBulkAddToGroup()">Add to Group</button>';
  html += _buildExportDropdown(n);
  html += _buildCopyDropdown(n);
  html += '<button class="danger" onclick="sidebarBulkDelete()">Delete (' + n + ')</button>';
  html += '</div>';
  bar.innerHTML = html;
}

// ── View switching ───────────────────────────────────────────────────────────
function showWelcome() {
  currentDetailId = '';
  document.getElementById('welcome-state').style.display = '';
  document.getElementById('detail-view').style.display = 'none';
  document.getElementById('compare-view').style.display = 'none';
  document.getElementById('exp-sidebar').classList.add('collapsed');
  renderExpList();
  if (allExperiments.length === 0) owlSpeak('empty');
}

function showCompareView() {
  document.getElementById('welcome-state').style.display = 'none';
  document.getElementById('detail-view').style.display = 'none';
  document.getElementById('compare-view').style.display = '';
  populateCompareDropdowns();
}

function showDetailView() {
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
  highlightMode = false;
  highlightColors = {};
  renderExpList();
  renderExperiments();
}

function toggleHighlightMode() {
  highlightMode = !highlightMode;
  if (highlightMode) {
    buildHighlightColors();
  } else {
    highlightColors = {};
  }
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
  const groups = new Set();
  const selExps = allExperiments.filter(e => selectedIds.has(e.id));
  for (const e of selExps) {
    let grp = '';
    if (groupBy === 'git_commit') grp = e.git_commit ? e.git_commit.slice(0, 7) : 'no commit';
    else if (groupBy === 'git_branch') grp = e.git_branch || 'no branch';
    else if (groupBy === 'status') grp = e.status || 'unknown';
    else grp = (e.groups && e.groups.length) ? e.groups[0] : (e.tags && e.tags.length ? e.tags[0] : 'ungrouped');
    groups.add(grp);
  }
  let i = 0;
  for (const g of groups) {
    highlightColors[g] = { bg: palette[i % palette.length], border: borderPalette[i % borderPalette.length] };
    i++;
  }
}

function getHighlightGroup(e) {
  if (!highlightMode || !selectedIds.has(e.id)) return null;
  let grp = '';
  if (groupBy === 'git_commit') grp = e.git_commit ? e.git_commit.slice(0, 7) : 'no commit';
  else if (groupBy === 'git_branch') grp = e.git_branch || 'no branch';
  else if (groupBy === 'status') grp = e.status || 'unknown';
  else grp = (e.groups && e.groups.length) ? e.groups[0] : (e.tags && e.tags.length ? e.tags[0] : 'ungrouped');
  return highlightColors[grp] || null;
}
"""

# Table actions, bulk operations, sorting, filtering
JS_TABLE = r"""

function _buildExportDropdown(n) {
  let h = '<span style="position:relative;display:inline-block">';
  h += '<button class="export-btn" onclick="this.nextElementSibling.style.display=this.nextElementSibling.style.display===\'block\'?\'none\':\'block\'">Export (' + n + ') \u25BE</button>';
  h += '<div class="export-dropdown-menu" style="display:none">';
  h += '<button class="action-btn" onclick="sidebarExportFmt(\'json\')">JSON</button>';
  h += '<button class="action-btn" onclick="sidebarExportFmt(\'csv\')">CSV</button>';
  h += '<button class="action-btn" onclick="sidebarExportFmt(\'tsv\')">TSV</button>';
  h += '<button class="action-btn" onclick="sidebarExportFmt(\'markdown\')">Markdown</button>';
  h += '<button class="action-btn" onclick="sidebarExportFmt(\'plain\')">Plain Text</button>';
  h += '</div></span>';
  return h;
}

function _buildCopyDropdown(n) {
  let h = '<span style="position:relative;display:inline-block">';
  h += '<button class="export-btn" onclick="this.nextElementSibling.style.display=this.nextElementSibling.style.display===\'block\'?\'none\':\'block\'">Copy (' + n + ') \u25BE</button>';
  h += '<div class="export-dropdown-menu" style="display:none">';
  h += '<button class="action-btn" onclick="sidebarCopyFmt(\'json\')">JSON</button>';
  h += '<button class="action-btn" onclick="sidebarCopyFmt(\'csv\')">CSV</button>';
  h += '<button class="action-btn" onclick="sidebarCopyFmt(\'tsv\')">TSV</button>';
  h += '<button class="action-btn" onclick="sidebarCopyFmt(\'markdown\')">Markdown</button>';
  h += '<button class="action-btn" onclick="sidebarCopyFmt(\'plain\')">Plain Text</button>';
  h += '</div></span>';
  return h;
}

function renderTableActionsBar() {
  const bar = document.getElementById('table-actions-bar');
  if (!bar) return;
  const n = selectedIds.size;
  if (n === 0) {
    bar.style.display = 'none';
    return;
  }
  bar.style.display = 'flex';
  let html = '<button class="deselect-btn" onclick="deselectAll()" title="Deselect all">&times; Deselect All</button>';
  html += '<span class="sel-count">' + n + ' selected</span>';
  if (n === 2) {
    html += '<button class="primary" onclick="compareSelected()">Compare</button>';
  }
  html += '<button class="highlight-btn' + (highlightMode ? ' active' : '') + '" onclick="toggleHighlightMode()" title="Highlight selected by group">\u2588 Highlight</button>';
  html += '<button onclick="promptBulkAddToGroup()">Add to Group</button>';
  html += _buildExportDropdown(n);
  html += _buildCopyDropdown(n);
  html += '<button class="danger" onclick="sidebarBulkDelete()">Delete (' + n + ')</button>';
  if (highlightMode && Object.keys(highlightColors).length > 0) {
    html += '<span style="margin-left:8px;display:inline-flex;gap:6px;align-items:center;font-size:11px;color:var(--muted)">';
    for (const [grp, col] of Object.entries(highlightColors)) {
      html += '<span style="display:inline-flex;align-items:center;gap:3px"><span style="width:10px;height:10px;border-radius:2px;background:' + col.border + ';display:inline-block"></span>' + esc(grp) + '</span>';
    }
    html += '</span>';
  }
  bar.innerHTML = html;
}

async function sidebarBulkDelete() {
  owlSpeak('delete');
  if (!confirm('Delete ' + selectedIds.size + ' experiments? This cannot be undone.')) return;
  const ids = [...selectedIds];
  const d = await postApi('/api/bulk-delete', {ids});
  if (d.ok) {
    selectedIds.clear();
    showWelcome();
    loadStats();
    loadExperiments();
  } else alert(d.error || 'Failed');
}

async function sidebarExportFmt(fmt) {
  owlSpeak('export');
  const ids = [...selectedIds];
  let text;
  if (fmt === 'plain') {
    // Plain text: fetch JSON data and format client-side
    const data = await postApi('/api/bulk-export', {ids, format: 'json'});
    const exps = Array.isArray(data) ? data : [data];
    text = exps.map(d => _formatExpPlainText(d)).join('\n' + '='.repeat(60) + '\n\n');
  } else {
    const data = await postApi('/api/bulk-export', {ids, format: fmt});
    if (data.content) {
      text = data.content;
    } else if (Array.isArray(data)) {
      text = JSON.stringify(data, null, 2);
    } else {
      text = JSON.stringify(data, null, 2);
    }
  }
  const ext = {json:'.json', markdown:'.md', csv:'.csv', tsv:'.tsv', plain:'.txt'};
  const filename = 'exptrack_export_' + ids.length + '_experiments' + (ext[fmt] || '.txt');
  const mime = fmt === 'json' ? 'application/json' : 'text/plain';
  const blob = new Blob([text], {type: mime});
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
  // Close dropdown
  document.querySelectorAll('.export-dropdown-menu').forEach(d => d.style.display = 'none');
  owlSay('Downloaded ' + filename);
}

function _formatExpPlainText(d) {
  // Shared plain-text formatter — same format used by the detail view export
  let lines = [];
  lines.push('Experiment: ' + (d.name || ''));
  lines.push('ID: ' + (d.id || ''));
  lines.push('Status: ' + (d.status || ''));
  if (d.created_at) lines.push('Created: ' + d.created_at);
  if (d.duration_s) lines.push('Duration: ' + fmtDur(d.duration_s));
  if (d.script) lines.push('Script: ' + d.script);
  if (d.command) lines.push('Command: ' + d.command);
  if (d.python_ver) lines.push('Python: ' + d.python_ver);
  if (d.git_branch) lines.push('Branch: ' + d.git_branch);
  if (d.git_commit) lines.push('Commit: ' + d.git_commit);
  if (d.hostname) lines.push('Hostname: ' + d.hostname);
  if (d.tags && d.tags.length) lines.push('Tags: ' + d.tags.join(', '));
  if (d.groups && d.groups.length) lines.push('Groups: ' + d.groups.join(', '));
  if (d.output_dir) lines.push('Output Dir: ' + d.output_dir);
  if (d.notes) lines.push('Notes: ' + d.notes);
  lines.push('');
  const params = d.params || {};
  if (Object.keys(params).length) {
    lines.push('Parameters:');
    Object.entries(params).forEach(([k,v]) => lines.push('  ' + k + ' = ' + JSON.stringify(v)));
    lines.push('');
  }
  const vars = d.variables || {};
  if (Object.keys(vars).length) {
    lines.push('Variables:');
    Object.entries(vars).forEach(([k,v]) => lines.push('  ' + k + ' = ' + JSON.stringify(v)));
    lines.push('');
  }
  const ms = d.metrics_series || {};
  if (Object.keys(ms).length) {
    lines.push('Metrics:');
    Object.entries(ms).forEach(([k,pts]) => {
      const last = pts.length ? pts[pts.length-1].value : '--';
      lines.push('  ' + k + ' = ' + last + ' (' + pts.length + ' steps)');
    });
    lines.push('');
  }
  if (d.artifacts && d.artifacts.length) {
    lines.push('Artifacts:');
    d.artifacts.forEach(a => lines.push('  ' + a.label + ': ' + a.path));
    lines.push('');
  }
  const changes = d.code_changes || {};
  if (Object.keys(changes).length) {
    lines.push('Code Changes:');
    Object.entries(changes).forEach(([k,v]) => lines.push('  ' + k + ': ' + JSON.stringify(v)));
    lines.push('');
  }
  const ts = d.timeline_summary || {};
  if (ts.total_events) {
    lines.push('Timeline: ' + ts.total_events + ' events (' +
      (ts.cell_executions || 0) + ' cells, ' +
      (ts.variable_sets || 0) + ' vars, ' +
      (ts.artifact_events || 0) + ' artifacts)');
  }
  return lines.join('\n');
}

async function sidebarCopyFmt(fmt) {
  const ids = [...selectedIds];
  let text;
  if (fmt === 'plain') {
    const data = await postApi('/api/bulk-export', {ids, format: 'json'});
    const sections = (Array.isArray(data) ? data : []).map(d => _formatExpPlainText(d));
    text = sections.join('\n\n---\n\n');
  } else {
    const data = await postApi('/api/bulk-export', {ids, format: fmt});
    if (data.content) {
      text = data.content;
    } else if (Array.isArray(data)) {
      text = JSON.stringify(data, null, 2);
    } else {
      text = JSON.stringify(data, null, 2);
    }
  }
  await navigator.clipboard.writeText(text);
  document.querySelectorAll('.export-dropdown-menu').forEach(d => d.style.display = 'none');
  owlSay('Copied ' + ids.length + ' experiment(s) as ' + fmt.toUpperCase() + ' to clipboard!');
}

async function sidebarCopyText() {
  sidebarCopyFmt('plain');
}

function setGroup(field) {
  groupBy = field;
  collapsedGroups.clear();
  document.querySelectorAll('#group-bar button').forEach(b => {
    const val = b.getAttribute('data-group');
    b.classList.toggle('active', val === field);
  });
  renderExperiments();
}

function toggleGroup(key) {
  if (collapsedGroups.has(key)) collapsedGroups.delete(key);
  else collapsedGroups.add(key);
  renderExperiments();
}

function toggleSort(col) {
  if (sortCol === col) {
    sortDir = sortDir === 'asc' ? 'desc' : 'asc';
  } else {
    sortCol = col;
    sortDir = (col === 'name' || col === 'status' || col === 'id') ? 'asc' : 'desc';
  }
  renderExperiments();
  updateSortHeaders();
}

function updateSortHeaders() {
  document.querySelectorAll('#exp-table th.sortable').forEach(th => {
    const col = th.getAttribute('onclick').match(/toggleSort\('(\w+)'\)/)?.[1];
    th.classList.toggle('sort-active', col === sortCol);
    const arrow = th.querySelector('.sort-arrow');
    if (arrow) arrow.textContent = col === sortCol ? (sortDir === 'asc' ? '\u25B2' : '\u25BC') : '';
  });
}

function getFilteredExperiments() {
  let exps = allExperiments;
  if (tagFilter) {
    exps = exps.filter(e => (e.tags || []).includes(tagFilter));
  }
  if (groupFilter) {
    exps = exps.filter(e => (e.groups || []).includes(groupFilter));
  }
  if (searchQuery) {
    const q = searchQuery.toLowerCase();
    exps = exps.filter(e =>
      e.name.toLowerCase().includes(q) ||
      e.id.toLowerCase().includes(q) ||
      (e.tags || []).some(t => t.toLowerCase().includes(q)) ||
      (e.groups || []).some(g => g.toLowerCase().includes(q)) ||
      Object.keys(e.params || {}).some(k => k.toLowerCase().includes(q)) ||
      Object.values(e.params || {}).some(v => String(v).toLowerCase().includes(q)) ||
      (e.git_branch || '').toLowerCase().includes(q) ||
      (e.notes || '').toLowerCase().includes(q)
    );
  }
  // Sort: pinned first, then by sort column
  exps = [...exps].sort((a, b) => {
    const ap = pinnedIds.has(a.id) ? 0 : 1;
    const bp = pinnedIds.has(b.id) ? 0 : 1;
    if (ap !== bp) return ap - bp;
    let av, bv;
    switch (sortCol) {
      case 'name': av = a.name.toLowerCase(); bv = b.name.toLowerCase(); break;
      case 'status': av = a.status; bv = b.status; break;
      case 'id': av = a.id; bv = b.id; break;
      case 'tags': av = (a.tags||[]).length; bv = (b.tags||[]).length; break;
      case 'groups': av = (a.groups||[]).length; bv = (b.groups||[]).length; break;
      case 'created_at': default: av = a.created_at||''; bv = b.created_at||''; break;
    }
    let cmp = av < bv ? -1 : av > bv ? 1 : 0;
    return sortDir === 'desc' ? -cmp : cmp;
  });
  return exps;
}
"""

# Stats loading, experiment list, row rendering
JS_EXPERIMENTS = r"""

async function loadStats() {
  const s = await api('/api/stats');
  const statsEl = document.getElementById('stats');
  if (statsEl) {
    const timeAgo = s.most_recent ? fmtTimeAgo(s.most_recent) : '--';
    statsEl.innerHTML = `
      <div class="stats-label">Runs</div>
      <div class="stats-row runs">
        <div class="stat"><div class="num">${s.total}</div><div class="label">Total Runs</div><div class="stat-hint">All experiments tracked in this project</div></div>
        <div class="stat"><div class="num status-done">${s.done}</div><div class="label">Done</div><div class="stat-hint">Completed successfully</div></div>
        <div class="stat"><div class="num status-failed">${s.failed}</div><div class="label">Failed</div><div class="stat-hint">Ended with an error</div></div>
        <div class="stat"><div class="num status-running">${s.running}</div><div class="label">Running</div><div class="stat-hint">Currently in progress</div></div>
      </div>
      <div class="stats-label">Additional Stats</div>
      <div class="stats-row additional">
        <div class="stat"><div class="num">${s.success_rate}%</div><div class="label">Success Rate</div><div class="stat-hint">done / total</div></div>
        <div class="stat"><div class="num">${fmtDur(s.avg_duration_s)}</div><div class="label">Avg Duration</div><div class="stat-hint">Mean run time (completed only)</div></div>
        <div class="stat"><div class="num">${timeAgo}</div><div class="label">Latest Run</div><div class="stat-hint">Time since most recent experiment</div></div>
        <div class="stat"><div class="num">${fmtDur(s.longest_run_s)}</div><div class="label">Longest Run</div><div class="stat-hint">Maximum run duration</div></div>
        <div class="stat"><div class="num">${s.unique_tags}</div><div class="label">Tags</div><div class="stat-hint">Unique tags across all experiments</div></div>
        <div class="stat"><div class="num">${s.total_artifacts}</div><div class="label">Artifacts</div><div class="stat-hint">Total artifacts saved</div></div>
        <div class="stat"><div class="num">${s.unique_branches}</div><div class="label">Branches</div><div class="stat-hint">Unique git branches used</div></div>
      </div>
    `;
  }
  renderStatusChips();
}

async function loadExperiments() {
  const url = currentFilter ? '/api/experiments?status=' + currentFilter : '/api/experiments';
  allExperiments = await api(url);
  renderExperiments();
  renderExpList();
}

function onRowClick(id) {
  if (clickTimer) clearTimeout(clickTimer);
  clickTimer = setTimeout(() => { clickTimer = null; showDetail(id); }, 250);
}

function cancelRowClick() {
  if (clickTimer) { clearTimeout(clickTimer); clickTimer = null; }
}

function renderExpRow(e) {
  const metricsHtml = Object.entries(e.metrics || {}).slice(0, 3)
    .map(([k,v]) => '<span style="color:var(--blue)">' + esc(k.split('/').pop()) + '</span>=' + (typeof v === 'number' ? v.toFixed(3) : esc(String(v))))
    .join(', ');
  const isSelected = selectedIds.has(e.id);
  const isPinned = pinnedIds.has(e.id);
  const hlGroup = getHighlightGroup(e);
  const rowCls = (isSelected ? 'selected-row' : '') + (isPinned ? ' pinned-row' : '') + (hlGroup ? ' highlighted-row' : '');
  const rowStyle = hlGroup ? ' style="background:' + hlGroup.bg + '"' : '';
  const hlBorder = hlGroup ? ' style="border-left:3px solid ' + hlGroup.border + '"' : '';
  const tagsHtml = (e.tags||[]).map(t=>'<span class="tag">#'+esc(t)+'</span>').join('');
  const groupsHtml = (e.groups||[]).map(g=>'<span class="tag" style="background:rgba(44,90,160,0.1);color:var(--blue)">'+esc(g)+'</span>').join('');
  const notesPreview = e.notes ? esc(e.notes.split('\n')[0].slice(0,60)) : '<span style="color:var(--muted)">--</span>';
  const codeParams = Object.keys(e.params || {}).filter(k => k.startsWith('_code_change/') || k === '_code_changes');
  let codeStatHtml = '--';
  if (codeParams.length) {
    let added = 0, removed = 0;
    for (const k of codeParams) {
      const v = String(e.params[k] || '');
      const parts = v.split('; ');
      for (const p of parts) {
        if (p.trim().startsWith('+')) added++;
        else if (p.trim().startsWith('-')) removed++;
      }
    }
    codeStatHtml = '<span class="code-stat">' + codeParams.length + ' file' + (codeParams.length>1?'s':'');
    if (added || removed) codeStatHtml += ' <span class="lines-added">+' + added + '</span> <span class="lines-removed">-' + removed + '</span>';
    codeStatHtml += '</span>';
  }
  return `<tr class="${rowCls}"${rowStyle} onclick="onRowClick('${e.id}')">
    <td${hlBorder} onclick="event.stopPropagation()"><button class="pin-btn${isPinned?' pinned':''}" onclick="togglePin('${e.id}')" title="${isPinned?'Unpin':'Pin'}">${isPinned?'\u2605':'\u2606'}</button></td>
    <td onclick="event.stopPropagation()">
      <label style="display:flex;align-items:center;justify-content:center;cursor:pointer;padding:4px"><input type="checkbox" ${isSelected?'checked':''} onclick="toggleSelection('${e.id}')" title="Select" style="cursor:pointer"></label>
    </td>
    <td>${e.id.slice(0,6)}</td>
    <td>
      <span class="editable-name" ondblclick="event.stopPropagation();cancelRowClick();startInlineRename('${e.id}',this)">${esc(e.name.slice(0,45))}</span>
    </td>
    <td class="status-${e.status}">${e.status}</td>
    <td class="tags-cell" ondblclick="event.stopPropagation();cancelRowClick();startInlineTag('${e.id}',this)">${tagsHtml || '<span style="color:var(--muted)">--</span>'}</td>
    <td class="tags-cell" ondblclick="event.stopPropagation();cancelRowClick();startInlineGroup('${e.id}',this)">${groupsHtml || '<span style="color:var(--muted)">--</span>'}</td>
    <td class="notes-cell-expanded" title="${esc(e.notes||'')}" ondblclick="event.stopPropagation();cancelRowClick();startInlineNote('${e.id}',this)">${notesPreview}</td>
    <td style="font-size:12px">${metricsHtml || '<span style="color:var(--muted)">--</span>'}</td>
    <td>${codeStatHtml}</td>
    <td>${fmtDt(e.created_at)}</td>
  </tr>`;
}

function renderExperiments() {
  const exps = getFilteredExperiments();
  const tbody = document.getElementById('exp-body');
  if (!tbody) return;
  renderFilterBar();
  updateSortHeaders();
  renderTableActionsBar();

  if (!groupBy) {
    tbody.innerHTML = exps.map(renderExpRow).join('');
    return;
  }

  // Group experiments
  const groups = new Map();
  for (const e of exps) {
    let key = '';
    if (groupBy === 'git_commit') key = e.git_commit ? e.git_commit.slice(0, 7) : 'no commit';
    else if (groupBy === 'git_branch') key = e.git_branch || 'no branch';
    else if (groupBy === 'status') key = e.status || 'unknown';
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(e);
  }

  let html = '';
  for (const [key, items] of groups) {
    const isCollapsed = collapsedGroups.has(key);
    let groupLabel = key;
    if (groupBy === 'git_commit' && items[0].git_branch) {
      groupLabel = key + ' <span class="group-meta">' + esc(items[0].git_branch) + '</span>';
    }
    html += '<tr class="group-header" onclick="toggleGroup(\'' + esc(key) + '\')"><td colspan="11">';
    html += '<span class="group-toggle">' + (isCollapsed ? '\u25B6' : '\u25BC') + '</span> ';
    html += '<span class="group-label">' + groupLabel + '</span>';
    html += '<span class="group-meta"> \u2014 ' + items.length + ' run' + (items.length > 1 ? 's' : '') + '</span>';
    html += '</td></tr>';
    if (!isCollapsed) {
      html += items.map(renderExpRow).join('');
    }
  }
  tbody.innerHTML = html;
}
"""

# Inline editing: rename, tags, notes
JS_INLINE_EDIT = r"""

// ── Inline rename on double-click ────────────────────────────────────────────
function startInlineRename(id, el) {
  const currentName = el.textContent.trim();
  const input = document.createElement('input');
  input.type = 'text';
  input.className = 'name-edit-input';
  input.value = currentName;
  el.replaceWith(input);
  input.focus();
  input.select();

  let saved = false;
  async function doRename() {
    if (saved) return;
    saved = true;
    const newName = input.value.trim();
    if (newName && newName !== currentName) {
      const d = await postApi('/api/experiment/' + id + '/rename', {name: newName});
      if (d.ok) {
        const exp = allExperiments.find(e => e.id === id);
        if (exp) exp.name = newName;
        renderExperiments();
        renderExpList();
        if (currentDetailId === id) {
          const nameEl = document.getElementById('detail-name');
          if (nameEl) nameEl.textContent = newName;
        }
        return;
      }
    }
    renderExperiments();
    renderExpList();
  }

  input.addEventListener('blur', doRename);
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { e.preventDefault(); input.blur(); }
    if (e.key === 'Escape') { input.value = currentName; input.blur(); }
  });
}

// ── Unified item autocomplete helper (tags & groups) ─────────────────────────
function createItemInput(id, items, exp, onUpdate, opts = {}) {
  // opts.kind: 'tag' or 'group'
  // opts.allKnown: allKnownTags or allKnownGroups
  // opts.apiAdd: e.g. '/tag' or '/group'
  // opts.bodyKey: e.g. 'tag' or 'group'
  // opts.expKey: e.g. 'tags' or 'groups'
  // opts.loadAll: e.g. loadAllTags or loadAllGroups
  // opts.prefix: display prefix, e.g. '#' for tags, '' for groups
  const kind = opts.kind || 'tag';
  const allKnown = opts.allKnown || allKnownTags;
  const apiAdd = opts.apiAdd || '/tag';
  const bodyKey = opts.bodyKey || 'tag';
  const expKey = opts.expKey || 'tags';
  const loadAll = opts.loadAll || loadAllTags;
  const prefix = opts.prefix != null ? opts.prefix : '#';

  const wrapper = document.createElement('div');
  wrapper.className = 'tag-autocomplete';
  wrapper.style.cssText = 'display:inline-block;position:relative';
  const input = document.createElement('input');
  input.type = 'text';
  input.placeholder = opts.placeholder || '+ ' + kind;
  input.className = 'name-edit-input';
  input.style.cssText = opts.style || 'width:90px;font-size:12px;padding:2px 4px';
  const dropdown = document.createElement('div');
  dropdown.className = 'tag-autocomplete-list';
  dropdown.style.display = 'none';
  wrapper.appendChild(input);
  wrapper.appendChild(dropdown);
  let activeIdx = -1;

  function showSuggestions() {
    const val = input.value.trim().toLowerCase();
    const existing = new Set(items.map(t => t.toLowerCase()));
    let suggestions = allKnown.filter(t => !existing.has(t.name.toLowerCase()));
    if (val) suggestions = suggestions.filter(t => t.name.toLowerCase().includes(val));
    suggestions = suggestions.slice(0, 8);
    if (val && !suggestions.some(t => t.name.toLowerCase() === val) && !existing.has(val)) {
      suggestions.unshift({name: val, count: 0, isNew: true});
    }
    if (!suggestions.length) { dropdown.style.display = 'none'; return; }
    dropdown.innerHTML = suggestions.map((t, i) =>
      '<div class="tag-autocomplete-item' + (i === activeIdx ? ' active' : '') + '" data-val="' + esc(t.name) + '">' +
      (t.isNew ? '<span class="tag-autocomplete-new">create "' + esc(t.name) + '"</span>' : '<span>' + prefix + esc(t.name) + '</span>') +
      '<span class="tag-count">' + (t.count || '') + '</span></div>'
    ).join('');
    dropdown.style.display = 'block';
    dropdown.querySelectorAll('.tag-autocomplete-item').forEach(item => {
      item.onmousedown = (ev) => { ev.preventDefault(); selectItem(item.dataset.val); };
    });
  }

  async function selectItem(val) {
    if (!val) return;
    const body = {}; body[bodyKey] = val;
    await postApi('/api/experiment/' + id + apiAdd, body);
    if (!items.includes(val)) items.push(val);
    if (exp) exp[expKey] = [...items];
    input.value = '';
    dropdown.style.display = 'none';
    activeIdx = -1;
    loadAll();
    if (onUpdate) onUpdate();
  }

  input.addEventListener('input', () => { activeIdx = -1; showSuggestions(); });
  input.addEventListener('focus', showSuggestions);
  input.addEventListener('blur', () => { setTimeout(() => dropdown.style.display = 'none', 150); });
  input.addEventListener('keydown', (ev) => {
    const items_el = dropdown.querySelectorAll('.tag-autocomplete-item');
    if (ev.key === 'ArrowDown') { ev.preventDefault(); activeIdx = Math.min(activeIdx + 1, items_el.length - 1); showSuggestions(); }
    else if (ev.key === 'ArrowUp') { ev.preventDefault(); activeIdx = Math.max(activeIdx - 1, -1); showSuggestions(); }
    else if (ev.key === 'Enter') {
      ev.preventDefault();
      if (activeIdx >= 0 && items_el[activeIdx]) selectItem(items_el[activeIdx].dataset.val);
      else if (input.value.trim()) selectItem(input.value.trim());
    }
    else if (ev.key === 'Escape') { dropdown.style.display = 'none'; if (opts.onEscape) opts.onEscape(); }
  });
  return { wrapper, input };
}

// Convenience wrappers
function createTagInput(id, tags, exp, onUpdate, opts = {}) {
  return createItemInput(id, tags, exp, onUpdate, Object.assign({
    kind: 'tag', allKnown: allKnownTags, apiAdd: '/tag', bodyKey: 'tag',
    expKey: 'tags', loadAll: loadAllTags, prefix: '#'
  }, opts));
}
function createGroupInput(id, groups, exp, onUpdate, opts = {}) {
  return createItemInput(id, groups, exp, onUpdate, Object.assign({
    kind: 'group', allKnown: allKnownGroups, apiAdd: '/group', bodyKey: 'group',
    expKey: 'groups', loadAll: loadAllGroups, prefix: ''
  }, opts));
}

// ── Unified inline item editing (tags & groups) ──────────────────────────────
function startInlineItems(id, el, opts) {
  // opts.expKey: 'tags' or 'groups'
  // opts.prefix: '#' or ''
  // opts.chipStyle: extra CSS for chips
  // opts.deleteApi: e.g. '/delete-tag' or '/delete-group'
  // opts.deleteBodyKey: e.g. 'tag' or 'group'
  // opts.createInput: createTagInput or createGroupInput
  // opts.loadAll: loadAllTags or loadAllGroups
  const exp = allExperiments.find(e => e.id === id);
  if (!exp) return;
  const items = [...(exp[opts.expKey] || [])];
  const container = document.createElement('div');
  container.style.cssText = 'display:flex;flex-wrap:wrap;gap:4px;align-items:center;min-width:120px';
  container.onclick = (ev) => ev.stopPropagation();

  function render() {
    container.innerHTML = '';
    items.forEach((t, i) => {
      const chip = document.createElement('span');
      chip.className = 'tag';
      chip.style.cssText = 'display:inline-flex;align-items:center;gap:2px' + (opts.chipStyle ? ';' + opts.chipStyle : '');
      chip.textContent = opts.prefix + t;
      const x = document.createElement('span');
      x.textContent = '\u00d7';
      x.style.cssText = 'cursor:pointer;margin-left:2px;color:var(--red);font-weight:bold';
      x.onclick = async (ev) => {
        ev.stopPropagation();
        const body = {}; body[opts.deleteBodyKey] = t;
        await postApi('/api/experiment/' + id + opts.deleteApi, body);
        items.splice(i, 1);
        if (exp) exp[opts.expKey] = [...items];
        render();
        renderExpList();
        opts.loadAll();
      };
      chip.appendChild(x);
      container.appendChild(chip);
    });
    const { wrapper, input } = opts.createInput(id, items, exp, () => {
      render();
      renderExpList();
      renderExperiments();
    }, {
      onEscape: () => { renderExperiments(); renderExpList(); }
    });
    container.appendChild(wrapper);
    setTimeout(() => input.focus(), 0);
  }
  el.innerHTML = '';
  el.appendChild(container);
  render();
}

function startInlineTag(id, el) {
  startInlineItems(id, el, {
    expKey: 'tags', prefix: '#', chipStyle: '',
    deleteApi: '/delete-tag', deleteBodyKey: 'tag',
    createInput: createTagInput, loadAll: loadAllTags
  });
}

function startInlineGroup(id, el) {
  startInlineItems(id, el, {
    expKey: 'groups', prefix: '', chipStyle: 'background:rgba(44,90,160,0.1);color:var(--blue)',
    deleteApi: '/delete-group', deleteBodyKey: 'group',
    createInput: createGroupInput, loadAll: loadAllGroups
  });
}

// ── Inline note editing on double-click ─────────────────────────────────────
function startInlineNote(id, el) {
  const exp = allExperiments.find(e => e.id === id);
  if (!exp) return;
  const textarea = document.createElement('textarea');
  textarea.value = exp.notes || '';
  textarea.className = 'name-edit-input';
  textarea.style.cssText = 'width:100%;min-height:50px;font-size:12px;font-family:inherit;resize:vertical;padding:4px 6px';
  textarea.onclick = (ev) => ev.stopPropagation();
  el.innerHTML = '';
  el.appendChild(textarea);
  textarea.focus();

  let saved = false;
  async function doSave() {
    if (saved) return;
    saved = true;
    const newNotes = textarea.value.trim();
    await postApi('/api/experiment/' + id + '/edit-notes', {notes: newNotes});
    if (exp) exp.notes = newNotes;
    renderExperiments();
    renderExpList();
    if (currentDetailId === id) {
      const notesEl = document.getElementById('detail-notes');
      if (notesEl) notesEl.innerHTML = newNotes ? '<div class="notes-display">'+esc(newNotes)+'<button class="notes-edit-btn" onclick="editNotes(\''+id+'\')">edit</button></div>' : '<span style="color:var(--muted)">none</span>';
    }
  }
  textarea.addEventListener('blur', doSave);
  textarea.addEventListener('keydown', (ev) => {
    if (ev.key === 'Enter' && ev.ctrlKey) { ev.preventDefault(); textarea.blur(); }
    if (ev.key === 'Escape') { saved = true; renderExperiments(); renderExpList(); }
  });
}
"""

# Detail view, export
JS_DETAIL = r"""

async function compareSelected() {
  if (selectedIds.size !== 2) return;
  owlSpeak('compare');
  showCompareView();
  await populateCompareDropdowns();
  const ids = [...selectedIds];
  document.getElementById('cmp-id1').value = ids[0];
  document.getElementById('cmp-id2').value = ids[1];
  doCompare();
}

function filterExps(status) {
  if (status) owlSpeak('filter');
  currentFilter = status;
  renderStatusChips();
  loadExperiments();
}

async function populateCompareDropdowns() {
  const exps = await api('/api/experiments?limit=100');
  const sel1 = document.getElementById('cmp-id1');
  const sel2 = document.getElementById('cmp-id2');
  const prev1 = sel1.value, prev2 = sel2.value;
  const makeOpts = (exps) => '<option value="">-- Select experiment --</option>' +
    exps.map(e => `<option value="${e.id}">${e.id.slice(0,6)} | ${esc(e.name.slice(0,35))} | ${e.status} | ${fmtDt(e.created_at)}</option>`).join('');
  sel1.innerHTML = makeOpts(exps);
  sel2.innerHTML = makeOpts(exps);
  if (prev1) sel1.value = prev1;
  if (prev2) sel2.value = prev2;
  if (!prev1 && !prev2 && selectedIds.size === 2) {
    const ids = [...selectedIds];
    sel1.value = ids[0];
    sel2.value = ids[1];
  }
}

function artifactTypeBadge(path) {
  const ext = (path || '').split('.').pop().toLowerCase();
  if (['png','jpg','jpeg','svg','gif','bmp','tiff'].includes(ext)) return '<span class="artifact-type-badge img">image</span>';
  if (['pt','pth','h5','hdf5','onnx','pkl','joblib','safetensors'].includes(ext)) return '<span class="artifact-type-badge model">model</span>';
  if (['csv','json','jsonl','parquet','tsv','npy','npz'].includes(ext)) return '<span class="artifact-type-badge data">data</span>';
  return '<span class="artifact-type-badge">file</span>';
}

async function showDetail(id) {
  // Toggle: clicking same experiment deselects
  if (currentDetailId === id) {
    showWelcome();
    return;
  }
  return refreshDetail(id);
}

async function refreshDetail(id) {
  currentDetailId = id;
  showDetailView();
  document.getElementById('exp-sidebar').classList.remove('collapsed');
  renderExpList();

  const [exp, metricsData, diffData] = await Promise.all([
    api('/api/experiment/' + id),
    api('/api/metrics/' + id),
    api('/api/diff/' + id),
  ]);
  if (exp.error) return;

  const regularParams = {};
  const codeChanges = {};
  const varChanges = {};
  let cellsRan = null;
  for (const [k, v] of Object.entries(exp.params)) {
    if (k === '_code_changes' || k.startsWith('_code_change/')) {
      codeChanges[k] = v;
    } else if (k.startsWith('_var/')) {
      varChanges[k.slice(5)] = v;
    } else if (k === '_script_hash' || k === '_cells_ran') {
      if (k === '_cells_ran') cellsRan = v;
    } else if (k === '_tags') {
      // skip, shown elsewhere
    } else {
      regularParams[k] = v;
    }
  }

  const paramRows = Object.entries(regularParams).map(([k,v]) =>
    `<tr><td style="color:var(--blue)">${esc(k)}</td><td>${esc(JSON.stringify(v))}</td></tr>`
  ).join('');

  const metricRows = exp.metrics.map(m =>
    `<tr><td style="color:var(--green)">${esc(m.key)}</td><td>${m.last?.toFixed(4) ?? '--'}</td><td>${m.min?.toFixed(4) ?? '--'}</td><td>${m.max?.toFixed(4) ?? '--'}</td><td>${m.n}</td></tr>`
  ).join('');

  const artRows = exp.artifacts.map(a =>
    `<tr><td><div class="artifact-row">${artifactTypeBadge(a.path)} ${esc(a.label)}</div></td><td style="font-size:12px;color:var(--muted)">${esc(a.path)}</td><td><div class="artifact-actions"><button onclick="editArtifact('${exp.id}','${esc(a.label)}','${esc(a.path)}')">edit</button><button class="art-del" onclick="deleteArtifact('${exp.id}','${esc(a.label)}','${esc(a.path)}')">del</button></div></td></tr>`
  ).join('');

  const addArtifactForm = `<div class="artifact-add-form" id="add-artifact-form-${exp.id}">
    <input type="text" id="art-label-${exp.id}" placeholder="Label (e.g. model_v2)" style="width:150px">
    <input type="text" id="art-path-${exp.id}" placeholder="Path (e.g. outputs/model.pt)" style="width:250px">
    <button onclick="addArtifact('${exp.id}')">+ Add Artifact</button>
  </div>`;

  // Code changes
  let codeHtml = '';
  if (Object.keys(codeChanges).length) {
    codeHtml = '<h2 class="section-toggle" onclick="this.classList.toggle(\'collapsed\')">Code Changes</h2><div class="section-body"><div class="code-changes">';
    for (const [k, v] of Object.entries(codeChanges)) {
      const label = k === '_code_changes' ? 'Script diff vs. last commit' : k.replace('_code_change/','Cell ');
      const parts = String(v).split('; ').map(part => {
        const trimmed = part.trim();
        if (trimmed.startsWith('+')) return '<span class="diff-add">' + esc(trimmed) + '</span>';
        if (trimmed.startsWith('-')) return '<span class="diff-del">' + esc(trimmed) + '</span>';
        return esc(trimmed);
      }).join('\n');
      codeHtml += '<div class="change-item"><div class="change-label">' + esc(label) + '</div><div class="change-diff">' + parts + '</div></div>';
    }
    codeHtml += '</div></div>';
  }

  // Variable changes
  let varHtml = '';
  if (Object.keys(varChanges).length) {
    const scalars = {}, arrays = {}, other = {};
    for (const [k, v] of Object.entries(varChanges)) {
      const sv = String(v);
      if (sv.startsWith('ndarray(') || sv.startsWith('Tensor(') || sv.startsWith('DataFrame(') || sv.startsWith('Series(')) {
        arrays[k] = v;
      } else if (sv.startsWith("'") || sv.startsWith('"') || !isNaN(Number(sv)) || sv === 'True' || sv === 'False') {
        scalars[k] = v;
      } else {
        other[k] = v;
      }
    }
    varHtml = '<h2 class="section-toggle" onclick="this.classList.toggle(\'collapsed\')">Variables (' + Object.keys(varChanges).length + ')</h2><div class="section-body"><div class="var-changes">';
    const renderGroup = (title, vars) => {
      if (!Object.keys(vars).length) return '';
      let h = '<div class="var-section-title">' + title + ' (' + Object.keys(vars).length + ')</div><table>';
      for (const [k, v] of Object.entries(vars)) {
        let displayVal = String(v);
        // Strip "varname = " prefix if present (capture stores "x = expr  # type")
        if (displayVal.startsWith(k + ' = ')) {
          displayVal = displayVal.slice(k.length + 3);
        }
        h += '<tr><td class="var-name">' + esc(k) + '</td><td>= ' + esc(displayVal) + '</td></tr>';
      }
      return h + '</table>';
    };
    varHtml += renderGroup('Scalars', scalars);
    varHtml += renderGroup('Arrays & Tensors', arrays);
    varHtml += renderGroup('Other', other);
    varHtml += '</div></div>';
  }

  // Summary card
  const totalMetricSteps = exp.metrics.reduce((s,m) => s + m.n, 0);
  const numVars = Object.keys(varChanges).length;
  const numArt = exp.artifacts.length;
  const numCodeChanges = Object.keys(codeChanges).length;
  let summaryHtml = '<div class="summary-card"><div class="summary-grid">';
  summaryHtml += '<div class="summary-item"><div class="val">' + Object.keys(regularParams).length + '</div><div class="lbl">Params</div></div>';
  summaryHtml += '<div class="summary-item"><div class="val">' + exp.metrics.length + '</div><div class="lbl">Metric Keys</div></div>';
  summaryHtml += '<div class="summary-item"><div class="val">' + totalMetricSteps + '</div><div class="lbl">Metric Points</div></div>';
  summaryHtml += '<div class="summary-item"><div class="val">' + numVars + '</div><div class="lbl">Variables</div></div>';
  summaryHtml += '<div class="summary-item"><div class="val">' + numArt + '</div><div class="lbl">Artifacts</div></div>';
  summaryHtml += '<div class="summary-item"><div class="val">' + numCodeChanges + '</div><div class="lbl">Code Changes</div></div>';
  summaryHtml += '</div></div>';

  // Diff
  let diffHtml = '';
  if (diffData.diff) {
    diffHtml = diffData.diff.split('\n').map(line => {
      if (line.startsWith('+') && !line.startsWith('+++')) return '<span class="diff-add">' + esc(line) + '</span>';
      if (line.startsWith('-') && !line.startsWith('---')) return '<span class="diff-del">' + esc(line) + '</span>';
      if (line.startsWith('@@')) return '<span class="diff-hunk">' + esc(line) + '</span>';
      return esc(line);
    }).join('\n');
  }

  const expTags = exp.tags || [];
  const tagsHtml = '<span class="detail-tags-inline" id="detail-tags-area">' +
    (expTags.length
      ? expTags.map(t => '<span class="tag-removable">#' + esc(t) +
        ' <span class="tag-delete" onclick="event.stopPropagation();deleteTagInline(\'' + exp.id + '\',\'' + esc(t) + '\')" title="Remove tag from this experiment">&times;</span>' +
        '</span>').join('')
      : '') +
    '<span class="tag-input-area" id="detail-tag-input-area"></span>' +
    '</span>';

  const expGroups = exp.groups || [];
  const groupsHtml = '<span class="detail-tags-inline" id="detail-groups-area">' +
    (expGroups.length
      ? expGroups.map(g => '<span class="tag-removable" style="background:rgba(44,90,160,0.1);color:var(--blue)">' + esc(g) +
        ' <span class="tag-delete" onclick="event.stopPropagation();deleteGroupInline(\'' + exp.id + '\',\'' + esc(g) + '\')" title="Remove group">&times;</span>' +
        '</span>').join('')
      : '') +
    '<span class="tag-input-area" id="detail-group-input-area"></span>' +
    '</span>';

  document.getElementById('detail-panel').innerHTML = `
    <div class="detail" style="border:none;padding:4px 16px;margin:0">
      <!-- Summary bar -->
      <div class="detail-summary">
        <span class="sum-item"><strong class="status-${exp.status}">${exp.status}</strong></span>
        <span class="sum-sep">|</span>
        <span class="sum-item">Branch: <strong>${esc(exp.git_branch||'--')}</strong></span>
        <span class="sum-item">Commit: <strong>${esc((exp.git_commit||'--').slice(0,7))}</strong></span>
        <span class="sum-sep">|</span>
        <span class="sum-item">Started: <strong>${fmtDt(exp.created_at)}</strong></span>
        <span class="sum-item">Duration: <strong>${fmtDur(exp.duration_s)}</strong></span>
        <span class="sum-sep">|</span>
        <span class="sum-item">${Object.keys(regularParams).length} params</span>
        <span class="sum-item">${exp.metrics.length} metrics</span>
        <span class="sum-item">${exp.artifacts.length} artifacts</span>
      </div>

      <!-- Header with name + actions -->
      <div class="detail-header">
        <h2 id="detail-name" class="editable-hint" ondblclick="startInlineRename('${exp.id}',this)" title="Double-click to rename">${esc(exp.name)}</h2>
        <div class="detail-actions">
          ${exp.status === 'running' ? `<button class="action-btn primary" onclick="finishExp('${exp.id}')">Finish Run</button>` : ''}
          <button class="action-btn danger" onclick="deleteExp('${exp.id}','${esc(exp.name)}')">Delete</button>
          <button class="close-btn" onclick="showWelcome()" title="Back to list">&times;</button>
        </div>
      </div>

      <div class="detail-export-bar">
        <button class="action-btn primary" onclick="exportExp('${exp.id}')">Export</button>
        <div id="export-container"></div>
      </div>

      <div class="tabs" id="detail-tabs">
        <button class="tab active" onclick="switchDetailTab('overview','${exp.id}')">Overview</button>
        <button class="tab" onclick="switchDetailTab('timeline','${exp.id}')">Timeline</button>
        <button class="tab" onclick="switchDetailTab('images','${exp.id}')">Images</button>
        <button class="tab" onclick="switchDetailTab('compare-within','${exp.id}')">Compare Within</button>
      </div>

      <div id="detail-tab-overview">
        <!-- Two-column grid -->
        <div class="detail-grid">
          <!-- Left column: info + params -->
          <div>
            <div class="info-grid">
              <span class="label">ID</span><span>${exp.id}</span>
              <span class="label">Script</span><span style="font-size:12px">${esc(exp.script||'--')}</span>
              <span class="label">Host</span><span>${exp.hostname||'--'}</span>
              <span class="label">Python</span><span>${exp.python_ver||'--'}</span>
              <span class="label">Tags</span><span class="tag-list" id="detail-tags">${tagsHtml}</span>
              <span class="label">Groups</span><span class="tag-list" id="detail-groups">${groupsHtml}</span>
              <span class="label">Notes</span><span id="detail-notes" class="detail-notes-inline editable-hint" ondblclick="startDetailNoteEdit('${exp.id}',this)" title="Double-click to edit">${exp.notes ? esc(exp.notes) : '<span style="color:var(--muted)">double-click to add notes</span>'}</span>
            </div>
            ${paramRows ? '<h2 class="section-toggle" onclick="this.classList.toggle(\'collapsed\')">Params (' + Object.keys(regularParams).length + ')</h2><div class="section-body"><table class="params-table"><tr><th>Key</th><th>Value</th></tr>'+paramRows+'</table></div>' : ''}
            ${varHtml}
          </div>
          <!-- Right column: metrics + charts + artifacts -->
          <div>
            ${metricRows ? '<h2 class="section-toggle" onclick="this.classList.toggle(\'collapsed\')">Metrics (' + exp.metrics.length + ')</h2><div class="section-body"><table class="metrics-table"><tr><th>Key</th><th>Last</th><th>Min</th><th>Max</th><th>Steps</th></tr>'+metricRows+'</table><div id="charts-container"></div></div>' : '<div id="charts-container"></div>'}
            <h2 class="section-toggle" onclick="this.classList.toggle('collapsed')">Artifacts (${exp.artifacts.length})</h2>
            <div class="section-body">
            ${artRows ? '<table class="params-table"><tr><th>File</th><th>Path</th><th style="width:80px"></th></tr>'+artRows+'</table>' : '<p style="color:var(--muted);font-size:13px">No artifacts yet.</p>'}
            ${addArtifactForm}
            </div>
          </div>
        </div>
        <!-- Full-width sections below the grid -->
        <div style="margin-top:20px">
          ${codeHtml}
          ${diffHtml ? '<h2 class="section-toggle" onclick="this.classList.toggle(\'collapsed\')">Git Diff ('+exp.diff_lines+' lines)</h2><div class="section-body"><div class="diff-view">'+diffHtml+'</div></div>' : ''}
        </div>
      </div>

      <div id="detail-tab-timeline" style="display:none"></div>
      <div id="detail-tab-images" style="display:none"></div>
      <div id="detail-tab-compare-within" style="display:none"></div>
    </div>
  `;

  // Wire up inline tag input in detail view
  const tagInputArea = document.getElementById('detail-tag-input-area');
  if (tagInputArea) {
    const detailTags = [...(exp.tags || [])];
    const { wrapper, input } = createTagInput(exp.id, detailTags, null, () => {
      loadExperiments().then(() => refreshDetail(exp.id));
    }, { placeholder: '+ add tag', style: 'width:100px;font-size:12px;padding:2px 6px' });
    tagInputArea.appendChild(wrapper);
  }

  // Wire up inline group input in detail view
  const groupInputArea = document.getElementById('detail-group-input-area');
  if (groupInputArea) {
    const detailGroups = [...(exp.groups || [])];
    const { wrapper: gWrapper, input: gInput } = createGroupInput(exp.id, detailGroups, null, () => {
      loadExperiments().then(() => refreshDetail(exp.id));
    }, { placeholder: '+ add group', style: 'width:110px;font-size:12px;padding:2px 6px' });
    groupInputArea.appendChild(gWrapper);
  }

  // Render metric charts
  Object.values(charts).forEach(c => c.destroy());
  charts = {};
  const container = document.getElementById('charts-container');
  for (const [key, points] of Object.entries(metricsData)) {
    if (points.length < 2) continue;
    const div = document.createElement('div');
    div.className = 'chart-container';
    const canvas = document.createElement('canvas');
    div.appendChild(canvas);
    container.appendChild(div);
    charts[key] = new Chart(canvas, {
      type: 'line',
      data: {
        labels: points.map((p,i) => p.step !== null ? p.step : i),
        datasets: [{
          label: key,
          data: points.map(p => p.value),
          borderColor: '#2c5aa0',
          backgroundColor: 'rgba(44,90,160,0.1)',
          fill: true, tension: 0.3, pointRadius: 2,
        }]
      },
      options: {
        responsive: true,
        plugins: { legend: { display: true, labels: { font: { family: "'IBM Plex Mono'" } } } },
        scales: {
          x: { title: { display: true, text: 'Step', font: { family: "'IBM Plex Mono'" } } },
          y: { title: { display: true, text: key, font: { family: "'IBM Plex Mono'" } } }
        }
      }
    });
  }
}
"""

# Compare view
JS_COMPARE = r"""

// ── Export ──────────────────────────────────────────────────────────────────────

let _exportCache = {};

async function exportExp(id) {
  owlSpeak('export');
  _exportCache = {};
  const container = document.getElementById('export-container');
  const fmts = ['json','markdown','csv','tsv','plain'];
  let btns = fmts.map(f =>
    '<button class="action-btn" id="export-btn-' + f + '" onclick="doExport(\'' + id + '\',\'' + f + '\')">' +
    f.toUpperCase().replace('PLAIN','Plain Text').replace('MARKDOWN','Markdown') + '</button>'
  ).join('');
  container.innerHTML = '<div class="export-panel">' +
    '<div class="export-actions">' + btns +
    '<button class="action-btn" onclick="downloadExport()">Download File</button>' +
    '<button class="action-btn" onclick="copyExport()">Copy to Clipboard</button>' +
    '<button class="action-btn" onclick="this.closest(\'.export-panel\').remove()">Close</button>' +
    '</div><pre id="export-content" style="display:none"></pre></div>';
}

async function doExport(id, fmt) {
  // Highlight active format button
  document.querySelectorAll('.export-actions .action-btn').forEach(b => b.classList.remove('active-fmt'));
  const btn = document.getElementById('export-btn-' + fmt);
  if (btn) btn.classList.add('active-fmt');

  let text;
  const ext = {json:'.json', markdown:'.md', csv:'.csv', tsv:'.tsv', plain:'.txt'};
  if (fmt === 'csv' || fmt === 'tsv') {
    const data = await postApi('/api/bulk-export', {ids: [id], format: fmt});
    text = data.content || JSON.stringify(data, null, 2);
  } else {
    const data = await api('/api/export/' + id + '?format=' + (fmt === 'plain' ? 'json' : fmt));
    if (fmt === 'markdown') {
      text = data.markdown || JSON.stringify(data, null, 2);
    } else if (fmt === 'plain') {
      text = _formatExpPlainText(data.data || data);
    } else {
      text = JSON.stringify(data, null, 2);
    }
  }
  const pre = document.getElementById('export-content');
  pre.style.display = '';
  pre.textContent = text;

  // Find experiment name for filename
  const exp = allExperiments.find(e => e.id.startsWith(id));
  const name = exp ? exp.name.replace(/[^a-zA-Z0-9_-]/g, '_') : id.slice(0,8);
  _exportCache = {text, filename: name + (ext[fmt] || '.txt'), mime: fmt === 'json' ? 'application/json' : 'text/plain'};
}

function downloadExport() {
  if (!_exportCache.text) { owlSay('Select a format first.'); return; }
  const blob = new Blob([_exportCache.text], {type: _exportCache.mime});
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = _exportCache.filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
  owlSay('Downloaded ' + _exportCache.filename);
}

function copyExport() {
  const pre = document.getElementById('export-content');
  if (!pre || !pre.textContent || pre.style.display === 'none') { owlSay('Select a format first.'); return; }
  navigator.clipboard.writeText(pre.textContent).then(() => {
    owlSay('Copied to clipboard!');
  });
}

// ── Compare ────────────────────────────────────────────────────────────────────

let onlyDiffers = false;

async function doCompare() {
  const id1 = document.getElementById('cmp-id1').value.trim();
  const id2 = document.getElementById('cmp-id2').value.trim();
  if (!id1 || !id2) return;
  const data = await api('/api/compare?id1=' + id1 + '&id2=' + id2);
  if (data.error || data.exp1?.error || data.exp2?.error) {
    document.getElementById('compare-result').innerHTML = '<p>One or both experiments not found.</p>';
    return;
  }
  const e1 = data.exp1, e2 = data.exp2;
  const isUserParam = k => !k.startsWith('_code_change') && k !== '_code_changes' && !k.startsWith('_var/') && k !== '_script_hash' && k !== '_cells_ran' && k !== '_tags';
  const allPKeys = [...new Set([...Object.keys(e1.params), ...Object.keys(e2.params)])].filter(isUserParam).sort();
  const [tlVars1, tlVars2] = await Promise.all([
    api('/api/vars-at/' + id1 + '?seq=999999'),
    api('/api/vars-at/' + id2 + '?seq=999999'),
  ]);
  const allVarKeysFromTimeline = [...new Set([...Object.keys(tlVars1), ...Object.keys(tlVars2)])].sort();
  const allMKeys = [...new Set([...e1.metrics.map(m=>m.key), ...e2.metrics.map(m=>m.key)])].sort();
  const m1 = Object.fromEntries(e1.metrics.map(m => [m.key, m.last]));
  const m2 = Object.fromEntries(e2.metrics.map(m => [m.key, m.last]));

  const n1 = e1.name.length > 25 ? e1.name.slice(0,22) + '...' : e1.name;
  const n2 = e2.name.length > 25 ? e2.name.slice(0,22) + '...' : e2.name;

  let html = '<div class="compare-grid">';
  html += '<div><h2>' + esc(n1) + '</h2><p class="status-' + e1.status + '">' + e1.status + ' - ' + fmtDur(e1.duration_s) + '</p></div>';
  html += '<div><h2>' + esc(n2) + '</h2><p class="status-' + e2.status + '">' + e2.status + ' - ' + fmtDur(e2.duration_s) + '</p></div>';
  html += '</div>';
  html += '<label class="only-differs-toggle"><input type="checkbox" ' + (onlyDiffers ? 'checked' : '') + ' onchange="onlyDiffers=this.checked;doCompare()"> Show only differences</label>';

  if (allPKeys.length) {
    html += '<details open><summary style="cursor:pointer;font-size:16px;font-weight:600;margin:12px 0">Params</summary><table class="params-table"><tr><th>Key</th><th>' + esc(n1) + '</th><th>' + esc(n2) + '</th></tr>';
    for (const k of allPKeys) {
      const v1 = JSON.stringify(e1.params[k] ?? '--');
      const v2 = JSON.stringify(e2.params[k] ?? '--');
      const differs = v1 !== v2;
      if (onlyDiffers && !differs) continue;
      const cls1 = differs ? (e1.params[k]!==undefined ? ' class="diff-removed"' : '') : '';
      const cls2 = differs ? (e2.params[k]!==undefined ? ' class="diff-added"' : '') : '';
      html += '<tr><td>' + esc(k) + '</td><td' + cls1 + '>' + esc(v1) + '</td><td' + cls2 + '>' + esc(v2) + '</td></tr>';
    }
    html += '</table></details>';
  }

  if (allVarKeysFromTimeline.length) {
    html += '<details open><summary style="cursor:pointer;font-size:16px;font-weight:600;margin:12px 0">Variables <span class="help-icon" title="Final variable state from the execution timeline of each experiment.">?</span></summary><table class="params-table"><tr><th>Variable</th><th>' + esc(n1) + '</th><th>' + esc(n2) + '</th></tr>';
    for (const k of allVarKeysFromTimeline) {
      const v1 = String(tlVars1[k] ?? '--').slice(0, 60);
      const v2 = String(tlVars2[k] ?? '--').slice(0, 60);
      const differs = v1 !== v2;
      if (onlyDiffers && !differs) continue;
      const cls1 = differs ? ' class="diff-removed"' : '';
      const cls2 = differs ? ' class="diff-added"' : '';
      html += '<tr><td class="var-name">' + esc(k) + '</td><td' + cls1 + '>' + esc(v1) + '</td><td' + cls2 + '>' + esc(v2) + '</td></tr>';
    }
    html += '</table></details>';
  }

  if (allMKeys.length) {
    html += '<details open><summary style="cursor:pointer;font-size:16px;font-weight:600;margin:12px 0">Metrics (last)</summary><table class="metrics-table"><tr><th>Key</th><th>' + esc(n1) + '</th><th>' + esc(n2) + '</th><th>Delta</th></tr>';
    for (const k of allMKeys) {
      const v1 = m1[k], v2 = m2[k];
      const sv1 = v1 !== undefined ? v1.toFixed(4) : '--';
      const sv2 = v2 !== undefined ? v2.toFixed(4) : '--';
      let delta = '';
      if (v1 !== undefined && v2 !== undefined) {
        const d = v2 - v1;
        if (onlyDiffers && Math.abs(d) < 0.0001) continue;
        const arrow = d > 0 ? '&#x25B2;' : d < 0 ? '&#x25BC;' : '';
        delta = '<span style="color:' + (d>0?'var(--green,#3fb950)':'var(--red,#f85149)') + '">' + arrow + ' ' + (d>0?'+':'') + d.toFixed(4) + '</span>';
      }
      html += '<tr><td>' + esc(k) + '</td><td>' + sv1 + '</td><td>' + sv2 + '</td><td>' + delta + '</td></tr>';
    }
    html += '</table></details>';
  }
  document.getElementById('compare-result').innerHTML = html;
}
"""

# Utility functions and mutation actions
JS_MUTATIONS = r"""

function esc(s) {
  if (s == null) return '';
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
}


async function deleteExp(id, name) {
  owlSpeak('delete');
  if (!confirm('Delete experiment "' + name + '"? This cannot be undone.')) return;
  const d = await postApi('/api/experiment/' + id + '/delete');
  if (d.ok) {
    showWelcome();
    loadStats();
    loadExperiments();
  } else alert(d.error || 'Failed');
}

async function finishExp(id) {
  if (!confirm('Mark this experiment as done?')) return;
  const d = await postApi('/api/experiment/' + id + '/finish');
  if (d.ok) {
    refreshDetail(id);
    loadStats();
    loadExperiments();
  } else alert(d.error || 'Failed');
}

// ── Add artifact ─────────────────────────────────────────────────────────────

async function addArtifact(id) {
  const label = document.getElementById('art-label-' + id).value.trim();
  const path = document.getElementById('art-path-' + id).value.trim();
  if (!label && !path) { alert('Provide a label or path'); return; }
  const d = await postApi('/api/experiment/' + id + '/artifact', {label, path});
  if (d.ok) { refreshDetail(id); }
  else alert(d.error || 'Failed');
}

// ── Edit/delete tags, notes, artifacts ────────────────────────────────────────



async function deleteTagInline(id, tag) {
  // Optimistic removal: hide the tag chip immediately
  const exp = allExperiments.find(e => e.id === id);
  if (exp) exp.tags = (exp.tags||[]).filter(t => t !== tag);
  const area = document.getElementById('detail-tags-area');
  if (area) {
    area.querySelectorAll('.tag-removable').forEach(el => {
      if (el.textContent.trim().replace(/×$/, '').trim() === '#' + tag) el.remove();
    });
  }
  const d = await postApi('/api/experiment/' + id + '/delete-tag', {tag});
  if (d.ok) { loadAllTags(); loadExperiments().then(() => refreshDetail(id)); }
}

function startDetailNoteEdit(id, el) {
  const currentText = el.textContent.trim();
  const isPlaceholder = el.querySelector('span[style]') !== null;
  const textarea = document.createElement('textarea');
  textarea.className = 'notes-edit-area';
  textarea.value = isPlaceholder ? '' : currentText;
  textarea.style.cssText = 'width:100%;min-height:60px;font-size:13px;font-family:inherit;border:1px solid var(--blue);border-radius:3px;padding:4px 6px';
  el.innerHTML = '';
  el.appendChild(textarea);
  textarea.focus();

  let saved = false;
  async function doSave() {
    if (saved) return;
    saved = true;
    const notes = textarea.value;
    await postApi('/api/experiment/' + id + '/edit-notes', {notes});
    const exp = allExperiments.find(e => e.id === id);
    if (exp) exp.notes = notes;
    refreshDetail(id);
  }
  textarea.addEventListener('blur', doSave);
  textarea.addEventListener('keydown', (ev) => {
    if (ev.key === 'Enter' && !ev.shiftKey) { ev.preventDefault(); textarea.blur(); }
    if (ev.key === 'Escape') { saved = true; refreshDetail(id); }
  });
}


async function deleteArtifact(id, label, path) {
  if (!confirm('Delete artifact "' + label + '"?')) return;
  const d = await postApi('/api/experiment/' + id + '/delete-artifact', {label, path});
  if (d.ok) { refreshDetail(id); }
  else alert(d.error || 'Failed');
}

async function editArtifact(id, oldLabel, oldPath) {
  const newLabel = prompt('Edit label:', oldLabel);
  if (newLabel === null) return;
  const newPath = prompt('Edit path:', oldPath);
  if (newPath === null) return;
  const d = await postApi('/api/experiment/' + id + '/edit-artifact', {old_label: oldLabel, old_path: oldPath, new_label: newLabel.trim(), new_path: newPath.trim()});
  if (d.ok) { refreshDetail(id); }
  else alert(d.error || 'Failed');
}

"""

# Timeline visualization and within-experiment comparison
JS_TIMELINE = r"""
// ── Detail sub-tabs ──────────────────────────────────────────────────────────

let currentDetailTab = 'overview';
let currentDetailExpId = '';

function switchDetailTab(tab, expId) {
  currentDetailTab = tab;
  currentDetailExpId = expId;
  document.querySelectorAll('#detail-tabs .tab').forEach((t,i) => {
    const tabs = ['overview','timeline','images','compare-within'];
    t.classList.toggle('active', tabs[i] === tab);
  });
  ['overview','timeline','images','compare-within'].forEach(t => {
    const el = document.getElementById('detail-tab-'+t);
    if (el) el.style.display = t === tab ? '' : 'none';
  });
  if (tab === 'timeline') loadTimeline(expId);
  if (tab === 'images') loadImages(expId);
  if (tab === 'compare-within') loadCompareWithin(expId);
}

// ── Timeline visualization ───────────────────────────────────────────────────

let timelineFilter = '';

async function loadTimeline(expId, filter) {
  if (filter !== undefined) timelineFilter = filter;
  const url = timelineFilter
    ? '/api/timeline/' + expId + '?type=' + timelineFilter
    : '/api/timeline/' + expId;
  const events = await api(url);
  const container = document.getElementById('detail-tab-timeline');

  let html = '<div class="tl-filters">';
  const types = ['', 'cell_exec', 'var_set', 'artifact', 'observational'];
  const labels = ['All', 'Code', 'Variables', 'Artifacts', 'Observational'];
  types.forEach((t, i) => {
    html += '<button class="' + (timelineFilter===t?'active':'') + '" onclick="loadTimeline(\'' + expId + '\',\'' + t + '\')">' + labels[i] + '</button>';
  });
  html += '</div>';

  if (!events.length) {
    html += '<p style="color:var(--muted)">No timeline events recorded.</p>';
    container.innerHTML = html;
    return;
  }

  html += '<p style="color:var(--muted);font-size:12px;margin-bottom:8px">' + events.length + ' events. Click "view source" on cells to see full code.</p>';

  const varState = {};

  html += '<div class="timeline">';
  for (const ev of events) {
    const cls = 'tl-event tl-' + ev.event_type;
    const ts = fmtDt(ev.ts);
    const icons = {cell_exec:'&gt;&gt;', var_set:'=', artifact:'&#9633;', metric:'#', observational:'..'};
    const colors = {cell_exec:'var(--tl-cell)', var_set:'var(--tl-var)', artifact:'var(--tl-artifact)', metric:'var(--tl-metric)', observational:'var(--tl-obs)'};
    const typeLabels = {cell_exec:'code', var_set:'var', artifact:'artifact', metric:'metric', observational:'observe'};
    const icon = icons[ev.event_type] || '?';
    const iconColor = colors[ev.event_type] || 'var(--fg)';
    const typeLabel = '<span class="tl-type-label tl-type-' + ev.event_type + '">' + (typeLabels[ev.event_type]||ev.event_type) + '</span>';

    if (ev.event_type === 'cell_exec' || ev.event_type === 'observational') {
      const info = ev.value || {};
      const preview = (info.source_preview || '').split('\n')[0].slice(0, 80);
      let badges = '';
      if (info.code_is_new) badges += '<span class="tl-badge tl-badge-new">new</span>';
      if (info.code_changed) badges += '<span class="tl-badge tl-badge-edited">edited</span>';
      if (info.is_rerun) badges += '<span class="tl-badge tl-badge-rerun">rerun</span>';
      if (info.has_output) badges += '<span class="tl-badge tl-badge-output">output</span>';

      // View source button - uses cell_hash to fetch from lineage
      const viewSrcBtn = ev.cell_hash ? ' <button class="view-source-btn" onclick="event.stopPropagation();viewCellSource(\'' + ev.cell_hash + '\',this)">view source</button>' : '';

      html += '<div class="' + cls + '">';
      html += '<div class="tl-seq">' + ev.seq + '</div>';
      html += '<div class="tl-icon" style="color:' + iconColor + '">' + icon + '</div>';
      html += '<div class="tl-body">';
      html += typeLabel + '<strong>' + esc(ev.key||'') + '</strong>' + badges + viewSrcBtn;
      html += ' <span style="color:var(--muted);margin-left:8px">' + ts + '</span>';
      if (preview) html += '<div class="tl-code-preview">' + esc(preview) + '</div>';
      if (info.output_preview) {
        html += '<div style="margin-top:3px;font-size:11px;color:var(--green)">output: ' + esc(String(info.output_preview).slice(0,80)) + '</div>';
      }

      if (ev.source_diff && ev.source_diff.length) {
        html += '<div class="tl-diff">';
        for (const d of ev.source_diff.slice(0, 8)) {
          if (d.op === '+') html += '<div class="diff-add">+ ' + esc(d.line.slice(0,80)) + '</div>';
          else if (d.op === '-') html += '<div class="diff-del">- ' + esc(d.line.slice(0,80)) + '</div>';
        }
        if (ev.source_diff.length > 8) html += '<div style="color:var(--muted)">... ' + (ev.source_diff.length - 8) + ' more lines</div>';
        html += '</div>';
      }
      html += '</div></div>';

    } else if (ev.event_type === 'var_set') {
      varState[ev.key] = ev.value;
      let cleanVal = String(ev.value);
      if (cleanVal.startsWith(ev.key + ' = ')) {
        cleanVal = cleanVal.slice(ev.key.length + 3);
      }
      const valStr = cleanVal.slice(0, 60);
      let prevHtml = '';
      if (ev.prev_value !== null && ev.prev_value !== undefined) {
        let cleanPrev = String(ev.prev_value);
        if (cleanPrev.startsWith(ev.key + ' = ')) {
          cleanPrev = cleanPrev.slice(ev.key.length + 3);
        }
        prevHtml = ' <span class="tl-var-arrow">&larr;</span> <span style="color:var(--muted);text-decoration:line-through">' + esc(cleanPrev.slice(0,40)) + '</span>';
      }
      html += '<div class="' + cls + '">';
      html += '<div class="tl-seq">' + ev.seq + '</div>';
      html += '<div class="tl-icon" style="color:' + iconColor + '">' + icon + '</div>';
      html += '<div class="tl-body">';
      html += typeLabel + '<strong style="color:var(--tl-var)">' + esc(ev.key) + '</strong> = ' + esc(valStr) + prevHtml;
      html += ' <span style="color:var(--muted);margin-left:8px">' + ts + '</span>';
      html += '</div></div>';

    } else if (ev.event_type === 'artifact') {
      html += '<div class="' + cls + '">';
      html += '<div class="tl-seq">' + ev.seq + '</div>';
      html += '<div class="tl-icon" style="color:' + iconColor + '">' + icon + '</div>';
      html += '<div class="tl-body">';
      html += typeLabel + artifactTypeBadge(String(ev.value||'')) + ' <strong>' + esc(ev.key||'') + '</strong> &rarr; ' + esc(String(ev.value||'').slice(0,60));
      html += ' <span style="color:var(--muted);margin-left:8px">' + ts + '</span>';
      const ctxKeys = Object.keys(varState).filter(k => !k.startsWith('_'));
      if (ctxKeys.length) {
        const ctx = ctxKeys.slice(0, 6).map(k => k + '=' + String(varState[k]).slice(0,15)).join(', ');
        html += '<div class="tl-context">context: ' + esc(ctx) + '</div>';
      }
      html += '</div></div>';

    } else if (ev.event_type === 'metric') {
      html += '<div class="' + cls + '">';
      html += '<div class="tl-seq">' + ev.seq + '</div>';
      html += '<div class="tl-icon" style="color:' + iconColor + '">' + icon + '</div>';
      html += '<div class="tl-body">';
      html += typeLabel + '<strong style="color:var(--tl-metric)">' + esc(ev.key) + '</strong> = ' + ev.value;
      html += ' <span style="color:var(--muted);margin-left:8px">' + ts + '</span>';
      html += '</div></div>';
    }
  }
  html += '</div>';
  container.innerHTML = html;
}

async function viewCellSource(cellHash, btnEl) {
  // Toggle: if source is already showing, hide it
  const existing = btnEl.parentElement.querySelector('.source-view');
  if (existing) {
    existing.remove();
    btnEl.textContent = 'view source';
    return;
  }
  btnEl.textContent = 'loading...';
  const data = await api('/api/cell-source/' + cellHash);
  btnEl.textContent = 'hide source';
  if (data.error) {
    const div = document.createElement('div');
    div.className = 'source-view';
    div.textContent = 'Source not available (cell hash: ' + cellHash + ')';
    btnEl.parentElement.appendChild(div);
    return;
  }
  let html = '<div class="source-view">';
  // Show current source with line numbers
  html += '<div style="margin-bottom:8px;color:var(--blue);font-size:11px;text-transform:uppercase">Current cell source (hash: ' + cellHash + ')</div>';
  const lines = data.source.split('\n');
  for (let i = 0; i < lines.length; i++) {
    html += '<span class="line-num">' + (i+1) + '</span>' + esc(lines[i]) + '\n';
  }
  // If there's a parent, show it too
  if (data.parent_source) {
    html += '<div style="margin-top:12px;border-top:1px solid var(--border);padding-top:8px;color:var(--muted);font-size:11px;text-transform:uppercase">Previous version (hash: ' + data.parent_hash + ')</div>';
    const plines = data.parent_source.split('\n');
    for (let i = 0; i < plines.length; i++) {
      html += '<span class="line-num">' + (i+1) + '</span><span style="color:var(--muted)">' + esc(plines[i]) + '</span>\n';
    }
  }
  html += '</div>';
  btnEl.parentElement.insertAdjacentHTML('beforeend', html);
}

// ── Image gallery ────────────────────────────────────────────────────────────

let imageFilter = '';
let imageSort = 'date';
let imageLimit = 50;
let imageSortDir = 'desc';

async function loadImages(expId) {
  const container = document.getElementById('detail-tab-images');
  if (!container) return;
  container.innerHTML = '<p style="color:var(--muted)">Loading...</p>';

  const data = await api('/api/images/' + expId);
  if (data.error && data.error !== 'not found') {
    container.innerHTML = '<p style="color:var(--muted)">Error: ' + esc(data.error) + '</p>';
    return;
  }

  const paths = data.paths || [];
  const suggestedPaths = data.suggested_paths || [];
  let images = data.images || [];

  let html = '<div class="img-paths-section">';
  html += '<h3 style="font-size:14px;margin-bottom:8px">Image Paths</h3>';
  html += '<p style="font-size:12px;color:var(--muted);margin-bottom:8px">Add folders to scan for images. Paths are relative to project root.</p>';

  // Show saved paths
  if (paths.length) {
    for (let i = 0; i < paths.length; i++) {
      const p = paths[i];
      html += '<div class="img-path-row">';
      html += '<span class="img-path-val" ondblclick="startEditImagePath(\'' + expId + '\',' + i + ',this)">' + esc(p) + '</span>';
      html += '<button class="img-path-del" onclick="deleteImagePath(\'' + expId + '\',' + i + ')" title="Remove path">&times;</button>';
      html += '</div>';
    }
  }

  // Add path form
  html += '<div class="img-path-add">';
  html += '<input type="text" id="img-path-input" placeholder="e.g. outputs/samples" style="flex:1">';
  html += '<button onclick="addImagePath(\'' + expId + '\')">Add Path</button>';
  html += '</div>';

  // Suggested paths from output_dir or params
  if (suggestedPaths.length && paths.length === 0) {
    html += '<div style="margin-top:6px;font-size:11px;color:var(--muted)">Suggestions: ';
    html += suggestedPaths.map(s => '<a href="#" style="color:var(--blue)" onclick="event.preventDefault();document.getElementById(\'img-path-input\').value=\'' + esc(s) + '\';addImagePath(\'' + expId + '\')">' + esc(s) + '</a>').join(', ');
    html += '</div>';
  }
  html += '</div>';

  // Show images if we have any
  if (images.length) {
    // Collect unique directories for filtering
    const dirs = [...new Set(images.map(img => img.dir))].sort();

    // Apply filter
    let filtered = images;
    if (imageFilter) {
      filtered = filtered.filter(img => img.dir === imageFilter);
    }

    // Apply sort
    if (imageSort === 'name') {
      filtered = [...filtered].sort((a, b) => imageSortDir === 'asc' ? a.name.localeCompare(b.name) : b.name.localeCompare(a.name));
    } else {
      // date sort
      filtered = [...filtered].sort((a, b) => imageSortDir === 'asc' ? a.modified - b.modified : b.modified - a.modified);
    }

    const totalFiltered = filtered.length;
    // Apply limit
    const displayLimit = imageLimit > 0 ? imageLimit : filtered.length;
    const limited = filtered.slice(0, displayLimit);

    html += '<div class="img-gallery-toolbar">';
    html += '<span style="color:var(--muted);font-size:13px">' + (totalFiltered < images.length ? totalFiltered + ' of ' : '') + images.length + ' image' + (images.length !== 1 ? 's' : '') + '</span>';

    // Refresh button
    html += ' <button class="img-filter-select" onclick="loadImages(\'' + expId + '\')" title="Refresh images" style="cursor:pointer">&#x21bb; Refresh</button>';

    if (dirs.length > 1) {
      html += ' <select class="img-filter-select" onchange="imageFilter=this.value;loadImages(\'' + expId + '\')">';
      html += '<option value=""' + (imageFilter === '' ? ' selected' : '') + '>All folders</option>';
      for (const d of dirs) {
        html += '<option value="' + esc(d) + '"' + (imageFilter === d ? ' selected' : '') + '>' + esc(d) + '</option>';
      }
      html += '</select>';
    }

    // Sort by
    html += ' <select class="img-filter-select" onchange="imageSort=this.value;loadImages(\'' + expId + '\')">';
    html += '<option value="date"' + (imageSort === 'date' ? ' selected' : '') + '>Sort by date</option>';
    html += '<option value="name"' + (imageSort === 'name' ? ' selected' : '') + '>Sort by name</option>';
    html += '</select>';

    // Sort direction toggle
    html += ' <button class="img-filter-select" onclick="imageSortDir=imageSortDir===\'asc\'?\'desc\':\'asc\';loadImages(\'' + expId + '\')" title="Toggle sort direction" style="cursor:pointer">' + (imageSortDir === 'asc' ? '\u25B2 Asc' : '\u25BC Desc') + '</button>';

    // Show count
    html += ' <select class="img-filter-select" onchange="imageLimit=parseInt(this.value);loadImages(\'' + expId + '\')">';
    const limits = [20, 50, 100, 200, 0];
    const limitLabels = ['Show 20', 'Show 50', 'Show 100', 'Show 200', 'Show all'];
    for (let i = 0; i < limits.length; i++) {
      html += '<option value="' + limits[i] + '"' + (imageLimit === limits[i] ? ' selected' : '') + '>' + limitLabels[i] + '</option>';
    }
    html += '</select>';

    html += '</div>';

    if (totalFiltered > displayLimit) {
      html += '<div style="font-size:12px;color:var(--muted);margin-bottom:8px">Showing ' + displayLimit + ' of ' + totalFiltered + ' images</div>';
    }

    html += '<div class="img-gallery">';
    for (const img of limited) {
      const src = '/api/file/' + encodeURIComponent(img.path).replace(/%2F/g, '/');
      const sizeKb = (img.size / 1024).toFixed(1);
      const modDate = img.modified ? new Date(img.modified * 1000).toLocaleString() : '';
      html += '<div class="img-card" onclick="openImageModal(\'' + esc(src) + '\',\'' + esc(img.name) + '\')">';
      html += '<div class="img-thumb"><img src="' + src + '" alt="' + esc(img.name) + '" loading="lazy"></div>';
      html += '<div class="img-info">';
      html += '<div class="img-name" title="' + esc(img.path) + '">' + esc(img.name) + '</div>';
      if (img.dir !== '.') html += '<div class="img-dir">' + esc(img.dir) + '</div>';
      html += '<div class="img-meta">' + sizeKb + ' KB' + (modDate ? ' &middot; ' + modDate : '') + '</div>';
      html += '</div></div>';
    }
    html += '</div>';
  } else if (paths.length) {
    html += '<p style="color:var(--muted);margin-top:12px">No images found in the specified path(s).</p>';
    html += ' <button class="img-filter-select" onclick="loadImages(\'' + expId + '\')" title="Refresh images" style="cursor:pointer;margin-top:8px">&#x21bb; Refresh</button>';
  }

  container.innerHTML = html;
}

async function addImagePath(expId) {
  const input = document.getElementById('img-path-input');
  const path = input ? input.value.trim() : '';
  if (!path) return;
  await postApi('/api/experiment/' + expId + '/image-path', {action: 'add', path});
  loadImages(expId);
}

async function deleteImagePath(expId, index) {
  await postApi('/api/experiment/' + expId + '/image-path', {action: 'delete', index});
  loadImages(expId);
}

function startEditImagePath(expId, index, el) {
  const currentVal = el.textContent.trim();
  const input = document.createElement('input');
  input.type = 'text'; input.className = 'name-edit-input';
  input.value = currentVal; input.style.cssText = 'width:200px;font-size:12px;padding:2px 4px';
  el.innerHTML = ''; el.appendChild(input); input.focus(); input.select();
  let saved = false;
  async function doSave() {
    if (saved) return; saved = true;
    const newVal = input.value.trim();
    if (newVal && newVal !== currentVal) {
      await postApi('/api/experiment/' + expId + '/image-path', {action: 'edit', index, path: newVal});
    }
    loadImages(expId);
  }
  input.addEventListener('blur', doSave);
  input.addEventListener('keydown', (ev) => {
    if (ev.key === 'Enter') { ev.preventDefault(); input.blur(); }
    if (ev.key === 'Escape') { saved = true; loadImages(expId); }
  });
}

function openImageModal(src, name) {
  const overlay = document.createElement('div');
  overlay.className = 'img-modal-overlay';
  overlay.onclick = (ev) => { if (ev.target === overlay) overlay.remove(); };

  const content = document.createElement('div');
  content.className = 'img-modal-content';
  content.innerHTML = '<div class="img-modal-header"><span class="img-modal-name">' + esc(name) + '</span><button class="img-modal-close" onclick="this.closest(\'.img-modal-overlay\').remove()">&times;</button></div>' +
    '<img src="' + src + '" alt="' + esc(name) + '" style="max-width:100%;max-height:calc(100vh - 80px);object-fit:contain">';
  overlay.appendChild(content);
  document.body.appendChild(overlay);

  const handler = (ev) => { if (ev.key === 'Escape') { overlay.remove(); document.removeEventListener('keydown', handler); } };
  document.addEventListener('keydown', handler);
}

// ── Within-experiment comparison ─────────────────────────────────────────────

let withinSeq1 = null, withinSeq2 = null;

async function loadCompareWithin(expId) {
  const events = await api('/api/timeline/' + expId);
  const container = document.getElementById('detail-tab-compare-within');

  const cellEvents = events.filter(e => e.event_type === 'cell_exec' || e.event_type === 'artifact');

  let html = '<p style="margin-bottom:12px">Select two timeline points to compare variable state. <span class="help-icon" title="Click two events to see how variables changed between them. Useful for tracking how a variable (e.g. learning rate, model weights) evolved during the experiment.">?</span></p>';
  html += '<div class="tl-compare-bar">';
  html += '<span>Point A: <strong id="cw-seq1">' + (withinSeq1 !== null ? 'seq='+withinSeq1 : 'click to select') + '</strong></span>';
  html += '<span>Point B: <strong id="cw-seq2">' + (withinSeq2 !== null ? 'seq='+withinSeq2 : 'click to select') + '</strong></span>';
  html += '<button onclick="doWithinCompare(\'' + expId + '\')">Compare</button>';
  html += '<button onclick="withinSeq1=null;withinSeq2=null;loadCompareWithin(\'' + expId + '\')" style="background:var(--muted)">Clear</button>';
  html += '</div>';

  html += '<div class="timeline" style="max-height:400px;overflow-y:auto">';
  for (const ev of cellEvents) {
    const info = ev.value || {};
    const preview = (info.source_preview || ev.key || '').split('\n')[0].slice(0, 60);
    const selCls = (withinSeq1 === ev.seq || withinSeq2 === ev.seq) ? ' tl-seq-select selected' : ' tl-seq-select';
    html += '<div class="tl-event tl-' + ev.event_type + selCls + '" onclick="selectWithinSeq(' + ev.seq + ',\'' + expId + '\')" style="cursor:pointer">';
    html += '<div class="tl-seq">' + ev.seq + '</div>';
    html += '<div class="tl-body">';
    html += '<strong>' + esc(ev.key||'') + '</strong>';
    html += ' <span style="color:var(--muted);margin-left:8px">' + fmtDt(ev.ts) + '</span>';
    if (preview) html += '<div class="tl-code-preview">' + esc(preview) + '</div>';
    html += '</div></div>';
  }
  html += '</div>';
  html += '<div id="within-compare-result"></div>';
  container.innerHTML = html;
}

function selectWithinSeq(seq, expId) {
  if (withinSeq1 === null || (withinSeq1 !== null && withinSeq2 !== null)) {
    withinSeq1 = seq;
    withinSeq2 = null;
  } else {
    withinSeq2 = seq;
  }
  loadCompareWithin(expId);
}

async function doWithinCompare(expId) {
  if (withinSeq1 === null || withinSeq2 === null) return;
  const [vars1, vars2] = await Promise.all([
    api('/api/vars-at/' + expId + '?seq=' + withinSeq1),
    api('/api/vars-at/' + expId + '?seq=' + withinSeq2),
  ]);

  const allKeys = [...new Set([...Object.keys(vars1), ...Object.keys(vars2)])].sort();
  let html = '<div class="within-compare">';
  html += '<h3>Variable state: seq=' + withinSeq1 + ' vs seq=' + withinSeq2 + '</h3>';
  html += '<table class="params-table">';
  html += '<tr><th>Variable</th><th>@seq=' + withinSeq1 + '</th><th>@seq=' + withinSeq2 + '</th></tr>';

  for (const k of allKeys) {
    const v1 = vars1[k] !== undefined ? String(vars1[k]).slice(0, 50) : '--';
    const v2 = vars2[k] !== undefined ? String(vars2[k]).slice(0, 50) : '--';
    const differs = String(vars1[k]) !== String(vars2[k]);
    const cls = differs ? ' class="differs"' : '';
    html += '<tr><td class="var-name">' + esc(k) + '</td><td' + cls + '>' + esc(v1) + '</td><td' + cls + '>' + esc(v2) + '</td></tr>';
  }
  html += '</table></div>';

  document.getElementById('within-compare-result').innerHTML = html;
}
"""

# Initialization
JS_INIT = r"""

// Init — sidebar starts collapsed (opens when entering detail view)
document.getElementById('exp-sidebar').classList.add('collapsed');
loadTimezoneConfig();
loadAllTags();
loadAllGroups();
loadStats();
loadExperiments().then(() => {
  if (allExperiments.length === 0) owlSpeak('empty');
  else owlSpeak('welcome');
});
"""

# Group management UI — column-based groups with inline editing
JS_GROUPS = r"""
// ── Group management ─────────────────────────────────────────────────────────

async function deleteGroupGlobal(name) {
  const count = allExperiments.filter(e => (e.groups||[]).includes(name)).length;
  if (!confirm('Delete group "' + name + '" from ' + count + ' experiment(s)? This cannot be undone.')) return;
  const res = await postApi('/api/groups/delete', {name});
  if (res.ok) {
    if (groupFilter === name) groupFilter = '';
    await loadAllGroups();
    await loadExperiments();
    renderManagePanel();
  }
}

async function createGroupFromPanel() {
  const input = document.getElementById('new-group-name');
  const name = input ? input.value.trim() : '';
  if (!name) return;
  const ids = [...selectedIds];
  if (ids.length > 0) {
    const res = await postApi('/api/groups/create', {name, experiment_ids: ids});
    if (res.ok) owlSay('Group "' + name + '" created with ' + ids.length + ' experiment(s)!');
  } else {
    owlSay('Select experiments first, then create a group.');
    return;
  }
  if (input) input.value = '';
  await loadAllGroups();
  await loadExperiments();
  renderManagePanel();
}

async function promptBulkAddToGroup() {
  const name = prompt('Group name to add ' + selectedIds.size + ' experiment(s) to:');
  if (!name || !name.trim()) return;
  const res = await postApi('/api/bulk-add-to-group', {group: name.trim(), ids: [...selectedIds]});
  if (res.ok) {
    await loadAllGroups();
    await loadExperiments();
    owlSay('Added ' + res.added + ' to "' + name.trim() + '"');
  } else {
    alert(res.error || 'Failed');
  }
}

async function deleteGroupInline(id, group) {
  const exp = allExperiments.find(e => e.id === id);
  if (exp) exp.groups = (exp.groups||[]).filter(g => g !== group);
  const area = document.getElementById('detail-groups-area');
  if (area) {
    area.querySelectorAll('.tag-removable').forEach(el => {
      if (el.textContent.trim().replace(/\u00d7$/, '').trim() === group) el.remove();
    });
  }
  const d = await postApi('/api/experiment/' + id + '/delete-group', {group});
  if (d.ok) { loadAllGroups(); loadExperiments().then(() => { if (currentDetailId === id) refreshDetail(id); }); }
}
"""


def get_all_js() -> str:
    """Concatenate all JavaScript sections."""
    return (JS_CORE + JS_OWL + JS_SIDEBAR + JS_TABLE +
            JS_EXPERIMENTS + JS_INLINE_EDIT + JS_DETAIL +
            JS_COMPARE + JS_MUTATIONS + JS_TIMELINE +
            JS_GROUPS + JS_INIT)
