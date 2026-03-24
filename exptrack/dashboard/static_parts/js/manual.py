"""Manual experiment creation modal."""

JS_MANUAL = """
function startDetailScriptEdit(id, el) {
  const currentVal = el.textContent.trim();
  const input = document.createElement('input');
  input.type = 'text';
  input.className = 'inline-edit-input';
  input.style.cssText = 'width:100%;font-size:12px;padding:4px 6px';
  input.value = currentVal === '--' ? '' : currentVal;
  el.textContent = '';
  el.appendChild(input);
  input.focus();
  input.select();

  let saved = false;
  async function doSave() {
    if (saved) return;
    saved = true;
    const newVal = input.value.trim();
    if (newVal !== currentVal) {
      const res = await postApi('/api/experiment/' + id + '/edit-script', {script: newVal});
      if (res.ok) {
        const exp = allExperiments.find(e => e.id === id);
        if (exp) exp.script = newVal;
      }
    }
    refreshDetail(id);
  }
  input.addEventListener('blur', doSave);
  input.addEventListener('keydown', function(ev) {
    if (ev.key === 'Enter') { ev.preventDefault(); input.blur(); }
    if (ev.key === 'Escape') { saved = true; refreshDetail(id); }
  });
}

function startDetailCommandEdit(id) {
  const codeEl = document.getElementById('detail-command');
  if (!codeEl) return;
  const currentVal = codeEl.textContent.trim();
  const input = document.createElement('input');
  input.type = 'text';
  input.className = 'inline-edit-input';
  input.style.cssText = 'width:100%;font-size:13px;padding:4px 6px;font-family:var(--font-mono,monospace)';
  input.value = (currentVal === 'no command recorded' || currentVal === 'double-click to add command') ? '' : currentVal;
  codeEl.textContent = '';
  codeEl.appendChild(input);
  input.focus();
  input.select();

  let saved = false;
  async function doSave() {
    if (saved) return;
    saved = true;
    const newVal = input.value.trim();
    if (newVal !== currentVal) {
      const res = await postApi('/api/experiment/' + id + '/edit-command', {command: newVal});
      if (res.ok) {
        const exp = allExperiments.find(e => e.id === id);
        if (exp) exp.command = newVal;
      }
    }
    refreshDetail(id);
  }
  input.addEventListener('blur', doSave);
  input.addEventListener('keydown', function(ev) {
    if (ev.key === 'Enter') { ev.preventDefault(); input.blur(); }
    if (ev.key === 'Escape') { saved = true; refreshDetail(id); }
  });
}

// ── Manual experiment creation modal ─────────────────────────────────────────

function openNewExpModal() {
  const overlay = document.createElement('div');
  overlay.className = 'new-exp-overlay';
  overlay.addEventListener('click', function(ev) { if (ev.target === overlay) overlay.remove(); });
  document.addEventListener('keydown', function onEsc(ev) {
    if (ev.key === 'Escape') { overlay.remove(); document.removeEventListener('keydown', onEsc); }
  });

  const kvRowHtml = function(placeholder) {
    return '<div class="new-exp-kv">' +
      '<input type="text" placeholder="key" class="kv-key">' +
      '<input type="text" placeholder="' + (placeholder || 'value') + '" class="kv-val">' +
      '<span class="new-exp-kv-del" title="Remove row">&times;</span>' +
      '</div>';
  };

  var html = '<div class="new-exp-dialog">' +
    '<div class="new-exp-header"><h3 onclick="newExpOwlEgg(this)" style="cursor:default">New Experiment</h3>' +
    '<button class="close-btn" id="new-exp-close-btn">&times;</button></div>' +
    '<div class="new-exp-body">' +
      '<div class="new-exp-field"><label>Name <span style="color:var(--red)">*</span></label>' +
      '<input type="text" id="new-exp-name" placeholder="e.g. baseline_resnet50"></div>' +
      '<div class="new-exp-row">' +
        '<div class="new-exp-field"><label>Status</label>' +
        '<select id="new-exp-status"><option value="done" selected>done</option><option value="failed">failed</option><option value="running">running</option></select></div>' +
        '<div class="new-exp-field"><label>Date</label>' +
        '<input type="datetime-local" id="new-exp-date"></div>' +
      '</div>' +
      '<div class="new-exp-field"><label>Script path</label>' +
      '<input type="text" id="new-exp-script" placeholder="/path/to/train.py"></div>' +
      '<div class="new-exp-field"><label>Command</label>' +
      '<input type="text" id="new-exp-command" placeholder="python train.py --lr 0.01"></div>' +
      '<div class="new-exp-field"><label>Tags</label>' +
      '<input type="text" id="new-exp-tags" placeholder="comma-separated, e.g. baseline, v1"></div>' +
      '<div class="new-exp-field"><label>Notes</label>' +
      '<textarea id="new-exp-notes" rows="2" placeholder="Optional notes"></textarea></div>' +
      '<div class="new-exp-field"><label>Params</label>' +
      '<div id="new-exp-params">' + kvRowHtml('value') + '</div>' +
      '<button class="new-exp-kv-add" id="new-exp-add-param">+ Add param</button></div>' +
      '<div class="new-exp-field"><label>Metrics</label>' +
      '<div id="new-exp-metrics">' + kvRowHtml('value (number)') + '</div>' +
      '<button class="new-exp-kv-add" id="new-exp-add-metric">+ Add metric</button></div>' +
    '</div>' +
    '<div class="new-exp-footer">' +
      '<button class="action-btn" id="new-exp-cancel-btn">Cancel</button>' +
      '<button class="action-btn primary" id="new-exp-submit-btn">Create Experiment</button>' +
    '</div>' +
  '</div>';
  overlay.innerHTML = html;

  // Wire up buttons via JS instead of inline onclick with quotes
  overlay.querySelector('#new-exp-close-btn').onclick = function() { overlay.remove(); };
  overlay.querySelector('#new-exp-cancel-btn').onclick = function() { overlay.remove(); };
  overlay.querySelector('#new-exp-submit-btn').onclick = submitNewExp;
  overlay.querySelector('#new-exp-add-param').onclick = function() { addNewExpKvRow('new-exp-params', 'value'); };
  overlay.querySelector('#new-exp-add-metric').onclick = function() { addNewExpKvRow('new-exp-metrics', 'value (number)'); };

  // Event delegation for delete buttons (handles dynamically added rows too)
  overlay.addEventListener('click', function(ev) {
    if (ev.target.classList.contains('new-exp-kv-del')) removeNewExpKvRow(ev.target);
  });

  document.body.appendChild(overlay);

  // Set default date to now in local time
  const now = new Date();
  const pad = n => String(n).padStart(2, '0');
  document.getElementById('new-exp-date').value =
    now.getFullYear() + '-' + pad(now.getMonth()+1) + '-' + pad(now.getDate()) +
    'T' + pad(now.getHours()) + ':' + pad(now.getMinutes());

  document.getElementById('new-exp-name').focus();
}

function addNewExpKvRow(containerId, placeholder) {
  const container = document.getElementById(containerId);
  const row = document.createElement('div');
  row.className = 'new-exp-kv';
  row.innerHTML =
    '<input type="text" placeholder="key" class="kv-key">' +
    '<input type="text" placeholder="' + (placeholder || 'value') + '" class="kv-val">' +
    '<span class="new-exp-kv-del" title="Remove row">&times;</span>';
  container.appendChild(row);
  row.querySelector('.kv-key').focus();
}

function removeNewExpKvRow(btn) {
  const row = btn.closest('.new-exp-kv');
  const container = row.parentElement;
  // Keep at least one row — just clear it instead of removing
  if (container.querySelectorAll('.new-exp-kv').length <= 1) {
    row.querySelector('.kv-key').value = '';
    row.querySelector('.kv-val').value = '';
    return;
  }
  row.remove();
}

function collectKv(containerId) {
  const obj = {};
  const rows = document.querySelectorAll('#' + containerId + ' .new-exp-kv');
  rows.forEach(function(row) {
    const k = row.querySelector('.kv-key').value.trim();
    const v = row.querySelector('.kv-val').value.trim();
    if (k && v) obj[k] = v;
  });
  return obj;
}

async function submitNewExp() {
  const name = document.getElementById('new-exp-name').value.trim();
  if (!name) { owlSay('Name is required'); return; }

  const dateVal = document.getElementById('new-exp-date').value;
  let created_at = '';
  if (dateVal) {
    created_at = new Date(dateVal).toISOString();
  }

  const body = {
    name: name,
    status: document.getElementById('new-exp-status').value,
    created_at: created_at,
    script: document.getElementById('new-exp-script').value.trim(),
    command: document.getElementById('new-exp-command').value.trim(),
    tags: document.getElementById('new-exp-tags').value.trim(),
    notes: document.getElementById('new-exp-notes').value.trim(),
    params: collectKv('new-exp-params'),
    metrics: collectKv('new-exp-metrics')
  };

  const res = await postApi('/api/experiments/create', body);
  if (res.ok) {
    document.querySelector('.new-exp-overlay').remove();
    owlSay('Experiment created!');
    await loadExperiments();
    renderExperiments();
    renderExpList();
    if (res.id) showDetail(res.id);
  } else {
    owlSay(res.error || 'Failed to create experiment');
  }
}

// Easter egg: click the "New Experiment" title 5 times
let _newExpOwlClicks = 0;
let _newExpOwlTimer = null;
function newExpOwlEgg(el) {
  _newExpOwlClicks++;
  if (_newExpOwlTimer) clearTimeout(_newExpOwlTimer);
  _newExpOwlTimer = setTimeout(() => { _newExpOwlClicks = 0; }, 1500);
  if (_newExpOwlClicks >= 5) {
    _newExpOwlClicks = 0;
    owlSay('Hoo-ray! You found me! Good luck with your experiment!', 'owl-bounce');
    // Spin the header owl
    const mascot = document.querySelector('.owl-mascot');
    if (mascot) { mascot.style.transition = 'transform 0.6s'; mascot.style.transform = 'rotate(360deg) scale(1.3)'; setTimeout(() => { mascot.style.transform = ''; }, 700); }
  }
}
"""
