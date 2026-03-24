"""Commands notepad: save, copy, edit, delete terminal commands."""

JS_COMMANDS = r"""

// ── Commands state ────────────────────────────────────────────────────────────
let _commands = [];
let _editingCmdId = null;

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

  if (_commands.length === 0) {
    list.innerHTML = '<div class="cmd-empty">No saved commands yet.<br>Add your frequently used terminal commands above.</div>';
    return;
  }

  list.innerHTML = _commands.map(c => {
    if (_editingCmdId === c.id) {
      return '<div class="cmd-item">' +
        '<div class="cmd-edit-form">' +
          '<input type="text" id="cmd-edit-label" value="' + esc(c.label).replace(/"/g, '&quot;') + '" placeholder="Label">' +
          '<textarea id="cmd-edit-command" rows="2" placeholder="Command">' + esc(c.command) + '</textarea>' +
          '<div class="cmd-edit-actions">' +
            '<button onclick="cancelEditCmd()">Cancel</button>' +
            '<button class="primary" onclick="saveEditCmd(\'' + c.id + '\')">Save</button>' +
          '</div>' +
        '</div>' +
      '</div>';
    }

    return '<div class="cmd-item">' +
      '<div class="cmd-item-header">' +
        '<span class="cmd-label">' + esc(c.label) + '</span>' +
        '<div class="cmd-actions">' +
          '<button class="cmd-action-btn" onclick="startEditCmd(\'' + c.id + '\')" title="Edit">&#9998;</button>' +
          '<button class="cmd-action-btn cmd-del" onclick="deleteCmd(\'' + c.id + '\')" title="Delete">&times;</button>' +
        '</div>' +
      '</div>' +
      '<div class="cmd-code-wrap">' +
        '<code class="cmd-code">' + esc(c.command) + '</code>' +
        '<button class="cmd-copy-btn" onclick="copyCmd(this, \'' + c.id + '\')" title="Copy to clipboard">Copy</button>' +
      '</div>' +
    '</div>';
  }).join('');
}

async function addCmd() {
  const labelEl = document.getElementById('cmd-label-input');
  const cmdEl = document.getElementById('cmd-command-input');
  const command = (cmdEl.value || '').trim();
  if (!command) { cmdEl.focus(); return; }
  const label = (labelEl.value || '').trim() || command.split(' ').slice(0, 3).join(' ');

  await postApi('/api/commands/add', { label, command });
  labelEl.value = '';
  cmdEl.value = '';
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

function copyCmd(btn, id) {
  const cmd = _commands.find(c => c.id === id);
  if (!cmd) return;
  navigator.clipboard.writeText(cmd.command).then(() => {
    btn.textContent = 'Copied!';
    btn.classList.add('copied');
    setTimeout(() => { btn.textContent = 'Copy'; btn.classList.remove('copied'); }, 1500);
  });
}

function startEditCmd(id) {
  _editingCmdId = id;
  renderCommands();
  const labelInput = document.getElementById('cmd-edit-label');
  if (labelInput) labelInput.focus();
}

function cancelEditCmd() {
  _editingCmdId = null;
  renderCommands();
}

async function saveEditCmd(id) {
  const label = (document.getElementById('cmd-edit-label').value || '').trim();
  const command = (document.getElementById('cmd-edit-command').value || '').trim();
  if (!command) return;
  await postApi('/api/commands/update', { id, label: label || command.split(' ').slice(0, 3).join(' '), command });
  _editingCmdId = null;
  await loadCommands();
}

// ── Toolbox drawer management ─────────────────────────────────────────────────
let _toolboxTab = 'todos';

function openToolbox(tab) {
  const drawer = document.getElementById('toolbox-drawer');
  const overlay = document.getElementById('toolbox-overlay');
  const isOpen = drawer.classList.contains('visible');
  const sameTab = _toolboxTab === tab;

  if (isOpen && sameTab) {
    closeToolbox();
    return;
  }

  _toolboxTab = tab || 'todos';
  drawer.classList.add('visible');
  overlay.classList.add('visible');

  // Update tab buttons
  document.querySelectorAll('.toolbox-tab').forEach(t => {
    t.classList.toggle('active', t.dataset.tab === _toolboxTab);
  });

  // Show active panel
  document.querySelectorAll('.toolbox-panel').forEach(p => {
    p.classList.toggle('active', p.id === 'toolbox-' + _toolboxTab);
  });

  // Update header buttons
  document.querySelectorAll('.toolbox-btn').forEach(b => {
    b.classList.toggle('active', b.dataset.tab === _toolboxTab);
  });

  // Load data
  if (_toolboxTab === 'todos') {
    loadTodos();
    populateTodoStudies();
  } else {
    loadCommands();
  }
}

function closeToolbox() {
  document.getElementById('toolbox-drawer').classList.remove('visible');
  document.getElementById('toolbox-overlay').classList.remove('visible');
  document.querySelectorAll('.toolbox-btn').forEach(b => b.classList.remove('active'));
}

function switchToolboxTab(tab) {
  _toolboxTab = tab;

  document.querySelectorAll('.toolbox-tab').forEach(t => {
    t.classList.toggle('active', t.dataset.tab === tab);
  });
  document.querySelectorAll('.toolbox-panel').forEach(p => {
    p.classList.toggle('active', p.id === 'toolbox-' + tab);
  });
  document.querySelectorAll('.toolbox-btn').forEach(b => {
    b.classList.toggle('active', b.dataset.tab === tab);
  });

  if (tab === 'todos') { loadTodos(); populateTodoStudies(); }
  else { loadCommands(); }
}

"""
