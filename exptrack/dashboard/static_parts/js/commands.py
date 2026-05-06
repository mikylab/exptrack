"""Commands notepad: save, copy, edit, delete terminal commands with inline adjustable text."""

JS_COMMANDS = r"""

// ── Commands state ────────────────────────────────────────────────────────────
let _commands = [];
let _editingCmdId = null;
let _cmdTagFilter = '';
let _cmdStudyFilter = '';

async function loadCommands() {
  try {
    const res = await api('/api/commands');
    _commands = res.commands || [];
  } catch(e) { _commands = []; }
  renderCommands();
}

function renderCommands() {
  const list = document.getElementById('cmd-list');
  if (!list) return;

  renderFilterChips('cmd-tag-filters', _commands.flatMap(c => c.tags || []),
    _cmdTagFilter, 'setCmdTagFilter');
  renderFilterChips('cmd-study-filters',
    _commands.map(c => c.study).filter(Boolean), _cmdStudyFilter, 'setCmdStudyFilter');

  let items = _commands;
  if (_cmdTagFilter) items = items.filter(c => (c.tags || []).includes(_cmdTagFilter));
  if (_cmdStudyFilter) items = items.filter(c => c.study === _cmdStudyFilter);

  if (items.length === 0) {
    const msg = _commands.length === 0
      ? 'No saved commands yet.<br>Add your frequently used terminal commands above.'
      : 'No commands match the current filter.';
    list.innerHTML = '<div class="cmd-empty">' + msg + '</div>';
    return;
  }

  // Sort: most recently edited first (updated or created as fallback)
  items = [...items].sort((a, b) => {
    const ta = a.updated || a.created || '';
    const tb = b.updated || b.created || '';
    return tb.localeCompare(ta);
  });

  list.innerHTML = items.map(c => {
    if (_editingCmdId === c.id) return renderCmdEditForm(c);

    return '<div class="cmd-item">' +
      '<div class="cmd-item-header">' +
        '<span class="cmd-label">' + esc(c.label) + '</span>' +
        renderItemMeta(c, 'cmd-meta') +
        '<div class="cmd-actions">' +
          '<button class="cmd-action-btn" onclick="duplicateCmd(\'' + c.id + '\')" title="Duplicate">&#x2398;</button>' +
          '<button class="cmd-action-btn" onclick="startEditCmd(\'' + c.id + '\')" title="Edit">&#9998;</button>' +
          '<button class="cmd-action-btn cmd-del" onclick="deleteCmd(\'' + c.id + '\')" title="Delete">&times;</button>' +
        '</div>' +
      '</div>' +
      '<div class="cmd-code-wrap">' +
        '<code class="cmd-code" contenteditable="true" spellcheck="false" ' +
          'data-id="' + c.id + '" data-original="' + esc(c.command).replace(/"/g, '&quot;') + '" ' +
          'oninput="onCmdCodeEdit(this)" onpaste="onCmdCodePaste(event)">' +
          esc(c.command) +
        '</code>' +
        '<span class="cmd-modified" id="cmd-mod-' + c.id + '" style="display:none" ' +
          'onclick="resetCmdCode(\'' + c.id + '\')" title="Reset to saved version">&#x21ba; reset</span>' +
        '<button class="cmd-copy-btn" onclick="copyCmdFromDom(this, \'' + c.id + '\')" title="Copy to clipboard">Copy</button>' +
      '</div>' +
    '</div>';
  }).join('');
}

function renderCmdEditForm(c) {
  return '<div class="cmd-item">' +
    '<div class="cmd-edit-form">' +
      '<input type="text" id="cmd-edit-label" value="' + esc(c.label).replace(/"/g, '&quot;') + '" placeholder="Label">' +
      '<textarea id="cmd-edit-command" rows="2" placeholder="Command">' + esc(c.command) + '</textarea>' +
      '<div class="toolbox-meta-row" id="cmd-edit-meta-row"></div>' +
      '<div class="cmd-edit-actions">' +
        '<button onclick="cancelEditCmd()">Cancel</button>' +
        '<button class="primary" onclick="saveEditCmd(\'' + c.id + '\')">Save</button>' +
      '</div>' +
    '</div>' +
  '</div>';
}

function setCmdTagFilter(tag) { _cmdTagFilter = _cmdTagFilter === tag ? '' : tag; renderCommands(); }
function setCmdStudyFilter(s) { _cmdStudyFilter = _cmdStudyFilter === s ? '' : s; renderCommands(); }

async function addCmd() {
  const labelEl = document.getElementById('cmd-label-input');
  const cmdEl = document.getElementById('cmd-command-input');
  const command = (cmdEl.value || '').trim();
  if (!command) { cmdEl.focus(); return; }

  const meta = _toolboxMeta['cmd'];
  await postApi('/api/commands/add', {
    label: (labelEl.value || '').trim(),
    command, tags: meta ? meta.getTags() : [], study: meta ? meta.getStudy() : ''
  });
  labelEl.value = ''; cmdEl.value = '';
  if (meta) meta.clear();
  await loadCommands();
  labelEl.focus();
}

function cmdAddKeydown(e) {
  if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); addCmd(); }
}

async function deleteCmd(id) {
  await postApi('/api/commands/delete', { id });
  await loadCommands();
}

async function duplicateCmd(id) {
  const c = _commands.find(x => x.id === id);
  if (!c) return;
  await postApi('/api/commands/add', {
    label: c.label + ' (copy)',
    command: c.command,
    tags: c.tags || [],
    study: c.study || ''
  });
  await loadCommands();
}

// ── Inline-adjustable command code ────────────────────────────────────────────

function onCmdCodeEdit(el) {
  const modEl = document.getElementById('cmd-mod-' + el.dataset.id);
  if (modEl) modEl.style.display = el.textContent !== el.dataset.original ? 'inline' : 'none';
}

function onCmdCodePaste(e) {
  e.preventDefault();
  const text = (e.clipboardData || window.clipboardData).getData('text/plain');
  document.execCommand('insertText', false, text);
}

function resetCmdCode(id) {
  const el = document.querySelector('.cmd-code[data-id="' + id + '"]');
  if (!el) return;
  el.textContent = el.dataset.original;
  const modEl = document.getElementById('cmd-mod-' + id);
  if (modEl) modEl.style.display = 'none';
}

function copyCmdFromDom(btn, id) {
  const el = document.querySelector('.cmd-code[data-id="' + id + '"]');
  if (!el) return;
  navigator.clipboard.writeText(el.textContent).then(() => {
    btn.textContent = 'Copied!';
    btn.classList.add('copied');
    setTimeout(() => { btn.textContent = 'Copy'; btn.classList.remove('copied'); }, 1500);
  });
}

// ── Full edit mode (label, command, tags, study) ──────────────────────────────

function startEditCmd(id) {
  _editingCmdId = id;
  renderCommands();
  // Set up autocomplete meta for the edit form, pre-populated with current values
  const c = _commands.find(x => x.id === id);
  if (!c) return;
  const container = document.getElementById('cmd-edit-meta-row');
  if (!container) return;
  _setupEditMeta(container, c.tags || [], c.study || '');
}

function _setupEditMeta(container, initTags, initStudy) {
  let tags = [...initTags];
  let study = initStudy;

  const tagArea = document.createElement('div');
  tagArea.className = 'toolbox-chip-area';
  container.appendChild(tagArea);

  function renderChips() {
    tagArea.innerHTML = tags.map(t =>
      '<span class="toolbox-tag toolbox-chip">#' + esc(t) +
      '<span class="toolbox-chip-x" data-tag="' + esc(t) + '">&times;</span></span>'
    ).join('');
    tagArea.querySelectorAll('.toolbox-chip-x').forEach(el => {
      el.onmousedown = (ev) => {
        ev.preventDefault();
        tags = tags.filter(t => t !== el.dataset.tag);
        renderChips();
      };
    });
  }
  renderChips();

  function getTagKnown() {
    const local = _todos.flatMap(t => t.tags || []).concat(_commands.flatMap(c => c.tags || []));
    return _mergeKnown(allKnownTags, local);
  }
  const tagAc = _createAutocomplete(getTagKnown, {
    prefix: '#', placeholder: '+ tag',
    style: 'width:80px;font-size:12px;padding:4px 6px',
    getExcluded: () => tags,
    onSelect: (val) => { if (!tags.includes(val)) tags.push(val); renderChips(); }
  });
  container.appendChild(tagAc.wrapper);

  // Study
  const studyLabel = document.createElement('span');
  studyLabel.className = 'toolbox-study-display';
  container.appendChild(studyLabel);

  function renderStudy() {
    if (study) {
      studyLabel.innerHTML = '<span class="toolbox-study toolbox-chip">' + esc(study) +
        '<span class="toolbox-chip-x">&times;</span></span>';
      studyLabel.querySelector('.toolbox-chip-x').onmousedown = (ev) => {
        ev.preventDefault(); study = ''; renderStudy();
      };
    } else { studyLabel.innerHTML = ''; }
  }
  renderStudy();

  function getStudyKnown() {
    const local = _todos.map(t => t.study).concat(_commands.map(c => c.study)).filter(Boolean);
    return _mergeKnown(allKnownStudies, local);
  }
  const studyAc = _createAutocomplete(getStudyKnown, {
    prefix: '', placeholder: '+ study',
    style: 'width:80px;font-size:12px;padding:4px 6px',
    getExcluded: () => study ? [study] : [],
    onSelect: (val) => { study = val; renderStudy(); }
  });
  container.appendChild(studyAc.wrapper);

  // Expose getters for saveEditCmd
  _toolboxMeta['cmd-edit'] = {
    getTags: () => [...tags],
    getStudy: () => study,
    clear: () => { tags = []; study = ''; renderChips(); renderStudy(); }
  };
}

function cancelEditCmd() { _editingCmdId = null; renderCommands(); }

async function saveEditCmd(id) {
  const label = (document.getElementById('cmd-edit-label').value || '').trim();
  const command = (document.getElementById('cmd-edit-command').value || '').trim();
  if (!command) return;
  const meta = _toolboxMeta['cmd-edit'];
  await postApi('/api/commands/update', {
    id, label, command,
    tags: meta ? meta.getTags() : [],
    study: meta ? meta.getStudy() : ''
  });
  _editingCmdId = null;
  await loadCommands();
}

// ── Toolbox drawer management ─────────────────────────────────────────────────
let _toolboxTab = _storageGet('exptrack-toolbox-tab') || 'todos';
let _toolboxPinned = _storageGet('exptrack-toolbox-pinned') === 'true';
let _todosLoaded = false, _commandsLoaded = false;

const TOOLBOX_MIN_W = 260;
const TOOLBOX_MAX_W = 800;
const TOOLBOX_DEFAULT_W = 460;

function _applyToolboxWidth(w) {
  const clamped = Math.max(TOOLBOX_MIN_W, Math.min(TOOLBOX_MAX_W, w));
  document.documentElement.style.setProperty('--toolbox-w', clamped + 'px');
  return clamped;
}

(function initToolboxWidth() {
  const saved = parseInt(_storageGet('exptrack-toolbox-w'), 10);
  _applyToolboxWidth(Number.isFinite(saved) ? saved : TOOLBOX_DEFAULT_W);
})();

function startToolboxResize(ev) {
  ev.preventDefault();
  const handle = document.getElementById('toolbox-resize-handle');
  if (handle) handle.classList.add('dragging');
  document.body.classList.add('toolbox-resizing');

  // Drawer is anchored to the right edge, so width = (viewport right edge - cursor x).
  // Cache vw once: it can't change mid-drag without firing a resize event.
  const vw = window.innerWidth;
  let lastW = TOOLBOX_DEFAULT_W;
  let rafId = 0, pendingX = 0;

  function flush() {
    rafId = 0;
    lastW = _applyToolboxWidth(vw - pendingX);
  }
  function onMove(e) {
    pendingX = e.clientX;
    if (!rafId) rafId = requestAnimationFrame(flush);
  }
  function cleanup() {
    document.removeEventListener('mousemove', onMove);
    document.removeEventListener('mouseup', cleanup);
    window.removeEventListener('blur', cleanup);
    if (rafId) { cancelAnimationFrame(rafId); rafId = 0; }
    if (handle) handle.classList.remove('dragging');
    document.body.classList.remove('toolbox-resizing');
    _storageSet('exptrack-toolbox-w', String(lastW));
  }
  document.addEventListener('mousemove', onMove);
  document.addEventListener('mouseup', cleanup);
  window.addEventListener('blur', cleanup);
}

function openToolbox(tab) {
  const drawer = document.getElementById('toolbox-drawer');
  const overlay = document.getElementById('toolbox-overlay');

  if (_toolboxPinned) {
    _toolboxTab = tab || _toolboxTab;
    _storageSet('exptrack-toolbox-tab', _toolboxTab);
    _syncToolboxUI();
    return;
  }

  if (drawer.classList.contains('visible') && _toolboxTab === tab) {
    closeToolbox(); return;
  }

  _toolboxTab = tab || 'todos';
  _storageSet('exptrack-toolbox-tab', _toolboxTab);
  drawer.classList.add('visible');
  overlay.classList.add('visible');
  _syncToolboxUI();
}

function closeToolbox() {
  if (_toolboxPinned) return;
  document.getElementById('toolbox-drawer').classList.remove('visible');
  document.getElementById('toolbox-overlay').classList.remove('visible');
  document.querySelectorAll('.toolbox-btn').forEach(b => b.classList.remove('active'));
}

function switchToolboxTab(tab) {
  _toolboxTab = tab;
  _storageSet('exptrack-toolbox-tab', tab);
  _syncToolboxUI();
}

function _syncToolboxUI() {
  document.querySelectorAll('.toolbox-tab').forEach(t =>
    t.classList.toggle('active', t.dataset.tab === _toolboxTab));
  document.querySelectorAll('.toolbox-panel').forEach(p =>
    p.classList.toggle('active', p.id === 'toolbox-' + _toolboxTab));
  document.querySelectorAll('.toolbox-btn').forEach(b =>
    b.classList.toggle('active', b.dataset.tab === _toolboxTab));

  setupToolboxMeta(_toolboxTab === 'todos' ? 'todo' : 'cmd');
  if (_toolboxTab === 'todos') {
    if (_todosLoaded) renderTodos(); else { _todosLoaded = true; loadTodos(); }
  } else {
    if (_commandsLoaded) renderCommands(); else { _commandsLoaded = true; loadCommands(); }
  }
}

// ── Pinning ───────────────────────────────────────────────────────────────────

function setToolboxPinned(pinned) {
  _toolboxPinned = !!pinned;
  _storageSet('exptrack-toolbox-pinned', _toolboxPinned ? 'true' : 'false');
  _applyToolboxPinned();
  if (_toolboxPinned) _syncToolboxUI();
}

function toggleToolboxPin() { setToolboxPinned(!_toolboxPinned); }

// CSS-only state apply — safe to call synchronously at module load
// since the script tag is at the end of <body>.
function _applyToolboxPinned() {
  const drawer = document.getElementById('toolbox-drawer');
  const overlay = document.getElementById('toolbox-overlay');
  document.body.classList.toggle('toolbox-pinned', _toolboxPinned);
  drawer.classList.toggle('pinned', _toolboxPinned);
  document.getElementById('toolbox-pin-btn').classList.toggle('active', _toolboxPinned);
  document.getElementById('settings-toolbox-pin').checked = _toolboxPinned;
  drawer.classList.toggle('visible', _toolboxPinned);
  overlay.classList.remove('visible');
  if (!_toolboxPinned) {
    document.querySelectorAll('.toolbox-btn').forEach(b => b.classList.remove('active'));
  }
}

// Apply persisted pin state immediately so there's no FOUC before _bootDashboard runs.
_applyToolboxPinned();

// ── Export ────────────────────────────────────────────────────────────────────

function _todoMetaSuffix(t) {
  const parts = [];
  if (t.tags && t.tags.length) parts.push(t.tags.map(x => '#' + x).join(' '));
  if (t.study) parts.push('study:' + t.study);
  if (t.due) parts.push('due:' + t.due);
  return parts.length ? '  (' + parts.join(', ') + ')' : '';
}

function exportTodos(fmt) {
  const stamp = new Date().toISOString().slice(0, 10);
  if (fmt === 'json') {
    saveOrDownload(JSON.stringify(_todos, null, 2),
      'todos_' + stamp + '.json', 'application/json');
    return;
  }
  if (fmt === 'md') {
    const active = _todos.filter(t => !t.done);
    const done = _todos.filter(t => t.done);
    const lines = ['# Todos', '', '_Exported ' + stamp + '_', ''];
    if (active.length) {
      lines.push('## Active');
      active.forEach(t => lines.push('- [ ] ' + t.text + _todoMetaSuffix(t)));
      lines.push('');
    }
    if (done.length) {
      lines.push('## Done');
      done.forEach(t => lines.push('- [x] ' + t.text + _todoMetaSuffix(t)));
    }
    saveOrDownload(lines.join('\n'), 'todos_' + stamp + '.md', 'text/markdown');
    return;
  }
  const lines = _todos.map(t =>
    (t.done ? '[x] ' : '[ ] ') + t.text + _todoMetaSuffix(t));
  saveOrDownload(lines.join('\n'), 'todos_' + stamp + '.txt', 'text/plain');
}

function exportCommands(fmt) {
  const stamp = new Date().toISOString().slice(0, 10);
  if (fmt === 'json') {
    saveOrDownload(JSON.stringify(_commands, null, 2),
      'commands_' + stamp + '.json', 'application/json');
    return;
  }
  if (fmt === 'md') {
    const lines = ['# Commands', '', '_Exported ' + stamp + '_', ''];
    _commands.forEach(c => {
      lines.push('## ' + (c.label || '(unlabeled)'));
      const meta = [];
      if (c.tags && c.tags.length) meta.push(c.tags.map(x => '#' + x).join(' '));
      if (c.study) meta.push('study: ' + c.study);
      if (meta.length) lines.push('_' + meta.join(' · ') + '_', '');
      lines.push('```sh', c.command, '```', '');
    });
    saveOrDownload(lines.join('\n'), 'commands_' + stamp + '.md', 'text/markdown');
    return;
  }
  const lines = ['#!/usr/bin/env bash', '# exptrack saved commands — exported ' + stamp, ''];
  _commands.forEach(c => {
    if (c.label) lines.push('# ' + c.label);
    const meta = [];
    if (c.tags && c.tags.length) meta.push('tags: ' + c.tags.join(', '));
    if (c.study) meta.push('study: ' + c.study);
    if (meta.length) lines.push('# ' + meta.join(' | '));
    lines.push(c.command, '');
  });
  saveOrDownload(lines.join('\n'), 'commands_' + stamp + '.sh', 'text/x-shellscript');
}

"""
