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
          'onclick="resetCmdCode(\'' + c.id + '\')" title="Reset to saved version">modified &middot; reset</span>' +
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
let _toolboxTab = 'todos';

function openToolbox(tab) {
  const drawer = document.getElementById('toolbox-drawer');
  const overlay = document.getElementById('toolbox-overlay');

  if (drawer.classList.contains('visible') && _toolboxTab === tab) {
    closeToolbox(); return;
  }

  _toolboxTab = tab || 'todos';
  drawer.classList.add('visible');
  overlay.classList.add('visible');
  _syncToolboxUI();
}

function closeToolbox() {
  document.getElementById('toolbox-drawer').classList.remove('visible');
  document.getElementById('toolbox-overlay').classList.remove('visible');
  document.querySelectorAll('.toolbox-btn').forEach(b => b.classList.remove('active'));
}

function switchToolboxTab(tab) {
  _toolboxTab = tab;
  _syncToolboxUI();
}

function _syncToolboxUI() {
  document.querySelectorAll('.toolbox-tab').forEach(t =>
    t.classList.toggle('active', t.dataset.tab === _toolboxTab));
  document.querySelectorAll('.toolbox-panel').forEach(p =>
    p.classList.toggle('active', p.id === 'toolbox-' + _toolboxTab));
  document.querySelectorAll('.toolbox-btn').forEach(b =>
    b.classList.toggle('active', b.dataset.tab === _toolboxTab));

  setupToolboxMeta('todo');
  setupToolboxMeta('cmd');
  if (_toolboxTab === 'todos') loadTodos();
  else loadCommands();
}

"""
