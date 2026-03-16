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
let studyFilter = '';
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
  {id: 'pin', label: '', sortable: false, defaultOn: true, width: 32},
  {id: 'cb', label: '', sortable: false, defaultOn: true, width: 36},
  {id: 'id', label: 'ID', sortable: true, defaultOn: true, width: 60},
  {id: 'name', label: 'Name', sortable: true, defaultOn: true, width: 180},
  {id: 'status', label: 'Status', sortable: true, defaultOn: true, width: 70},
  {id: 'tags', label: 'Tags', sortable: true, defaultOn: true, width: 120},
  {id: 'studies', label: 'Studies', sortable: true, defaultOn: true, width: 120},
  {id: 'stage', label: 'Stage', sortable: true, defaultOn: true, width: 120},
  {id: 'notes', label: 'Notes', sortable: false, defaultOn: true, width: 200},
  {id: 'metrics', label: 'Metrics', sortable: false, defaultOn: true, width: 160},
  {id: 'changes', label: 'Changes', sortable: false, defaultOn: false, width: 100},
  {id: 'started', label: 'Started', sortable: true, defaultOn: true, width: 140},
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
      html += '<th class="sortable" style="width:' + w + 'px;min-width:50px;position:relative" onclick="toggleSort(\'' + (colId === 'started' ? 'created_at' : colId) + '\')">' + col.label + '<span class="sort-arrow"></span>' + resizer + '</th>';
    } else {
      html += '<th style="width:' + w + 'px;min-width:50px;position:relative">' + col.label + resizer + '</th>';
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
    const cardStudiesHtml = (e.studies||[]).length ? '<div class="exp-card-tags">' + (e.studies||[]).map(g=>'<span class="tag" style="background:rgba(44,90,160,0.1);color:var(--blue)">'+esc(g)+'</span>').join('') + '</div>' : '';
    const cardHl = getHighlightStudy(e);
    const cardHlStyle = cardHl ? ' style="border-left:3px solid ' + cardHl.border + ';background:' + cardHl.bg + '"' : '';
    return '<div class="exp-card' + active + '"' + cardHlStyle + ' onclick="showDetail(\'' + e.id + '\')">' +
      '<div class="exp-card-row1">' + cbHtml +
      '<span class="status-dot ' + statusCls + '"></span>' +
      '<span class="exp-card-name" ondblclick="event.stopPropagation();startInlineRename(\'' + e.id + '\',this)">' + esc(e.name) + '</span></div>' +
      '<div class="exp-card-meta">' +
        esc(e.git_branch || '') + ' &middot; ' + fmtDur(e.duration_s) + ' &middot; ' + fmtDt(e.created_at) +
      '</div>' +
      (metrics ? '<div class="exp-card-metrics">' + esc(metrics) + '</div>' : '') +
      tagsHtml + cardStudiesHtml +
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
  if (n >= 2) {
    html += '<button class="primary" onclick="compareSelected()">Compare (' + n + ')</button>';
  } else if (n === 1) {
    html += '<button class="primary" style="opacity:0.5" disabled title="Select 2+ to compare">Compare (need 2+)</button>';
  }
  html += '<button class="export-btn" onclick="promptBulkAddToStudy()">Add to Study</button>';
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
  if (n >= 2) {
    html += '<button class="primary" onclick="compareSelected()">Compare (' + n + ')</button>';
  }
  html += '<button onclick="promptBulkAddToStudy()">Add to Study</button>';
  html += _buildExportDropdown(n);
  html += _buildCopyDropdown(n);
  html += '<button class="danger" onclick="sidebarBulkDelete()">Delete (' + n + ')</button>';
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
  if (d.studies && d.studies.length) lines.push('Studies: ' + d.studies.join(', '));
  if (d.stage != null) lines.push('Stage: ' + d.stage + (d.stage_name ? ' (' + d.stage_name + ')' : ''));
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
  if (studyFilter) {
    exps = exps.filter(e => (e.studies || []).includes(studyFilter));
  }
  if (searchQuery) {
    const q = searchQuery.toLowerCase();
    exps = exps.filter(e =>
      e.name.toLowerCase().includes(q) ||
      e.id.toLowerCase().includes(q) ||
      (e.tags || []).some(t => t.toLowerCase().includes(q)) ||
      (e.studies || []).some(g => g.toLowerCase().includes(q)) ||
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
      case 'studies': av = (a.studies||[]).length; bv = (b.studies||[]).length; break;
      case 'stage': av = a.stage != null ? a.stage : Infinity; bv = b.stage != null ? b.stage : Infinity; break;
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
  if (highlightMode) { buildHighlightColors(); renderHighlightLegend(); }
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

function miniSpark(values) {
  if (!values || values.length < 2) return '';
  const w = 40, h = 14;
  const min = Math.min(...values), max = Math.max(...values);
  const range = max - min || 1;
  const points = values.map((v, i) =>
    (i * w / (values.length - 1)).toFixed(1) + ',' + (h - (v - min) / range * h).toFixed(1)
  ).join(' ');
  return '<svg width="'+w+'" height="'+h+'" style="vertical-align:middle;margin-left:4px"><polyline points="'+points+'" fill="none" stroke="var(--blue)" stroke-width="1.2"/></svg>';
}

function renderExpRow(e) {
  const isSelected = selectedIds.has(e.id);
  const isPinned = pinnedIds.has(e.id);
  const hlStudy = getHighlightStudy(e);
  const rowCls = (isSelected ? 'selected-row' : '') + (isPinned ? ' pinned-row' : '') + (hlStudy ? ' highlighted-row' : '');
  const rowStyle = hlStudy ? ' style="background:' + hlStudy.bg + '"' : '';
  const hlBorder = hlStudy ? ' style="border-left:3px solid ' + hlStudy.border + '"' : '';
  const editIcon = '<span class="edit-icon" title="Click to edit">&#9998;</span>';

  // Pre-compute cell content for all possible columns
  const cells = {
    pin: '<td' + hlBorder + ' onclick="event.stopPropagation()"><button class="pin-btn' + (isPinned?' pinned':'') + '" onclick="togglePin(\'' + e.id + '\')" title="' + (isPinned?'Unpin':'Pin') + '">' + (isPinned?'\u2605':'\u2606') + '</button></td>',
    cb: '<td onclick="event.stopPropagation()"><label style="display:flex;align-items:center;justify-content:center;cursor:pointer;padding:4px"><input type="checkbox" ' + (isSelected?'checked':'') + ' onclick="toggleSelection(\'' + e.id + '\')" title="Select" style="cursor:pointer"></label></td>',
    id: '<td class="truncate-cell">' + e.id.slice(0,6) + '</td>',
    name: '<td class="truncate-cell"><span class="editable-cell" onclick="event.stopPropagation();cancelRowClick();startInlineRename(\'' + e.id + '\',this)">' + esc(e.name.slice(0,45)) + editIcon + '</span></td>',
    status: '<td class="truncate-cell status-' + e.status + '">' + e.status + '</td>',
    tags: '<td class="tags-cell wrap-cell editable-cell" onclick="event.stopPropagation();cancelRowClick();startInlineTag(\'' + e.id + '\',this)">' + ((e.tags||[]).map(t=>'<span class="tag">#'+esc(t)+'</span>').join('') || '<span style="color:var(--muted)">--</span>') + editIcon + '</td>',
    studies: '<td class="tags-cell wrap-cell editable-cell" onclick="event.stopPropagation();cancelRowClick();startInlineStudy(\'' + e.id + '\',this)">' + ((e.studies||[]).map(g=>'<span class="tag" style="background:rgba(44,90,160,0.1);color:var(--blue)">'+esc(g)+'</span>').join('') || '<span style="color:var(--muted)">--</span>') + editIcon + '</td>',
    stage: '<td class="wrap-cell stage-cell editable-cell" onclick="event.stopPropagation();cancelRowClick();startInlineStage(\'' + e.id + '\',this)">' + (e.stage != null ? '<span style="font-weight:600">' + esc(String(e.stage)) + '</span>' + (e.stage_name ? ' <span style="color:var(--muted)">\u00b7</span> <span style="color:var(--muted)">' + esc(e.stage_name) + '</span>' : '') : '<span style="color:var(--muted)">--</span>') + editIcon + '</td>',
    notes: '<td class="truncate-cell notes-cell-expanded editable-cell" title="' + esc(e.notes||'') + '" onclick="event.stopPropagation();cancelRowClick();startInlineNote(\'' + e.id + '\',this)">' + (e.notes ? esc(e.notes.split('\n')[0].slice(0,60)) : '<span style="color:var(--muted)">--</span>') + editIcon + '</td>',
    metrics: (function() {
      const parts = [];
      for (const [k, m] of Object.entries(e.metrics || {}).slice(0, 3)) {
        const v = typeof m === 'object' ? m.value : m;
        const src = typeof m === 'object' ? m.source : 'auto';
        const color = src === 'manual' ? 'var(--tl-metric)' : src === 'pipeline' ? 'var(--green)' : 'var(--blue)';
        parts.push('<span style="color:' + color + '" title="' + esc(k) + ' (' + src + ')">' + esc(abbrevMetric(k).split('/').pop()) + '</span>=' + (typeof v === 'number' ? v.toFixed(3) : esc(String(v))) + miniSpark((e.sparklines||{})[k]));
      }
      return '<td class="truncate-cell" style="font-size:13px">' + (parts.join(', ') || '<span style="color:var(--muted)">--</span>') + '</td>';
    })(),
    changes: (function() {
      const codeParams = Object.keys(e.params || {}).filter(k => k.startsWith('_code_change/') || k === '_code_changes');
      if (!codeParams.length) return '<td class="truncate-cell">--</td>';
      let added = 0, removed = 0;
      for (const k of codeParams) { const v = String(e.params[k] || ''); for (const p of v.split('; ')) { if (p.trim().startsWith('+')) added++; else if (p.trim().startsWith('-')) removed++; } }
      let s = '<span class="code-stat">' + codeParams.length + ' file' + (codeParams.length>1?'s':'');
      if (added || removed) s += ' <span class="lines-added">+' + added + '</span> <span class="lines-removed">-' + removed + '</span>';
      return '<td class="truncate-cell">' + s + '</span></td>';
    })(),
    started: '<td class="truncate-cell">' + fmtDt(e.created_at) + '</td>',
  };

  let tds = '';
  for (const colId of visibleCols) { tds += cells[colId] || ''; }
  return '<tr class="' + rowCls + '"' + rowStyle + ' onclick="onRowClick(\'' + e.id + '\')">' + tds + '</tr>';
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
    html += '<tr class="group-header" onclick="toggleGroup(\'' + esc(key) + '\')"><td colspan="' + visibleCols.length + '">';
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

// ── Inline rename ────────────────────────────────────────────────────────────
function startInlineRename(id, el) {
  // Strip edit icon text from the element content
  const iconEl = el.querySelector('.edit-icon');
  const currentName = iconEl ? el.textContent.replace(iconEl.textContent, '').trim() : el.textContent.trim();
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

// ── Unified item autocomplete helper (tags & studies) ────────────────────────
function createItemInput(id, items, exp, onUpdate, opts = {}) {
  // opts.kind: 'tag' or 'study'
  // opts.allKnown: allKnownTags or allKnownStudies
  // opts.apiAdd: e.g. '/tag' or '/study'
  // opts.bodyKey: e.g. 'tag' or 'study'
  // opts.expKey: e.g. 'tags' or 'studies'
  // opts.loadAll: e.g. loadAllTags or loadAllStudies
  // opts.prefix: display prefix, e.g. '#' for tags, '' for studies
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
function createStudyInput(id, studies, exp, onUpdate, opts = {}) {
  return createItemInput(id, studies, exp, onUpdate, Object.assign({
    kind: 'study', allKnown: allKnownStudies, apiAdd: '/study', bodyKey: 'study',
    expKey: 'studies', loadAll: loadAllStudies, prefix: ''
  }, opts));
}

// ── Unified inline item editing (tags & studies) ─────────────────────────────
function startInlineItems(id, el, opts) {
  // opts.expKey: 'tags' or 'studies'
  // opts.prefix: '#' or ''
  // opts.chipStyle: extra CSS for chips
  // opts.deleteApi: e.g. '/delete-tag' or '/delete-study'
  // opts.deleteBodyKey: e.g. 'tag' or 'study'
  // opts.createInput: createTagInput or createStudyInput
  // opts.loadAll: loadAllTags or loadAllStudies
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

function startInlineStudy(id, el) {
  startInlineItems(id, el, {
    expKey: 'studies', prefix: '', chipStyle: 'background:rgba(44,90,160,0.1);color:var(--blue)',
    deleteApi: '/delete-study', deleteBodyKey: 'study',
    createInput: createStudyInput, loadAll: loadAllStudies
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
  if (selectedIds.size < 2) return;
  owlSpeak('compare');
  showCompareView();
  const ids = [...selectedIds];
  if (ids.length === 2) {
    // Pair compare
    document.getElementById('compare-pair-tab').classList.add('active');
    document.getElementById('compare-multi-tab').classList.remove('active');
    document.getElementById('compare-pair-content').style.display = '';
    document.getElementById('compare-multi-content').style.display = 'none';
    await populateCompareDropdowns();
    document.getElementById('cmp-id1').value = ids[0];
    document.getElementById('cmp-id2').value = ids[1];
    doCompare();
  } else {
    // Multi compare
    document.getElementById('compare-pair-tab').classList.remove('active');
    document.getElementById('compare-multi-tab').classList.add('active');
    document.getElementById('compare-pair-content').style.display = 'none';
    document.getElementById('compare-multi-content').style.display = '';
    await populateMultiCompareSelector();
    doMultiCompare(ids);
  }
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
  if (['log','txt','out','err'].includes(ext)) return '<span class="artifact-type-badge log">log</span>';
  if (!ext || path.indexOf('.') === -1) return '<span class="artifact-type-badge dir">dir</span>';
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
    } else if (k.startsWith('_result:')) {
      // Legacy _result:* params — skip (migrated to metrics table)
    } else if (k === '_script_hash' || k === '_cells_ran' || k === '_result_source') {
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

  // Build unified metrics rows grouped by prefix (train/*, test/*, val/*, etc.)
  function buildMetricRow(m, showFullKey) {
    const src = m.source || 'auto';
    const isManual = src === 'manual';
    const keyColor = isManual ? 'var(--tl-metric)' : 'var(--green)';
    const delBtn = `<span class="result-del-x" onclick="event.stopPropagation();deleteMetric('${exp.id}','${esc(m.key)}')" title="Delete all">&times;</span>`;
    const editAttr = isManual ? ` class="editable-hint" ondblclick="startResultEdit('${exp.id}','${esc(m.key)}',this)" title="Double-click to edit"` : '';
    const displayKey = showFullKey ? abbrevMetric(m.key) : abbrevMetric(m.key.includes('/') ? m.key.split('/').slice(1).join('/') : m.key);
    return `<tr><td style="color:${keyColor}" class="editable-hint" ondblclick="startMetricRename('${exp.id}','${esc(m.key)}',this)" title="${esc(m.key)} — double-click to rename">${esc(displayKey)}</td><td${editAttr}>${m.last?.toFixed(4) ?? '--'}</td><td>${isManual ? '--' : (m.min?.toFixed(4) ?? '--')}</td><td>${isManual ? '--' : (m.max?.toFixed(4) ?? '--')}</td><td>${m.n}</td><td><span class="source-badge ${src}">${src}</span> ${delBtn}</td></tr>`;
  }
  // Group metrics by prefix
  const metricGroups = {};
  for (const m of exp.metrics) {
    const slashIdx = m.key.indexOf('/');
    const group = slashIdx > 0 ? m.key.slice(0, slashIdx) : '';
    (metricGroups[group] = metricGroups[group] || []).push(m);
  }
  const groupKeys = Object.keys(metricGroups).sort((a, b) => a === '' ? 1 : b === '' ? -1 : a.localeCompare(b));
  let metricRows = '';
  const thead = '<tr><th>Key</th><th>Last</th><th>Min</th><th>Max</th><th>Count</th><th>Source</th></tr>';
  if (groupKeys.length <= 1) {
    // No grouping needed — single flat table, show abbreviated full key
    metricRows = exp.metrics.map(m => buildMetricRow(m, true)).join('');
    if (metricRows) metricRows = '<table class="metrics-table">' + thead + metricRows + '</table>';
  } else {
    // Grouped tables with prefix headers
    for (const g of groupKeys) {
      const label = g || 'Other';
      const items = metricGroups[g];
      metricRows += '<div class="metric-group"><h3 class="metric-group-header" onclick="this.parentElement.classList.toggle(\'collapsed\')">' + esc(label) + ' <span style="font-weight:normal;font-size:12px">(' + items.length + ')</span></h3>';
      metricRows += '<table class="metrics-table">' + thead;
      for (const m of items) metricRows += buildMetricRow(m);
      metricRows += '</table></div>';
    }
  }

  const artRows = exp.artifacts.map(a => {
    const ext = (a.path || '').split('.').pop().toLowerCase();
    const isLog = ['log', 'txt', 'out', 'err'].includes(ext);
    const isData = ['csv', 'json', 'jsonl'].includes(ext);
    const viewBtn = (isLog || isData)
      ? `<button onclick="viewLogFile('${esc(a.path)}','${esc(a.label)}')" title="View contents">view</button>`
      : '';
    return `<tr><td><div class="artifact-row">${artifactTypeBadge(a.path)} ${esc(a.label)}</div></td><td style="font-size:12px;color:var(--muted)">${esc(a.path)}</td><td><div class="artifact-actions">${viewBtn}<button onclick="editArtifact('${exp.id}','${esc(a.label)}','${esc(a.path)}')">edit</button><button class="art-del" onclick="deleteArtifact('${exp.id}','${esc(a.label)}','${esc(a.path)}')">del</button></div></td></tr>`;
  }).join('');

  const addArtifactForm = `<div class="artifact-add-form" id="add-artifact-form-${exp.id}">
    <input type="text" id="art-label-${exp.id}" placeholder="Label (e.g. model_v2)" style="width:210px">
    <input type="text" id="art-path-${exp.id}" placeholder="Path (e.g. outputs/model.pt)" style="width:280px">
    <button onclick="addArtifact('${exp.id}')">+ Add Artifact</button>
  </div>`;

  const logResultForm = `<div class="artifact-add-form" style="margin-top:8px;align-items:center;gap:4px" id="log-result-form-${exp.id}">
    <input type="text" id="result-key-${exp.id}" list="metric-suggestions-${exp.id}" placeholder="Metric key" style="width:150px" autocomplete="off">
    <datalist id="metric-suggestions-${exp.id}"></datalist>
    <input type="text" id="result-val-${exp.id}" placeholder="Value" style="width:80px" onkeydown="if(event.key==='Enter')logMetric('${exp.id}')">
    <input type="text" id="result-step-${exp.id}" placeholder="Step" style="width:55px;font-size:12px" title="Optional step number">
    <button onclick="logMetric('${exp.id}')">+ Log</button>
    <button onclick="openManageResultTypes()" style="background:transparent;color:var(--muted);border:none;font-size:16px;padding:0 4px;cursor:pointer;line-height:1" title="Manage metric types">&#9881;</button>
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
  let diffCompacted = false;
  if (diffData.diff) {
    if (diffData.diff.startsWith('[compacted')) {
      diffCompacted = true;
      diffHtml = '<div style="padding:16px;color:var(--yellow,#e8a735);font-style:italic">'
        + esc(diffData.diff)
        + (diffData.commit ? '<br><span style="color:var(--muted);font-size:12px">To recover: git diff ' + esc(diffData.commit) + '~1 ' + esc(diffData.commit) + '</span>' : '')
        + '</div>';
    } else {
      diffHtml = diffData.diff.split('\n').map(line => {
        if (line.startsWith('+') && !line.startsWith('+++')) return '<span class="diff-add">' + esc(line) + '</span>';
        if (line.startsWith('-') && !line.startsWith('---')) return '<span class="diff-del">' + esc(line) + '</span>';
        if (line.startsWith('@@')) return '<span class="diff-hunk">' + esc(line) + '</span>';
        return esc(line);
      }).join('\n');
    }
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

  const expStudies = exp.studies || [];
  const studiesDetailHtml = '<span class="detail-tags-inline" id="detail-studies-area">' +
    (expStudies.length
      ? expStudies.map(g => '<span class="tag-removable" style="background:rgba(44,90,160,0.1);color:var(--blue)">' + esc(g) +
        ' <span class="tag-delete" onclick="event.stopPropagation();deleteStudyInline(\'' + exp.id + '\',\'' + esc(g) + '\')" title="Remove study">&times;</span>' +
        '</span>').join('')
      : '') +
    '<span class="tag-input-area" id="detail-study-input-area"></span>' +
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
        <button class="tab" onclick="switchDetailTab('logs','${exp.id}')">Data Files</button>
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
              <span class="label">Studies</span><span class="tag-list" id="detail-studies">${studiesDetailHtml}</span>
              <span class="label">Stage</span><span id="detail-stage" class="editable-hint" ondblclick="startDetailStageEdit('${exp.id}',this)" title="Double-click to edit stage">${exp.stage != null ? esc(String(exp.stage)) + (exp.stage_name ? ' (' + esc(exp.stage_name) + ')' : '') : '<span style="color:var(--muted)">click to set stage</span>'}</span>
              <span class="label">Notes</span><span id="detail-notes" class="detail-notes-inline editable-hint" ondblclick="startDetailNoteEdit('${exp.id}',this)" title="Double-click to edit">${exp.notes ? esc(exp.notes) : '<span style="color:var(--muted)">double-click to add notes</span>'}</span>
            </div>
            ${exp.command ? '<div class="reproduce-box"><div class="reproduce-header"><span class="label">Reproduce</span><button class="copy-btn" data-cmd="' + esc(exp.command).replace(/"/g,'&quot;') + '" onclick="navigator.clipboard.writeText(this.dataset.cmd).then(()=>owlSay(\'Copied!\'))">Copy</button></div><code class="reproduce-cmd">' + esc(exp.command) + '</code></div>' : ''}
            ${paramRows ? '<h2 class="section-toggle" onclick="this.classList.toggle(\'collapsed\')">Params (' + Object.keys(regularParams).length + ')</h2><div class="section-body"><table class="params-table"><tr><th>Key</th><th>Value</th></tr>'+paramRows+'</table></div>' : ''}
            ${varHtml}
          </div>
          <!-- Right column: metrics + charts + artifacts -->
          <div>
            <h2 class="section-toggle" onclick="this.classList.toggle('collapsed')">Metrics (${exp.metrics.length})</h2>
            <div class="section-body">
            ${metricRows || '<p style="color:var(--muted);font-size:13px">No metrics yet.</p>'}
            ${logResultForm}
            <div id="charts-container"></div>
            </div>
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
          ${diffHtml ? '<h2 class="section-toggle" onclick="this.classList.toggle(\'collapsed\')">'+(diffCompacted ? 'Git Diff (compacted)' : 'Git Diff ('+exp.diff_lines+' lines)')+'</h2><div class="section-body"><div class="diff-view">'+diffHtml+'</div></div>' : ''}
        </div>
      </div>

      <div id="detail-tab-timeline" style="display:none"></div>
      <div id="detail-tab-images" style="display:none"></div>
      <div id="detail-tab-logs" style="display:none"></div>
      <div id="detail-tab-compare-within" style="display:none"></div>
    </div>
  `;

  // Wire up inline tag input in detail view
  const tagInputArea = document.getElementById('detail-tag-input-area');
  if (tagInputArea) {
    const detailTags = [...(exp.tags || [])];
    const { wrapper, input } = createTagInput(exp.id, detailTags, null, () => {
      loadExperiments().then(() => refreshDetail(exp.id));
    }, { placeholder: '+ add tag', style: 'width:120px;font-size:13px;padding:4px 6px' });
    tagInputArea.appendChild(wrapper);
  }

  // Wire up inline study input in detail view
  const studyInputArea = document.getElementById('detail-study-input-area');
  if (studyInputArea) {
    const detailStudies = [...(exp.studies || [])];
    const { wrapper: sWrapper, input: sInput } = createStudyInput(exp.id, detailStudies, null, () => {
      loadExperiments().then(() => refreshDetail(exp.id));
    }, { placeholder: '+ add study', style: 'width:130px;font-size:13px;padding:4px 6px' });
    studyInputArea.appendChild(sWrapper);
  }

  // Render metric charts (click a point to delete it)
  Object.values(charts).forEach(c => c.destroy());
  charts = {};
  const container = document.getElementById('charts-container');
  for (const [key, points] of Object.entries(metricsData)) {
    if (points.length < 1) continue;
    const div = document.createElement('div');
    div.className = 'chart-container';
    const canvas = document.createElement('canvas');
    div.appendChild(canvas);
    container.appendChild(div);
    const chartPoints = points.map((p,i) => ({ x: p.step !== null ? p.step : i, y: p.value, _step: p.step }));
    charts[key] = new Chart(canvas, {
      type: 'line',
      data: {
        labels: points.map((p,i) => p.step !== null ? p.step : i),
        datasets: [{
          label: key,
          data: points.map(p => p.value),
          borderColor: '#2c5aa0',
          backgroundColor: 'rgba(44,90,160,0.1)',
          fill: true, tension: 0.3, pointRadius: 4, pointHoverRadius: 7,
          pointHitRadius: 10,
        }]
      },
      options: {
        responsive: true,
        plugins: {
          legend: { display: true, labels: { font: { family: "'IBM Plex Mono'" } } },
          tooltip: {
            callbacks: {
              afterLabel: () => 'Click to delete this point'
            }
          }
        },
        scales: {
          x: { title: { display: true, text: 'Step', font: { family: "'IBM Plex Mono'" } } },
          y: { title: { display: true, text: key, font: { family: "'IBM Plex Mono'" } } }
        },
        onClick: (evt, elements) => {
          if (!elements.length) return;
          const idx = elements[0].index;
          const pt = points[idx];
          const step = pt.step;
          const val = pt.value;
          if (confirm('Delete point: ' + key + ' = ' + val + ' (step ' + (step ?? idx) + ')?')) {
            deleteMetricPoint(currentDetailId, key, step ?? idx);
          }
        }
      }
    });
  }

  // Populate result type dropdown
  populateResultTypeDropdown(exp.id);
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
let compareCharts = {};

function switchCompareTab(tab) {
  document.getElementById('compare-pair-tab').classList.toggle('active', tab === 'pair');
  document.getElementById('compare-multi-tab').classList.toggle('active', tab === 'multi');
  document.getElementById('compare-pair-content').style.display = tab === 'pair' ? '' : 'none';
  document.getElementById('compare-multi-content').style.display = tab === 'multi' ? '' : 'none';
  if (tab === 'pair') populateCompareDropdowns();
  if (tab === 'multi') populateMultiCompareSelector();
}

async function populateMultiCompareSelector() {
  const exps = await api('/api/experiments?limit=100');
  const sel = document.getElementById('cmp-multi-select');
  sel.innerHTML = exps.map(e =>
    '<option value="' + e.id + '"' + (selectedIds.has(e.id) ? ' selected' : '') + '>' +
    e.id.slice(0,6) + ' | ' + esc(e.name.slice(0,35)) + ' | ' + e.status + ' | ' + fmtDt(e.created_at) + '</option>'
  ).join('');
}

function doMultiCompareFromSelector() {
  const sel = document.getElementById('cmp-multi-select');
  const ids = [...sel.selectedOptions].map(o => o.value);
  if (ids.length < 2) { owlSay('Select at least 2 experiments'); return; }
  doMultiCompare(ids);
}

function selectAllMultiCompare() {
  const sel = document.getElementById('cmp-multi-select');
  for (const opt of sel.options) opt.selected = true;
}

async function doCompare() {
  Object.values(compareCharts).forEach(c => c.destroy());
  compareCharts = {};
  const id1 = document.getElementById('cmp-id1').value.trim();
  const id2 = document.getElementById('cmp-id2').value.trim();
  if (!id1 || !id2) return;
  const data = await api('/api/compare?id1=' + id1 + '&id2=' + id2);
  if (data.error || data.exp1?.error || data.exp2?.error) {
    document.getElementById('compare-result').innerHTML = '<p>One or both experiments not found.</p>';
    return;
  }
  const e1 = data.exp1, e2 = data.exp2;
  const isUserParam = k => !k.startsWith('_code_change') && k !== '_code_changes' && !k.startsWith('_var/') && k !== '_script_hash' && k !== '_cells_ran' && k !== '_tags' && !k.startsWith('_result:');
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

  // Unified metrics comparison (all sources now in metrics table)
  const allUnifiedKeys = [...allMKeys];
  // Build source maps from metrics data
  const src1 = Object.fromEntries(e1.metrics.map(m => [m.key, m.source || 'auto']));
  const src2 = Object.fromEntries(e2.metrics.map(m => [m.key, m.source || 'auto']));

  if (allUnifiedKeys.length) {
    html += '<details open><summary style="cursor:pointer;font-size:16px;font-weight:600;margin:12px 0">Metrics</summary><table class="metrics-table"><tr><th>Key</th><th>' + esc(n1) + '</th><th>' + esc(n2) + '</th><th>Delta</th><th>Source</th></tr>';
    for (const k of allUnifiedKeys) {
      const v1 = m1[k], v2 = m2[k];
      const sv1 = v1 !== undefined ? (typeof v1 === 'number' ? v1.toFixed(4) : String(v1)) : '--';
      const sv2 = v2 !== undefined ? (typeof v2 === 'number' ? v2.toFixed(4) : String(v2)) : '--';
      let delta = '';
      if (v1 !== undefined && v2 !== undefined && typeof v1 === 'number' && typeof v2 === 'number') {
        const d = v2 - v1;
        if (onlyDiffers && Math.abs(d) < 0.0001) continue;
        const arrow = d > 0 ? '&#x25B2;' : d < 0 ? '&#x25BC;' : '';
        delta = '<span style="color:' + (d>0?'var(--green,#3fb950)':'var(--red,#f85149)') + '">' + arrow + ' ' + (d>0?'+':'') + d.toFixed(4) + '</span>';
      }
      const ks1 = src1[k] || 'auto', ks2 = src2[k] || 'auto';
      const source = ks1 === ks2 ? '<span class="source-badge ' + ks1 + '">' + ks1 + '</span>' : '<span class="source-badge ' + ks1 + '">' + ks1 + '</span> / <span class="source-badge ' + ks2 + '">' + ks2 + '</span>';
      html += '<tr><td>' + esc(k) + '</td><td>' + sv1 + '</td><td>' + sv2 + '</td><td>' + delta + '</td><td>' + source + '</td></tr>';
    }
    html += '</table></details>';
  }

  // Overlay metric charts
  const [metricsSeries1, metricsSeries2] = await Promise.all([
    api('/api/metrics/' + id1),
    api('/api/metrics/' + id2),
  ]);
  const sharedMKeys = allMKeys.filter(k => metricsSeries1[k] && metricsSeries2[k] && (metricsSeries1[k].length > 1 || metricsSeries2[k].length > 1));
  if (sharedMKeys.length) {
    html += '<details open><summary style="cursor:pointer;font-size:16px;font-weight:600;margin:12px 0">Metric Charts</summary><div class="compare-charts-grid">';
    for (const k of sharedMKeys) {
      html += '<div class="chart-container"><canvas id="cmp-chart-' + k.replace(/[^a-zA-Z0-9]/g,'_') + '"></canvas></div>';
    }
    html += '</div></details>';
  }

  // ── Image comparison section ──
  crossCmpA = null; crossCmpB = null;
  const [imgData1, imgData2] = await Promise.all([
    api('/api/images/' + id1),
    api('/api/images/' + id2),
  ]);
  const imgs1 = (imgData1.images || []);
  const imgs2 = (imgData2.images || []);

  if (imgs1.length || imgs2.length) {
    html += '<details open><summary style="cursor:pointer;font-size:16px;font-weight:600;margin:12px 0">Images</summary>';
    html += '<div class="compare-images-section">';
    html += '<div class="compare-images-cols">';

    // Left column
    html += '<div class="compare-images-col"><h4>' + esc(n1) + ' (' + imgs1.length + ')</h4>';
    if (imgs1.length) {
      html += '<div class="cmp-img-grid">';
      for (const img of imgs1.slice(0, 60)) {
        const src = '/api/file/' + encodeURIComponent(img.path).replace(/%2F/g, '/');
        html += '<div class="cmp-img-thumb" data-side="1" data-src="' + esc(src) + '" onclick="selectCrossImg(\'' + esc(src) + '\',\'' + esc(img.name) + '\',1)">';
        html += '<img src="' + src + '" loading="lazy" alt="' + esc(img.name) + '">';
        html += '<div class="cmp-thumb-name">' + esc(img.name) + '</div>';
        html += '</div>';
      }
      html += '</div>';
    } else {
      html += '<p style="color:var(--muted);font-size:12px">No image paths configured. Set them in the experiment\'s Images tab.</p>';
    }
    html += '</div>';

    // Right column
    html += '<div class="compare-images-col"><h4>' + esc(n2) + ' (' + imgs2.length + ')</h4>';
    if (imgs2.length) {
      html += '<div class="cmp-img-grid">';
      for (const img of imgs2.slice(0, 60)) {
        const src = '/api/file/' + encodeURIComponent(img.path).replace(/%2F/g, '/');
        html += '<div class="cmp-img-thumb" data-side="2" data-src="' + esc(src) + '" onclick="selectCrossImg(\'' + esc(src) + '\',\'' + esc(img.name) + '\',2)">';
        html += '<img src="' + src + '" loading="lazy" alt="' + esc(img.name) + '">';
        html += '<div class="cmp-thumb-name">' + esc(img.name) + '</div>';
        html += '</div>';
      }
      html += '</div>';
    } else {
      html += '<p style="color:var(--muted);font-size:12px">No image paths configured. Set them in the experiment\'s Images tab.</p>';
    }
    html += '</div></div>';

    // Selection bar
    html += '<div class="compare-select-bar" id="cross-cmp-bar">';
    html += '<span class="cmp-sel-a">A: (none)</span>';
    html += '<span style="color:var(--muted)">vs</span>';
    html += '<span class="cmp-sel-b">B: (none)</span>';
    html += '<button class="cmp-compare-btn" onclick="doCrossCompare()" disabled>Compare</button>';
    html += '<button class="cmp-clear-btn" onclick="clearCrossCompare()">Clear</button>';
    html += '</div>';

    html += '</div></details>';
  }

  document.getElementById('compare-result').innerHTML = html;

  // Create overlay charts for shared metrics
  for (const k of sharedMKeys) {
    const canvasId = 'cmp-chart-' + k.replace(/[^a-zA-Z0-9]/g,'_');
    const canvas = document.getElementById(canvasId);
    if (!canvas) continue;
    const pts1 = metricsSeries1[k] || [];
    const pts2 = metricsSeries2[k] || [];
    const maxLen = Math.max(pts1.length, pts2.length);
    const labels = Array.from({length: maxLen}, (_, i) => {
      const p = pts1[i] || pts2[i];
      return p && p.step !== null ? p.step : i;
    });
    compareCharts[k] = new Chart(canvas, {
      type: 'line',
      data: {
        labels: labels,
        datasets: [{
          label: n1,
          data: pts1.map(p => p.value),
          borderColor: '#2c5aa0',
          backgroundColor: 'rgba(44,90,160,0.1)',
          fill: false, tension: 0.3, pointRadius: 2,
        }, {
          label: n2,
          data: pts2.map(p => p.value),
          borderColor: '#2d7d46',
          backgroundColor: 'rgba(45,125,70,0.1)',
          fill: false, tension: 0.3, pointRadius: 2,
        }]
      },
      options: {
        responsive: true,
        plugins: { legend: { display: true, labels: { font: { family: "'IBM Plex Mono'" } } } },
        scales: {
          x: { title: { display: true, text: 'Step', font: { family: "'IBM Plex Mono'" } } },
          y: { title: { display: true, text: k, font: { family: "'IBM Plex Mono'" } } }
        }
      }
    });
  }
}

// ── Multi Compare ───────────────────────────────────────────────────────────

const MULTI_COLORS = ['#2c5aa0','#2d7d46','#c0392b','#7c3aed','#d4820f','#1abc9c','#e74c3c','#3498db','#9b59b6','#f39c12'];
let multiCharts = {};

async function doMultiCompare(ids) {
  Object.values(multiCharts).forEach(c => c.destroy());
  multiCharts = {};
  if (!ids || ids.length < 2) {
    ids = [...selectedIds];
  }
  if (ids.length < 2) return;

  const data = await api('/api/multi-compare?ids=' + ids.join(','));
  if (data.error || !data.experiments || !data.experiments.length) {
    document.getElementById('multi-compare-result').innerHTML = '<p>Could not load experiments.</p>';
    return;
  }
  const exps = data.experiments;
  // Collect all unique metric keys
  const allKeys = new Set();
  for (const e of exps) {
    for (const k of Object.keys(e.metrics || {})) allKeys.add(k);
  }
  const keys = [...allKeys].sort();

  // Summary table
  let html = '<details open><summary style="cursor:pointer;font-size:16px;font-weight:600;margin:12px 0">Comparison Table</summary>';
  html += '<div style="overflow-x:auto"><table class="metrics-table"><tr><th>Key</th>';
  for (const e of exps) {
    const name = e.name.length > 20 ? e.name.slice(0,17) + '...' : e.name;
    html += '<th>' + esc(name) + '</th>';
  }
  html += '</tr>';
  for (const k of keys) {
    html += '<tr><td>' + esc(k) + '</td>';
    for (const e of exps) {
      const v = e.metrics[k];
      html += '<td>' + (v !== undefined ? (typeof v === 'number' ? v.toFixed(4) : esc(String(v))) : '--') + '</td>';
    }
    html += '</tr>';
  }
  html += '</table></div></details>';

  // Bar charts
  if (keys.length) {
    html += '<details open><summary style="cursor:pointer;font-size:16px;font-weight:600;margin:12px 0">Bar Charts</summary><div class="compare-charts-grid">';
    for (const k of keys) {
      html += '<div class="chart-container"><canvas id="multi-chart-' + k.replace(/[^a-zA-Z0-9]/g,'_') + '"></canvas></div>';
    }
    html += '</div></details>';
  }

  document.getElementById('multi-compare-result').innerHTML = html;

  // Create bar charts
  for (const k of keys) {
    const canvasId = 'multi-chart-' + k.replace(/[^a-zA-Z0-9]/g,'_');
    const canvas = document.getElementById(canvasId);
    if (!canvas) continue;
    const labels = exps.map(e => e.name.length > 15 ? e.name.slice(0,12) + '...' : e.name);
    const values = exps.map(e => e.metrics[k] ?? null);
    const colors = exps.map((_, i) => MULTI_COLORS[i % MULTI_COLORS.length]);
    multiCharts[k] = new Chart(canvas, {
      type: 'bar',
      data: {
        labels: labels,
        datasets: [{
          label: k,
          data: values,
          backgroundColor: colors.map(c => c + '33'),
          borderColor: colors,
          borderWidth: 1.5,
        }]
      },
      options: {
        responsive: true,
        plugins: { legend: { display: false } },
        scales: {
          x: { ticks: { font: { family: "'IBM Plex Mono'", size: 11 } } },
          y: { title: { display: true, text: k, font: { family: "'IBM Plex Mono'" } } }
        }
      }
    });
  }
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

function parseCSV(text, delimiter) {
  const rows = [];
  let current = '', inQuote = false, row = [], i = 0;
  while (i < text.length) {
    const ch = text[i];
    if (inQuote) {
      if (ch === '"' && text[i+1] === '"') { current += '"'; i += 2; }
      else if (ch === '"') { inQuote = false; i++; }
      else { current += ch; i++; }
    } else {
      if (ch === '"') { inQuote = true; i++; }
      else if (ch === delimiter) { row.push(current); current = ''; i++; }
      else if (ch === '\n' || (ch === '\r' && text[i+1] === '\n')) { row.push(current); current = ''; rows.push(row); row = []; i += (ch === '\r' ? 2 : 1); }
      else if (ch === '\r') { row.push(current); current = ''; rows.push(row); row = []; i++; }
      else { current += ch; i++; }
    }
  }
  if (current || row.length) { row.push(current); rows.push(row); }
  return rows.filter(r => r.length > 0 && !(r.length === 1 && r[0] === ''));
}

async function viewLogFile(path, label) {
  try {
    const resp = await fetch('/api/file/' + encodeURIComponent(path).replace(/%2F/g, '/'));
    if (!resp.ok) { alert('Could not load file: ' + resp.statusText); return; }
    const text = await resp.text();

    const overlay = document.createElement('div');
    overlay.className = 'img-modal-overlay';
    overlay.onclick = (ev) => { if (ev.target === overlay) overlay.remove(); };

    const content = document.createElement('div');
    content.className = 'img-modal-content';
    content.style.cssText = 'max-width:900px;width:90vw';

    const ext = (path || '').split('.').pop().toLowerCase();
    const isCSV = ext === 'csv';
    const isTSV = ext === 'tsv';
    const isJSON = ext === 'json' || ext === 'jsonl';

    let logHtml = '<div class="img-modal-header">';
    logHtml += '<span class="img-modal-name">' + esc(label) + '</span>';

    if (isCSV || isTSV) {
      // CSV/TSV table rendering
      const delimiter = isTSV ? '\t' : ',';
      const rows = parseCSV(text, delimiter);
      const maxRows = 200;
      const truncated = rows.length > maxRows + 1;
      logHtml += '<span style="color:var(--muted);font-size:12px;margin-left:8px">' + (rows.length - 1) + ' rows' + (truncated ? ' (showing first ' + maxRows + ')' : '') + '</span>';
      logHtml += '<button class="img-modal-close" onclick="this.closest(\'.img-modal-overlay\').remove()">&times;</button>';
      logHtml += '</div>';
      logHtml += '<div style="max-height:70vh;overflow:auto">';
      if (rows.length > 0) {
        logHtml += '<table class="metrics-table" style="font-size:12px;white-space:nowrap">';
        // Header row
        logHtml += '<tr>';
        for (const cell of rows[0]) {
          logHtml += '<th style="position:sticky;top:0;background:var(--card-bg);z-index:1">' + esc(cell) + '</th>';
        }
        logHtml += '</tr>';
        // Data rows
        const displayRows = truncated ? rows.slice(1, maxRows + 1) : rows.slice(1);
        for (const row of displayRows) {
          logHtml += '<tr>';
          for (const cell of row) {
            const num = parseFloat(cell);
            const isNum = !isNaN(num) && cell.trim() !== '';
            logHtml += '<td' + (isNum ? ' style="text-align:right;font-variant-numeric:tabular-nums"' : '') + '>' + esc(cell) + '</td>';
          }
          logHtml += '</tr>';
        }
        logHtml += '</table>';
      }
      logHtml += '</div>';
    } else if (isJSON) {
      // JSON / JSONL rendering
      logHtml += '<button class="img-modal-close" onclick="this.closest(\'.img-modal-overlay\').remove()">&times;</button>';
      logHtml += '</div>';
      let jsonRows = [];
      if (ext === 'jsonl') {
        jsonRows = text.trim().split('\n').filter(l => l.trim()).map(l => { try { return JSON.parse(l); } catch { return null; } }).filter(Boolean);
      } else {
        try {
          const parsed = JSON.parse(text);
          jsonRows = Array.isArray(parsed) ? parsed : [parsed];
        } catch { jsonRows = []; }
      }
      if (jsonRows.length && typeof jsonRows[0] === 'object' && !Array.isArray(jsonRows[0])) {
        const keys = [...new Set(jsonRows.flatMap(r => Object.keys(r)))];
        const maxRows = 200;
        const truncated = jsonRows.length > maxRows;
        logHtml += '<div style="max-height:70vh;overflow:auto">';
        logHtml += '<table class="metrics-table" style="font-size:12px;white-space:nowrap">';
        logHtml += '<tr>' + keys.map(k => '<th style="position:sticky;top:0;background:var(--card-bg);z-index:1">' + esc(k) + '</th>').join('') + '</tr>';
        const display = truncated ? jsonRows.slice(0, maxRows) : jsonRows;
        for (const row of display) {
          logHtml += '<tr>' + keys.map(k => { const v = row[k]; const s = v !== undefined ? String(v) : ''; const num = parseFloat(s); const isNum = !isNaN(num) && s.trim() !== '' && typeof v === 'number'; return '<td' + (isNum ? ' style="text-align:right;font-variant-numeric:tabular-nums"' : '') + '>' + esc(s.slice(0,100)) + '</td>'; }).join('') + '</tr>';
        }
        logHtml += '</table></div>';
      } else {
        // Fallback: pretty-print JSON
        logHtml += '<div class="source-view" style="max-height:70vh;font-size:12px;line-height:1.5"><pre>' + esc(JSON.stringify(jsonRows.length === 1 ? jsonRows[0] : jsonRows, null, 2).slice(0, 50000)) + '</pre></div>';
      }
    } else {
      // Plain text / log rendering (original behavior)
      const lines = text.split('\n');
      const maxLines = 500;
      const truncated = lines.length > maxLines;
      const displayLines = truncated ? lines.slice(-maxLines) : lines;
      const lineNums = displayLines.map((_, i) => (truncated ? lines.length - maxLines + i + 1 : i + 1));
      logHtml += '<span style="color:var(--muted);font-size:12px;margin-left:8px">' + lines.length + ' lines</span>';
      logHtml += '<button class="img-modal-close" onclick="this.closest(\'.img-modal-overlay\').remove()">&times;</button>';
      logHtml += '</div>';
      logHtml += '<div class="source-view" style="max-height:70vh;font-size:12px;line-height:1.5">';
      if (truncated) logHtml += '<div style="color:var(--muted);margin-bottom:8px">Showing last ' + maxLines + ' of ' + lines.length + ' lines</div>';
      for (let i = 0; i < displayLines.length; i++) {
        logHtml += '<div><span class="line-num">' + lineNums[i] + '</span>' + esc(displayLines[i]) + '</div>';
      }
      logHtml += '</div>';
    }

    content.innerHTML = logHtml;
    overlay.appendChild(content);
    document.body.appendChild(overlay);

    const handler = (ev) => { if (ev.key === 'Escape') { overlay.remove(); document.removeEventListener('keydown', handler); } };
    document.addEventListener('keydown', handler);
  } catch(e) {
    alert('Error loading file: ' + e.message);
  }
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
    const tabs = ['overview','timeline','images','logs','compare-within'];
    t.classList.toggle('active', tabs[i] === tab);
  });
  ['overview','timeline','images','logs','compare-within'].forEach(t => {
    const el = document.getElementById('detail-tab-'+t);
    if (el) el.style.display = t === tab ? '' : 'none';
  });
  if (tab === 'timeline') loadTimeline(expId);
  if (tab === 'images') loadImages(expId);
  if (tab === 'logs') loadLogs(expId);
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

    // Compare mode floating bar
    if (imgCmpMode) {
      html += '<div class="img-cmp-floating-bar">';
      html += '<span>A: <strong>' + (imgCmpA ? esc(imgCmpA.name) : '(click to select)') + '</strong></span>';
      html += '<span style="color:var(--muted)">vs</span>';
      html += '<span>B: <strong>' + (imgCmpB ? esc(imgCmpB.name) : '(click to select)') + '</strong></span>';
      html += '<button class="cmp-go" onclick="doIntraCompare()"' + (imgCmpA && imgCmpB ? '' : ' disabled') + '>Compare</button>';
      html += '<button class="cmp-clr" onclick="clearIntraCompare(\'' + expId + '\')">Clear</button>';
      html += '</div>';
    }

    html += '<div class="img-gallery-toolbar">';
    html += '<span style="color:var(--muted);font-size:13px">' + (totalFiltered < images.length ? totalFiltered + ' of ' : '') + images.length + ' image' + (images.length !== 1 ? 's' : '') + '</span>';

    // Compare toggle
    html += ' <button class="img-compare-toggle' + (imgCmpMode ? ' active' : '') + '" onclick="toggleImgCompare(\'' + expId + '\')">' + (imgCmpMode ? 'Cancel Compare' : 'Compare') + '</button>';

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
      const isSelA = imgCmpMode && imgCmpA && imgCmpA.src === src;
      const isSelB = imgCmpMode && imgCmpB && imgCmpB.src === src;
      const selCls = (isSelA || isSelB) ? ' compare-sel' : '';
      const clickFn = imgCmpMode
        ? 'selectImgCompare(\'' + esc(src) + '\',\'' + esc(img.name) + '\',\'' + expId + '\')'
        : 'openImageModal(\'' + esc(src) + '\',\'' + esc(img.name) + '\')';
      html += '<div class="img-card' + selCls + '" onclick="' + clickFn + '" style="position:relative">';
      if (isSelA) html += '<div class="img-cmp-badge">A</div>';
      if (isSelB) html += '<div class="img-cmp-badge">B</div>';
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

// ── Logs tab ─────────────────────────────────────────────────────────────────

let logSort = 'date';
let logSortDir = 'desc';
let logFilter = '';

async function loadLogs(expId) {
  const container = document.getElementById('detail-tab-logs');
  if (!container) return;
  container.innerHTML = '<p style="color:var(--muted)">Loading...</p>';

  const data = await api('/api/logs/' + expId);
  if (data.error && data.error !== 'not found') {
    container.innerHTML = '<p style="color:var(--muted)">Error: ' + esc(data.error) + '</p>';
    return;
  }

  const paths = data.paths || [];
  const suggestedPaths = data.suggested_paths || [];
  let files = data.files || [];

  let html = '<div class="img-paths-section">';
  html += '<h3 style="font-size:14px;margin-bottom:8px">Scan Paths</h3>';
  html += '<p style="font-size:12px;color:var(--muted);margin-bottom:8px">Add folders to scan for logs, CSVs, JSON/JSONL, and TensorBoard event files. Paths are relative to project root.</p>';

  // Show saved paths
  if (paths.length) {
    for (let i = 0; i < paths.length; i++) {
      const p = paths[i];
      html += '<div class="img-path-row">';
      html += '<span class="img-path-val" ondblclick="startEditLogPath(\'' + expId + '\',' + i + ',this)">' + esc(p) + '</span>';
      html += '<button class="img-path-del" onclick="deleteLogPath(\'' + expId + '\',' + i + ')" title="Remove path">&times;</button>';
      html += '</div>';
    }
  }

  // Add path form
  html += '<div class="img-path-add">';
  html += '<input type="text" id="log-path-input" placeholder="e.g. outputs/logs or logs/tensorboard" style="flex:1">';
  html += '<button onclick="addLogPath(\'' + expId + '\')">Add Path</button>';
  html += '</div>';

  // Suggested paths
  if (suggestedPaths.length && paths.length === 0) {
    html += '<div style="margin-top:6px;font-size:11px;color:var(--muted)">Suggestions: ';
    html += suggestedPaths.map(s => '<a href="#" style="color:var(--blue)" onclick="event.preventDefault();document.getElementById(\'log-path-input\').value=\'' + esc(s) + '\';addLogPath(\'' + expId + '\')">' + esc(s) + '</a>').join(', ');
    html += '</div>';
  }
  html += '</div>';

  // Show files if we have any
  if (files.length) {
    const dirs = [...new Set(files.map(f => f.dir))].sort();

    // Apply filter
    let filtered = files;
    if (logFilter) {
      filtered = filtered.filter(f => f.dir === logFilter);
    }

    // Apply sort
    if (logSort === 'name') {
      filtered = [...filtered].sort((a, b) => logSortDir === 'asc' ? a.name.localeCompare(b.name) : b.name.localeCompare(a.name));
    } else {
      filtered = [...filtered].sort((a, b) => logSortDir === 'asc' ? a.modified - b.modified : b.modified - a.modified);
    }

    html += '<div class="img-gallery-toolbar">';
    html += '<span style="color:var(--muted);font-size:13px">' + files.length + ' file' + (files.length !== 1 ? 's' : '') + '</span>';

    // Refresh
    html += ' <button class="img-filter-select" onclick="loadLogs(\'' + expId + '\')" title="Refresh" style="cursor:pointer">&#x21bb; Refresh</button>';

    // Directory filter
    if (dirs.length > 1) {
      html += ' <select class="img-filter-select" onchange="logFilter=this.value;loadLogs(\'' + expId + '\')">';
      html += '<option value=""' + (logFilter === '' ? ' selected' : '') + '>All folders</option>';
      for (const d of dirs) {
        html += '<option value="' + esc(d) + '"' + (logFilter === d ? ' selected' : '') + '>' + esc(d) + '</option>';
      }
      html += '</select>';
    }

    // Sort
    html += ' <select class="img-filter-select" onchange="logSort=this.value;loadLogs(\'' + expId + '\')">';
    html += '<option value="date"' + (logSort === 'date' ? ' selected' : '') + '>Sort by date</option>';
    html += '<option value="name"' + (logSort === 'name' ? ' selected' : '') + '>Sort by name</option>';
    html += '</select>';

    html += ' <button class="img-filter-select" onclick="logSortDir=logSortDir===\'asc\'?\'desc\':\'asc\';loadLogs(\'' + expId + '\')" title="Toggle sort direction" style="cursor:pointer">' + (logSortDir === 'asc' ? '\u25B2 Asc' : '\u25BC Desc') + '</button>';

    html += '</div>';

    // File table
    html += '<table class="params-table" style="margin-top:8px">';
    html += '<tr><th>File</th><th>Size</th><th>Modified</th><th style="width:60px"></th></tr>';
    for (const f of filtered) {
      const sizeKb = (f.size / 1024).toFixed(1);
      const modDate = f.modified ? new Date(f.modified * 1000).toLocaleString() : '';
      const ext = f.ext || '';
      const logExts = ['log', 'txt', 'out', 'err'];
      const csvExts = ['csv', 'tsv'];
      const badge = logExts.includes(ext) ? '<span class="artifact-type-badge log">log</span>' : csvExts.includes(ext) ? '<span class="artifact-type-badge data">csv</span>' : '<span class="artifact-type-badge data">data</span>';
      html += '<tr>';
      html += '<td><div class="artifact-row">' + badge + ' ' + esc(f.name);
      if (f.dir !== '.') html += ' <span style="color:var(--muted);font-size:11px">(' + esc(f.dir) + ')</span>';
      html += '</div></td>';
      html += '<td style="font-size:12px;color:var(--muted)">' + sizeKb + ' KB</td>';
      html += '<td style="font-size:12px;color:var(--muted)">' + modDate + '</td>';
      html += '<td><button class="view-source-btn" onclick="viewLogFile(\'' + esc(f.path) + '\',\'' + esc(f.name) + '\')">view</button></td>';
      html += '</tr>';
    }
    html += '</table>';
  } else if (paths.length) {
    html += '<p style="color:var(--muted);margin-top:12px">No log files found in the specified path(s).</p>';
    html += ' <button class="img-filter-select" onclick="loadLogs(\'' + expId + '\')" title="Refresh" style="cursor:pointer;margin-top:8px">&#x21bb; Refresh</button>';
  }

  container.innerHTML = html;
}

async function addLogPath(expId) {
  const input = document.getElementById('log-path-input');
  const path = input ? input.value.trim() : '';
  if (!path) return;
  await postApi('/api/experiment/' + expId + '/log-path', {action: 'add', path});
  loadLogs(expId);
}

async function deleteLogPath(expId, index) {
  await postApi('/api/experiment/' + expId + '/log-path', {action: 'delete', index});
  loadLogs(expId);
}

function startEditLogPath(expId, index, el) {
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
      await postApi('/api/experiment/' + expId + '/log-path', {action: 'edit', index, path: newVal});
    }
    loadLogs(expId);
  }
  input.addEventListener('blur', doSave);
  input.addEventListener('keydown', (ev) => {
    if (ev.key === 'Enter') { ev.preventDefault(); input.blur(); }
    if (ev.key === 'Escape') { saved = true; loadLogs(expId); }
  });
}

// ── Result types management ──────────────────────────────────────────────────

let _resultTypes = null; // cached result types
let _metricPrefixes = null; // cached namespace prefixes

async function loadResultTypes() {
  if (_resultTypes !== null) return _resultTypes;
  try {
    const d = await api('/api/result-types');
    _resultTypes = d.types || [];
    _metricPrefixes = d.prefixes || ['train', 'val', 'test'];
  } catch(e) {
    _resultTypes = ['accuracy', 'loss', 'auroc', 'f1', 'precision', 'recall', 'mse', 'mae', 'r2'];
    _metricPrefixes = ['train', 'val', 'test'];
  }
  return _resultTypes;
}

async function loadMetricPrefixes() {
  if (_metricPrefixes !== null) return _metricPrefixes;
  await loadResultTypes();
  return _metricPrefixes;
}

async function populateResultTypeDropdown(expId) {
  const dl = document.getElementById('metric-suggestions-' + expId);
  if (!dl) return;
  const types = await loadResultTypes();
  const savedPrefixes = await loadMetricPrefixes();

  // Also pick up any prefixes already used in this experiment
  const exp = allExperiments.find(e => e.id === expId);
  const existingKeys = new Set();
  if (exp?.metrics) {
    for (const k of Object.keys(exp.metrics)) existingKeys.add(k);
  }
  const existingPrefixes = new Set();
  for (const k of existingKeys) {
    const si = k.indexOf('/');
    if (si > 0) existingPrefixes.add(k.slice(0, si));
  }
  const prefixes = [...new Set([...savedPrefixes, ...existingPrefixes])].sort();

  // Build suggestions: existing keys, bare types, prefixed types
  const suggestions = new Set();
  for (const k of existingKeys) suggestions.add(k);
  for (const t of types) {
    suggestions.add(t);
    for (const p of prefixes) suggestions.add(p + '/' + t);
  }

  dl.innerHTML = '';
  for (const s of suggestions) {
    const opt = document.createElement('option');
    opt.value = s;
    dl.appendChild(opt);
  }
}

async function logMetric(id) {
  const keyEl = document.getElementById('result-key-' + id);
  const valEl = document.getElementById('result-val-' + id);
  const stepEl = document.getElementById('result-step-' + id);
  if (!keyEl || !valEl) return;
  const key = keyEl.value.trim();
  if (!key) { alert('Enter a metric key'); return; }
  const value = valEl.value.trim();
  if (!value || isNaN(parseFloat(value))) { alert('Value must be a number'); return; }
  const step = stepEl ? stepEl.value.trim() : '';
  const payload = {key, value};
  if (step !== '') payload.step = step;
  const d = await postApi('/api/experiment/' + id + '/log-metric', payload);
  if (d.ok) {
    valEl.value = ''; if (stepEl) stepEl.value = '';
    // Auto-save new base type and prefix for future suggestions
    const hasSlash = key.includes('/');
    const baseType = hasSlash ? key.split('/').slice(1).join('/') : key;
    const types = await loadResultTypes();
    if (!types.includes(baseType)) {
      await postApi('/api/result-types', {action: 'add', name: baseType});
      _resultTypes = null;
    }
    if (hasSlash) {
      const prefix = key.split('/')[0];
      const prefixes = await loadMetricPrefixes();
      if (!prefixes.includes(prefix)) {
        await postApi('/api/result-types', {action: 'add', name: prefix, target: 'prefix'});
        _metricPrefixes = null;
      }
    }
    refreshDetail(id);
    loadExperiments();
    owlSay('Logged ' + key + ' = ' + d.value + ' (step ' + d.step + ')');
  }
  else alert(d.error || 'Failed to log metric');
}

async function deleteResult(id, key) {
  if (!confirm('Delete result "' + key + '"?')) return;
  const d = await postApi('/api/experiment/' + id + '/delete-result', {key});
  if (d.ok) { refreshDetail(id); loadExperiments(); }
  else alert(d.error || 'Failed to delete result');
}

async function deleteMetricLast(id, key) {
  const d = await postApi('/api/experiment/' + id + '/delete-metric', {key, mode: 'last'});
  if (d.ok) { refreshDetail(id); loadExperiments(); }
  else alert(d.error || 'Failed to delete metric point');
}

async function deleteMetric(id, key) {
  if (!confirm('Delete all data points for metric "' + key + '"?')) return;
  const d = await postApi('/api/experiment/' + id + '/delete-metric', {key, mode: 'all'});
  if (d.ok) { refreshDetail(id); loadExperiments(); }
  else alert(d.error || 'Failed to delete metric');
}

async function deleteMetricPoint(id, key, step) {
  const d = await postApi('/api/experiment/' + id + '/delete-metric', {key, mode: 'step', step});
  if (d.ok) { refreshDetail(id); loadExperiments(); owlSay('Deleted point (step ' + step + ')'); }
  else alert(d.error || 'Failed to delete metric point');
}

function startMetricRename(id, key, td) {
  if (td.querySelector('input')) return;
  const savedHtml = td.innerHTML;
  const input = document.createElement('input');
  input.type = 'text';
  input.value = key;
  input.style.cssText = 'width:100%;padding:2px 4px;font:inherit;border:1px solid var(--blue);border-radius:3px;background:var(--card-bg);color:var(--fg)';
  td.innerHTML = '';
  td.appendChild(input);
  input.focus();
  input.select();
  const finish = async (save) => {
    input.onblur = null;
    if (save) {
      const newKey = input.value.trim();
      if (newKey && newKey !== key) {
        const d = await postApi('/api/experiment/' + id + '/rename-metric', {old_key: key, new_key: newKey});
        if (d.ok) { refreshDetail(id); loadExperiments(); owlSay('Renamed: ' + newKey); return; }
        else alert(d.error || 'Failed to rename');
      }
    }
    td.innerHTML = savedHtml;
  };
  input.onkeydown = e => { if (e.key === 'Enter') finish(true); else if (e.key === 'Escape') finish(false); };
  input.onblur = () => finish(false);
}

function startResultEdit(id, key, td) {
  if (td.querySelector('input')) return;
  const row = td.querySelector('.artifact-row');
  const valText = row ? row.childNodes[0].textContent.trim() : td.textContent.trim();
  const savedHtml = td.innerHTML;
  const input = document.createElement('input');
  input.type = 'text';
  input.value = valText;
  input.style.cssText = 'width:100%;font-size:13px;padding:2px 4px;font-family:inherit;box-sizing:border-box';
  td.innerHTML = '';
  td.appendChild(input);
  input.focus();
  input.select();
  const restore = () => { td.innerHTML = savedHtml; };
  const save = async () => {
    const val = input.value.trim();
    if (!val || isNaN(parseFloat(val))) { alert('Value must be a number'); restore(); return; }
    if (val === valText) { restore(); return; }
    const d = await postApi('/api/experiment/' + id + '/edit-result', {key, value: val});
    if (d.ok) { refreshDetail(id); loadExperiments(); }
    else { restore(); alert(d.error || 'Failed'); }
  };
  input.onblur = save;
  input.onkeydown = (e) => { if (e.key === 'Enter') { e.preventDefault(); save(); } if (e.key === 'Escape') restore(); };
}


function openManageResultTypes() {
  const overlay = document.createElement('div');
  overlay.className = 'img-modal-overlay';
  overlay.onclick = (ev) => { if (ev.target === overlay) overlay.remove(); };

  const content = document.createElement('div');
  content.className = 'img-modal-content';
  content.style.cssText = 'max-width:500px;width:90vw';

  async function render() {
    const types = await loadResultTypes();
    const prefixes = await loadMetricPrefixes();
    let html = '<div class="img-modal-header">';
    html += '<span class="img-modal-name">Manage Metrics</span>';
    html += '<button class="img-modal-close" onclick="this.closest(\'.img-modal-overlay\').remove()">&times;</button>';
    html += '</div>';
    html += '<div style="padding:16px">';

    // Namespace prefixes
    html += '<div style="margin-bottom:16px">';
    html += '<div style="font-size:12px;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:0.5px;margin-bottom:6px">Namespace Prefixes</div>';
    html += '<div style="display:flex;flex-wrap:wrap;gap:6px;margin-bottom:8px">';
    for (let i = 0; i < prefixes.length; i++) {
      html += '<div class="result-type-chip"><span>' + esc(prefixes[i]) + '/</span>';
      html += '<button onclick="removeMetricItem(\'prefix\',' + i + ')" style="background:none;border:none;color:var(--muted);cursor:pointer;font-size:14px;padding:0 2px" title="Remove">&times;</button></div>';
    }
    html += '</div>';
    html += '<div class="artifact-add-form"><input type="text" id="new-metric-prefix" placeholder="New prefix (e.g. eval)" style="width:160px" onkeydown="if(event.key===\'Enter\')addMetricItem(\'prefix\')">';
    html += '<button onclick="addMetricItem(\'prefix\')">+ Add</button></div></div>';

    // Metric types
    html += '<div style="margin-bottom:8px">';
    html += '<div style="font-size:12px;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:0.5px;margin-bottom:6px">Metric Types</div>';
    html += '<div style="display:flex;flex-wrap:wrap;gap:6px;margin-bottom:8px">';
    for (let i = 0; i < types.length; i++) {
      html += '<div class="result-type-chip"><span>' + esc(types[i]) + '</span>';
      html += '<button onclick="removeMetricItem(\'type\',' + i + ')" style="background:none;border:none;color:var(--muted);cursor:pointer;font-size:14px;padding:0 2px" title="Remove">&times;</button></div>';
    }
    html += '</div>';
    html += '<div class="artifact-add-form"><input type="text" id="new-result-type" placeholder="New metric type (e.g. top5_acc)" style="width:160px" onkeydown="if(event.key===\'Enter\')addMetricItem(\'type\')">';
    html += '<button onclick="addMetricItem(\'type\')">+ Add</button></div></div>';

    html += '</div>';
    content.innerHTML = html;
  }

  overlay.appendChild(content);
  document.body.appendChild(overlay);
  render();

  window._rtOverlayRender = render;

  const handler = (ev) => { if (ev.key === 'Escape') { overlay.remove(); document.removeEventListener('keydown', handler); } };
  document.addEventListener('keydown', handler);
}

async function addMetricItem(target) {
  const inputId = target === 'prefix' ? 'new-metric-prefix' : 'new-result-type';
  const input = document.getElementById(inputId);
  if (!input) return;
  const name = input.value.trim().toLowerCase();
  if (!name) return;
  const d = await postApi('/api/result-types', {action: 'add', name, target});
  if (d.ok) {
    _resultTypes = d.types; _metricPrefixes = d.prefixes;
    input.value = '';
    if (window._rtOverlayRender) window._rtOverlayRender();
    if (currentDetailId) populateResultTypeDropdown(currentDetailId);
  } else {
    alert(d.error || 'Failed');
  }
}

async function removeMetricItem(target, index) {
  const d = await postApi('/api/result-types', {action: 'remove', index, target});
  if (d.ok) {
    _resultTypes = d.types; _metricPrefixes = d.prefixes;
    if (window._rtOverlayRender) window._rtOverlayRender();
    if (currentDetailId) populateResultTypeDropdown(currentDetailId);
  }
}

// ── Within-experiment comparison ─────────────────────────────────────────────

let withinSeq1 = null, withinSeq2 = null;
let _withinEvents = []; // cache timeline events

async function loadCompareWithin(expId) {
  const events = await api('/api/timeline/' + expId);
  _withinEvents = events;
  const container = document.getElementById('detail-tab-compare-within');

  // Group events into meaningful checkpoints: cell_exec, metric, artifact
  const checkpoints = events.filter(e =>
    e.event_type === 'cell_exec' || e.event_type === 'artifact' || e.event_type === 'metric'
  );

  // Helper to describe an event
  function describeEvent(ev) {
    if (ev.event_type === 'cell_exec') {
      const info = ev.value || {};
      return (info.source_preview || ev.key || 'cell').split('\n')[0].slice(0, 50);
    }
    if (ev.event_type === 'metric') return ev.key + ' = ' + (typeof ev.value === 'object' ? JSON.stringify(ev.value) : ev.value);
    if (ev.event_type === 'artifact') return ev.key || 'artifact';
    return ev.key || ev.event_type;
  }

  function eventIcon(type) {
    if (type === 'cell_exec') return '<span class="tl-type-label tl-type-cell_exec">CELL</span>';
    if (type === 'metric') return '<span class="tl-type-label tl-type-metric">METRIC</span>';
    if (type === 'artifact') return '<span class="tl-type-label tl-type-artifact">ARTIFACT</span>';
    return '<span class="tl-type-label">' + type.toUpperCase() + '</span>';
  }

  let html = '<div class="cw-header">';
  html += '<h3>Snapshot Comparison</h3>';
  html += '<p class="cw-subtitle">Pick two points in the timeline to see what changed between them: variables, metrics, and artifacts.</p>';
  html += '</div>';

  // Selection bar
  html += '<div class="tl-compare-bar">';
  const a1Label = withinSeq1 !== null ? describeEvent(checkpoints.find(e => e.seq === withinSeq1) || {event_type:'',value:null,key:'#'+withinSeq1}) : 'click below';
  const a2Label = withinSeq2 !== null ? describeEvent(checkpoints.find(e => e.seq === withinSeq2) || {event_type:'',value:null,key:'#'+withinSeq2}) : 'click below';
  html += '<div class="cw-point cw-point-a' + (withinSeq1 !== null ? ' active' : '') + '">';
  html += '<span class="cw-point-label">A</span>';
  html += '<span class="cw-point-desc">' + esc(withinSeq1 !== null ? '#' + withinSeq1 + ': ' + a1Label : 'Select start point') + '</span>';
  html += '</div>';
  html += '<span class="cw-arrow">&#8594;</span>';
  html += '<div class="cw-point cw-point-b' + (withinSeq2 !== null ? ' active' : '') + '">';
  html += '<span class="cw-point-label">B</span>';
  html += '<span class="cw-point-desc">' + esc(withinSeq2 !== null ? '#' + withinSeq2 + ': ' + a2Label : 'Select end point') + '</span>';
  html += '</div>';
  html += '<div class="cw-actions">';
  html += '<button onclick="doWithinCompare(\'' + expId + '\')"' + (withinSeq1 !== null && withinSeq2 !== null ? '' : ' disabled') + '>Compare</button>';
  html += '<button onclick="withinSeq1=null;withinSeq2=null;loadCompareWithin(\'' + expId + '\')" class="cw-clear">Clear</button>';
  html += '</div>';
  html += '</div>';

  // Visual timeline with markers
  html += '<div class="cw-timeline" style="max-height:400px;overflow-y:auto">';
  for (const ev of checkpoints) {
    const isA = withinSeq1 === ev.seq;
    const isB = withinSeq2 === ev.seq;
    const selCls = (isA || isB) ? ' tl-seq-select selected' : ' tl-seq-select';
    const markerCls = isA ? ' cw-marker-a' : (isB ? ' cw-marker-b' : '');
    html += '<div class="tl-event tl-' + ev.event_type + selCls + markerCls + '" onclick="selectWithinSeq(' + ev.seq + ',\'' + expId + '\')" style="cursor:pointer">';
    html += '<div class="tl-seq">';
    if (isA) html += '<span class="cw-badge cw-badge-a">A</span>';
    else if (isB) html += '<span class="cw-badge cw-badge-b">B</span>';
    else html += ev.seq;
    html += '</div>';
    html += '<div class="tl-body">';
    html += eventIcon(ev.event_type);
    html += '<strong>' + esc(describeEvent(ev)) + '</strong>';
    html += ' <span style="color:var(--muted);margin-left:8px;font-size:11px">' + fmtDt(ev.ts) + '</span>';
    html += '</div></div>';
  }
  if (!checkpoints.length) {
    html += '<p style="color:var(--muted);padding:20px">No timeline events recorded for this experiment. Timeline comparison works best with notebook runs.</p>';
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
  const lo = Math.min(withinSeq1, withinSeq2);
  const hi = Math.max(withinSeq1, withinSeq2);

  const [vars1, vars2, metricsData] = await Promise.all([
    api('/api/vars-at/' + expId + '?seq=' + lo),
    api('/api/vars-at/' + expId + '?seq=' + hi),
    api('/api/metrics/' + expId),
  ]);

  let html = '<div class="within-compare">';

  // Summary header
  const evA = _withinEvents.find(e => e.seq === lo);
  const evB = _withinEvents.find(e => e.seq === hi);
  html += '<div class="cw-result-header">';
  html += '<div class="cw-result-point"><span class="cw-badge cw-badge-a">A</span> #' + lo + (evA ? ' &mdash; ' + esc((evA.key||evA.event_type).slice(0,40)) : '') + '</div>';
  html += '<span class="cw-arrow">&#8594;</span>';
  html += '<div class="cw-result-point"><span class="cw-badge cw-badge-b">B</span> #' + hi + (evB ? ' &mdash; ' + esc((evB.key||evB.event_type).slice(0,40)) : '') + '</div>';
  html += '</div>';

  // Filter controls
  html += '<div class="cw-filters">';
  html += '<label><input type="checkbox" id="cw-only-changed" checked onchange="filterWithinResults()"> Show only changes</label>';
  html += '</div>';

  // Variables section
  const allVarKeys = [...new Set([...Object.keys(vars1), ...Object.keys(vars2)])].sort();
  const changedVars = allVarKeys.filter(k => String(vars1[k]) !== String(vars2[k]));
  html += '<h4 class="cw-section-title">Variables <span class="cw-change-count">' + changedVars.length + ' changed / ' + allVarKeys.length + ' total</span></h4>';
  if (allVarKeys.length) {
    html += '<table class="params-table cw-table">';
    html += '<tr><th>Variable</th><th>Point A (#' + lo + ')</th><th>Point B (#' + hi + ')</th><th>Delta</th></tr>';
    for (const k of allVarKeys) {
      const v1 = vars1[k] !== undefined ? String(vars1[k]).slice(0, 60) : '--';
      const v2 = vars2[k] !== undefined ? String(vars2[k]).slice(0, 60) : '--';
      const differs = String(vars1[k]) !== String(vars2[k]);
      const cls = differs ? ' class="differs cw-changed"' : ' class="cw-unchanged"';
      let delta = '';
      if (differs) {
        const n1 = parseFloat(vars1[k]), n2 = parseFloat(vars2[k]);
        if (!isNaN(n1) && !isNaN(n2)) {
          const d = n2 - n1;
          delta = '<span class="cw-delta ' + (d > 0 ? 'cw-delta-up' : 'cw-delta-down') + '">' + (d > 0 ? '+' : '') + (Number.isInteger(d) ? d : d.toFixed(4)) + '</span>';
        } else {
          delta = '<span class="cw-delta cw-delta-changed">changed</span>';
        }
      }
      html += '<tr' + cls + '><td class="var-name">' + esc(k) + '</td><td>' + esc(v1) + '</td><td>' + esc(v2) + '</td><td>' + delta + '</td></tr>';
    }
    html += '</table>';
  } else {
    html += '<p style="color:var(--muted);font-size:13px">No variable snapshots between these points.</p>';
  }

  // Metrics section — show metrics logged between the two seq points
  const metricEvents = _withinEvents.filter(e => e.event_type === 'metric' && e.seq >= lo && e.seq <= hi);
  if (metricEvents.length || Object.keys(metricsData).length) {
    html += '<h4 class="cw-section-title" style="margin-top:16px">Metrics between A and B <span class="cw-change-count">' + metricEvents.length + ' logged</span></h4>';
    if (metricEvents.length) {
      html += '<table class="params-table cw-table">';
      html += '<tr><th>Metric</th><th>Value</th><th>Step</th><th>When</th></tr>';
      for (const me of metricEvents) {
        const val = typeof me.value === 'object' ? JSON.stringify(me.value) : String(me.value);
        html += '<tr class="cw-changed"><td>' + esc(me.key||'') + '</td><td>' + esc(val) + '</td><td>#' + me.seq + '</td><td>' + fmtDt(me.ts) + '</td></tr>';
      }
      html += '</table>';
    } else {
      html += '<p style="color:var(--muted);font-size:13px">No metrics logged between these timeline points.</p>';
    }
  }

  // Artifacts section — show artifacts logged between the two seq points
  const artifactEvents = _withinEvents.filter(e => e.event_type === 'artifact' && e.seq >= lo && e.seq <= hi);
  if (artifactEvents.length) {
    html += '<h4 class="cw-section-title" style="margin-top:16px">Artifacts between A and B <span class="cw-change-count">' + artifactEvents.length + '</span></h4>';
    html += '<table class="params-table cw-table">';
    html += '<tr><th>Artifact</th><th>Step</th><th>When</th></tr>';
    for (const ae of artifactEvents) {
      html += '<tr class="cw-changed"><td>' + esc(ae.key||'') + '</td><td>#' + ae.seq + '</td><td>' + fmtDt(ae.ts) + '</td></tr>';
    }
    html += '</table>';
  }

  html += '</div>';
  document.getElementById('within-compare-result').innerHTML = html;
}

function filterWithinResults() {
  const onlyChanged = document.getElementById('cw-only-changed');
  if (!onlyChanged) return;
  const show = onlyChanged.checked;
  document.querySelectorAll('.cw-unchanged').forEach(el => {
    el.style.display = show ? 'none' : '';
  });
}
"""

# Initialization
JS_IMAGE_COMPARE = r"""

// ── Image Comparison Modal ───────────────────────────────────────────────────

let _imgCmpMode = 'side';
let _imgCmpData = null;
let _swipePct = 50;
let _swipeDragging = false;

function openCompareModal(src1, name1, src2, name2) {
  _imgCmpData = {src1, name1, src2, name2};
  _imgCmpMode = 'side';
  const overlay = document.createElement('div');
  overlay.className = 'img-cmp-overlay';
  overlay.id = 'img-cmp-overlay';

  let html = '<div class="img-cmp-header">';
  html += '<div class="img-cmp-names"><span>A: ' + esc(name1) + '</span><span>B: ' + esc(name2) + '</span></div>';
  html += '<div class="img-cmp-modes">';
  html += '<button class="active" onclick="setCompareMode(\'side\',this)">Side by Side</button>';
  html += '<button onclick="setCompareMode(\'overlay\',this)">Overlay</button>';
  html += '<button onclick="setCompareMode(\'swipe\',this)">Swipe</button>';
  html += '</div>';
  html += '<button class="img-cmp-close" onclick="closeCompareModal()">&times;</button>';
  html += '</div>';
  html += '<div class="img-cmp-body" id="img-cmp-body"></div>';
  overlay.innerHTML = html;

  overlay.addEventListener('click', function(ev) { if (ev.target === overlay) closeCompareModal(); });
  document.body.appendChild(overlay);

  const escHandler = function(ev) { if (ev.key === 'Escape') { closeCompareModal(); document.removeEventListener('keydown', escHandler); } };
  document.addEventListener('keydown', escHandler);
  overlay.__escHandler = escHandler;

  renderCompareBody();
}

function closeCompareModal() {
  const el = document.getElementById('img-cmp-overlay');
  if (el) {
    if (el.__escHandler) document.removeEventListener('keydown', el.__escHandler);
    el.remove();
  }
  _imgCmpData = null;
  _swipeDragging = false;
}

function setCompareMode(mode, btn) {
  _imgCmpMode = mode;
  if (btn) {
    btn.parentElement.querySelectorAll('button').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
  }
  renderCompareBody();
}

function renderCompareBody() {
  const body = document.getElementById('img-cmp-body');
  if (!body || !_imgCmpData) return;
  const d = _imgCmpData;

  if (_imgCmpMode === 'side') {
    body.innerHTML = '<div class="img-cmp-side">' +
      '<div class="img-cmp-panel"><img src="' + d.src1 + '" alt="A"><div class="img-cmp-label">' + esc(d.name1) + '</div></div>' +
      '<div class="img-cmp-panel"><img src="' + d.src2 + '" alt="B"><div class="img-cmp-label">' + esc(d.name2) + '</div></div>' +
      '</div>';
  } else if (_imgCmpMode === 'overlay') {
    body.innerHTML = '<div class="img-cmp-stack">' +
      '<img src="' + d.src1 + '" alt="A">' +
      '<img src="' + d.src2 + '" alt="B" id="img-cmp-top" style="opacity:0.5">' +
      '</div>' +
      '<div class="img-cmp-slider-wrap">' +
      '<span>A</span>' +
      '<input type="range" min="0" max="100" value="50" oninput="document.getElementById(\'img-cmp-top\').style.opacity=this.value/100;document.getElementById(\'img-cmp-opacity-val\').textContent=this.value+\'%\'">' +
      '<span>B</span> <span id="img-cmp-opacity-val" style="min-width:36px">50%</span>' +
      '</div>';
  } else if (_imgCmpMode === 'swipe') {
    _swipePct = 50;
    body.innerHTML = '<div class="img-cmp-swipe" id="img-cmp-swipe">' +
      '<img class="img-cmp-swipe-base" src="' + d.src1 + '" alt="A">' +
      '<img class="img-cmp-swipe-clip" src="' + d.src2 + '" alt="B" id="img-cmp-swipe-img" style="clip-path:inset(0 0 0 50%)">' +
      '<div class="img-cmp-divider" id="img-cmp-divider" style="left:50%"></div>' +
      '</div>' +
      '<div class="img-cmp-slider-wrap"><span>A</span><span style="flex:1;text-align:center;font-size:11px;opacity:0.5">drag the handle or click to move</span><span>B</span></div>';

    requestAnimationFrame(function() {
      const swipe = document.getElementById('img-cmp-swipe');
      const divider = document.getElementById('img-cmp-divider');
      if (!swipe || !divider) return;

      function updateSwipe(clientX) {
        const rect = swipe.getBoundingClientRect();
        let pct = ((clientX - rect.left) / rect.width) * 100;
        pct = Math.max(0, Math.min(100, pct));
        _swipePct = pct;
        const img = document.getElementById('img-cmp-swipe-img');
        if (img) img.style.clipPath = 'inset(0 0 0 ' + pct + '%)';
        divider.style.left = pct + '%';
      }

      swipe.addEventListener('pointerdown', function(ev) {
        _swipeDragging = true;
        swipe.setPointerCapture(ev.pointerId);
        updateSwipe(ev.clientX);
      });
      swipe.addEventListener('pointermove', function(ev) {
        if (_swipeDragging) updateSwipe(ev.clientX);
      });
      swipe.addEventListener('pointerup', function() { _swipeDragging = false; });
      swipe.addEventListener('pointercancel', function() { _swipeDragging = false; });
    });
  }
}

// ── Cross-run image comparison (in Compare view) ─────────────────────────────

let crossCmpA = null, crossCmpB = null;

function selectCrossImg(src, name, side) {
  if (side === 1) crossCmpA = {src, name};
  else crossCmpB = {src, name};
  // Update UI highlights
  document.querySelectorAll('.cmp-img-thumb[data-side="' + side + '"]').forEach(el => {
    el.classList.toggle('selected', el.dataset.src === src);
  });
  // Update bar
  const bar = document.getElementById('cross-cmp-bar');
  if (bar) {
    const aName = crossCmpA ? crossCmpA.name : '(none)';
    const bName = crossCmpB ? crossCmpB.name : '(none)';
    bar.querySelector('.cmp-sel-a').textContent = 'A: ' + aName;
    bar.querySelector('.cmp-sel-b').textContent = 'B: ' + bName;
    bar.querySelector('.cmp-compare-btn').disabled = !(crossCmpA && crossCmpB);
  }
}

function doCrossCompare() {
  if (crossCmpA && crossCmpB) openCompareModal(crossCmpA.src, crossCmpA.name, crossCmpB.src, crossCmpB.name);
}

function clearCrossCompare() {
  crossCmpA = null; crossCmpB = null;
  document.querySelectorAll('.cmp-img-thumb.selected').forEach(el => el.classList.remove('selected'));
  const bar = document.getElementById('cross-cmp-bar');
  if (bar) {
    bar.querySelector('.cmp-sel-a').textContent = 'A: (none)';
    bar.querySelector('.cmp-sel-b').textContent = 'B: (none)';
    bar.querySelector('.cmp-compare-btn').disabled = true;
  }
}

// ── Intra-run image comparison (in Images tab) ───────────────────────────────

let imgCmpMode = false, imgCmpA = null, imgCmpB = null;

function toggleImgCompare(expId) {
  imgCmpMode = !imgCmpMode;
  imgCmpA = null; imgCmpB = null;
  loadImages(expId);
}

function selectImgCompare(src, name, expId) {
  if (imgCmpA === null || (imgCmpA !== null && imgCmpB !== null)) {
    imgCmpA = {src, name};
    imgCmpB = null;
  } else {
    imgCmpB = {src, name};
  }
  loadImages(expId);
}

function doIntraCompare() {
  if (imgCmpA && imgCmpB) openCompareModal(imgCmpA.src, imgCmpA.name, imgCmpB.src, imgCmpB.name);
}

function clearIntraCompare(expId) {
  imgCmpA = null; imgCmpB = null;
  loadImages(expId);
}
"""

JS_INIT = r"""

// Init — sidebar starts collapsed (opens when entering detail view)
document.getElementById('exp-sidebar').classList.add('collapsed');
syncHighlightCheckbox();
loadTimezoneConfig();
renderTableHeader();
loadAllTags();
loadAllStudies();
loadResultTypes();
loadStats();
loadExperiments().then(() => {
  if (highlightMode) { buildHighlightColors(); renderHighlightLegend(); }
  if (allExperiments.length === 0) owlSpeak('empty');
  else owlSpeak('welcome');
});
"""

# Study management UI — column-based studies with inline editing
JS_STUDIES = r"""
// ── Study management ─────────────────────────────────────────────────────────

async function deleteStudyGlobal(name) {
  const count = allExperiments.filter(e => (e.studies||[]).includes(name)).length;
  if (!confirm('Delete study "' + name + '" from ' + count + ' experiment(s)? This cannot be undone.')) return;
  const res = await postApi('/api/studies/delete', {name});
  if (res.ok) {
    if (studyFilter === name) studyFilter = '';
    await loadAllStudies();
    await loadExperiments();
    renderManagePanel();
  }
}

async function createStudyFromPanel() {
  const input = document.getElementById('new-study-name');
  const name = input ? input.value.trim() : '';
  if (!name) return;
  const ids = [...selectedIds];
  if (ids.length > 0) {
    const res = await postApi('/api/studies/create', {name, experiment_ids: ids});
    if (res.ok) owlSay('Study "' + name + '" created with ' + ids.length + ' experiment(s)!');
  } else {
    owlSay('Select experiments first, then create a study.');
    return;
  }
  if (input) input.value = '';
  await loadAllStudies();
  await loadExperiments();
  renderManagePanel();
}

async function promptBulkAddToStudy() {
  const name = prompt('Study name to add ' + selectedIds.size + ' experiment(s) to:');
  if (!name || !name.trim()) return;
  const res = await postApi('/api/bulk-add-to-study', {study: name.trim(), ids: [...selectedIds]});
  if (res.ok) {
    await loadAllStudies();
    await loadExperiments();
    owlSay('Added ' + res.added + ' to "' + name.trim() + '"');
  } else {
    alert(res.error || 'Failed');
  }
}

async function deleteStudyInline(id, study) {
  const exp = allExperiments.find(e => e.id === id);
  if (exp) exp.studies = (exp.studies||[]).filter(s => s !== study);
  const area = document.getElementById('detail-studies-area');
  if (area) {
    area.querySelectorAll('.tag-removable').forEach(el => {
      if (el.textContent.trim().replace(/\u00d7$/, '').trim() === study) el.remove();
    });
  }
  const d = await postApi('/api/experiment/' + id + '/delete-study', {study});
  if (d.ok) { loadAllStudies(); loadExperiments().then(() => { if (currentDetailId === id) refreshDetail(id); }); }
}
"""

# Stage inline editing
JS_STAGE = r"""
// ── Stage inline editing ─────────────────────────────────────────────────────

function startInlineStage(id, td) {
  const exp = allExperiments.find(e => e.id === id);
  if (!exp) return;
  const curStage = exp.stage != null ? exp.stage : '';
  const curName = exp.stage_name || '';
  td.style.overflow = 'visible';
  td.innerHTML = '<div style="display:flex;gap:4px;align-items:center;white-space:nowrap" onclick="event.stopPropagation()">'
    + '<input type="number" class="inline-edit-input" style="width:50px;font-size:13px;padding:4px 6px" placeholder="#" value="' + esc(String(curStage)) + '" id="stage-num-' + id + '">'
    + '<input type="text" class="inline-edit-input" style="width:70px;font-size:13px;padding:4px 6px" placeholder="label" value="' + esc(curName) + '" id="stage-name-' + id + '">'
    + '<button style="font-size:12px;padding:3px 8px;cursor:pointer;border:1px solid var(--border);border-radius:3px;background:var(--code-bg)" onclick="saveInlineStage(\'' + id + '\')">&#10003;</button>'
    + '</div>';
  const numInput = document.getElementById('stage-num-' + id);
  if (numInput) { numInput.focus(); numInput.select(); }
  numInput.addEventListener('keydown', function(ev) {
    if (ev.key === 'Enter') saveInlineStage(id);
    if (ev.key === 'Escape') { renderExperiments(); }
  });
  const nameInput = document.getElementById('stage-name-' + id);
  nameInput.addEventListener('keydown', function(ev) {
    if (ev.key === 'Enter') saveInlineStage(id);
    if (ev.key === 'Escape') { renderExperiments(); }
  });
}

async function saveInlineStage(id) {
  const numInput = document.getElementById('stage-num-' + id);
  const nameInput = document.getElementById('stage-name-' + id);
  const stageVal = numInput ? numInput.value.trim() : '';
  const nameVal = nameInput ? nameInput.value.trim() : '';
  const body = {};
  if (stageVal !== '') body.stage = parseInt(stageVal, 10);
  else body.stage = null;
  if (nameVal) body.stage_name = nameVal;
  const res = await postApi('/api/experiment/' + id + '/stage', body);
  if (res.ok) {
    const exp = allExperiments.find(e => e.id === id);
    if (exp) { exp.stage = body.stage; exp.stage_name = nameVal; }
    renderExperiments();
    if (currentDetailId === id) refreshDetail(id);
  }
}

function startDetailStageEdit(id, el) {
  const exp = allExperiments.find(e => e.id === id);
  if (!exp) return;
  const curStage = exp.stage != null ? exp.stage : '';
  const curName = exp.stage_name || '';
  el.innerHTML = '<div style="display:inline-flex;gap:4px;align-items:center">'
    + '<input type="number" class="inline-edit-input" style="width:70px;font-size:13px;padding:4px 6px" placeholder="stage #" value="' + esc(String(curStage)) + '" id="detail-stage-num">'
    + '<input type="text" class="inline-edit-input" style="width:130px;font-size:13px;padding:4px 6px" placeholder="label (optional)" value="' + esc(curName) + '" id="detail-stage-name">'
    + '<button style="font-size:12px;padding:2px 8px;cursor:pointer" onclick="saveDetailStage(\'' + id + '\')">Save</button>'
    + '<button style="font-size:12px;padding:2px 8px;cursor:pointer" onclick="refreshDetail(\'' + id + '\')">Cancel</button>'
    + '</div>';
  const numInput = document.getElementById('detail-stage-num');
  if (numInput) { numInput.focus(); numInput.select(); }
  numInput.addEventListener('keydown', function(ev) {
    if (ev.key === 'Enter') saveDetailStage(id);
    if (ev.key === 'Escape') refreshDetail(id);
  });
  document.getElementById('detail-stage-name').addEventListener('keydown', function(ev) {
    if (ev.key === 'Enter') saveDetailStage(id);
    if (ev.key === 'Escape') refreshDetail(id);
  });
}

async function saveDetailStage(id) {
  const numInput = document.getElementById('detail-stage-num');
  const nameInput = document.getElementById('detail-stage-name');
  const stageVal = numInput ? numInput.value.trim() : '';
  const nameVal = nameInput ? nameInput.value.trim() : '';
  const body = {};
  if (stageVal !== '') body.stage = parseInt(stageVal, 10);
  else body.stage = null;
  if (nameVal) body.stage_name = nameVal;
  const res = await postApi('/api/experiment/' + id + '/stage', body);
  if (res.ok) {
    const exp = allExperiments.find(e => e.id === id);
    if (exp) { exp.stage = body.stage; exp.stage_name = nameVal; }
    renderExperiments();
    refreshDetail(id);
  }
}
"""


def get_all_js() -> str:
    """Concatenate all JavaScript sections."""
    return (JS_CORE + JS_OWL + JS_SIDEBAR + JS_TABLE +
            JS_EXPERIMENTS + JS_INLINE_EDIT + JS_DETAIL +
            JS_COMPARE + JS_MUTATIONS + JS_TIMELINE +
            JS_IMAGE_COMPARE + JS_STUDIES + JS_STAGE + JS_INIT)
