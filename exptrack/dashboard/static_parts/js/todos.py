"""Todos panel and shared toolbox helpers (autocomplete, filters, meta rendering)."""

JS_TODOS = r"""

// ── Todos state ───────────────────────────────────────────────────────────────
let _todos = [];
let _todoFilter = 'all';
let _todoTagFilter = '';
let _todoStudyFilter = '';

async function loadTodos() {
  try {
    const res = await api('/api/todos');
    _todos = res.todos || [];
  } catch(e) { _todos = []; }
  renderTodos();
}

function renderTodos() {
  const list = document.getElementById('todo-list');
  if (!list) return;

  let items = _todos;
  if (_todoFilter === 'active') items = items.filter(t => !t.done);
  if (_todoFilter === 'done') items = items.filter(t => t.done);
  if (_todoTagFilter) items = items.filter(t => (t.tags || []).includes(_todoTagFilter));
  if (_todoStudyFilter) items = items.filter(t => t.study === _todoStudyFilter);

  document.querySelectorAll('#todo-status-filters .todo-filter-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.filter === _todoFilter);
  });

  const active = _todos.filter(t => !t.done).length;
  const countEl = document.getElementById('todo-count');
  if (countEl) countEl.textContent = active ? active + ' remaining' : (_todos.length ? 'all done' : '');

  renderFilterChips('todo-tag-filters', _todos.flatMap(t => t.tags || []),
    _todoTagFilter, 'setTodoTagFilter');
  renderFilterChips('todo-study-filters', _todos.map(t => t.study).filter(Boolean),
    _todoStudyFilter, 'setTodoStudyFilter');

  if (items.length === 0) {
    const msg = _todoFilter === 'done' ? 'No completed todos'
              : _todoFilter === 'active' ? 'Nothing to do — nice!'
              : 'No todos yet. Add one above.';
    list.innerHTML = '<div class="todo-empty">' + msg + '</div>';
    return;
  }

  const sorted = [...items].sort((a, b) => a.done === b.done ? 0 : a.done ? 1 : -1);

  list.innerHTML = sorted.map(t => {
    const dueHtml = t.due ? (function() {
      const today = new Date().toISOString().slice(0,10);
      const isOverdue = !t.done && t.due < today;
      const isToday = t.due === today;
      const style = isOverdue ? 'color:var(--red)' : isToday ? 'color:var(--yellow)' : 'color:var(--muted)';
      const label = isOverdue ? 'overdue' : isToday ? 'today' : t.due;
      return '<span class="todo-due" style="' + style + '" title="Due: ' + t.due + '">' + label + '</span>';
    })() : '';
    return '<div class="todo-item' + (t.done ? ' done' : '') + '">' +
      '<input type="checkbox" class="todo-check"' + (t.done ? ' checked' : '') +
      ' onchange="toggleTodo(\'' + t.id + '\')">' +
      '<div class="todo-content">' +
        '<div class="todo-text">' + esc(t.text) + dueHtml + '</div>' +
        renderItemMeta(t, 'todo-meta') +
      '</div>' +
      '<button class="todo-delete" onclick="deleteTodo(\'' + t.id + '\')" title="Delete">&times;</button>' +
    '</div>';
  }).join('');
}

function setTodoFilter(f) { _todoFilter = f; renderTodos(); }
function setTodoTagFilter(tag) { _todoTagFilter = _todoTagFilter === tag ? '' : tag; renderTodos(); }
function setTodoStudyFilter(s) { _todoStudyFilter = _todoStudyFilter === s ? '' : s; renderTodos(); }

async function addTodo() {
  const textEl = document.getElementById('todo-text-input');
  const text = (textEl.value || '').trim();
  if (!text) { textEl.focus(); return; }

  const dueEl = document.getElementById('todo-due-input');
  const due = dueEl ? dueEl.value : '';
  const meta = _toolboxMeta['todo'];
  await postApi('/api/todos/add', {
    text, tags: meta ? meta.getTags() : [], study: meta ? meta.getStudy() : '',
    due: due
  });
  textEl.value = '';
  if (dueEl) dueEl.value = '';
  if (meta) meta.clear();
  await loadTodos();
  textEl.focus();
}

async function toggleTodo(id) {
  const todo = _todos.find(t => t.id === id);
  if (!todo) return;
  await postApi('/api/todos/update', { id, done: !todo.done });
  await loadTodos();
}

async function deleteTodo(id) {
  await postApi('/api/todos/delete', { id });
  await loadTodos();
}

function todoAddKeydown(e) {
  if (e.key === 'Enter') { e.preventDefault(); addTodo(); }
}

// ── Shared toolbox helpers ────────────────────────────────────────────────────

function renderItemMeta(item, className) {
  const tags = (item.tags || []).map(tag =>
    '<span class="toolbox-tag">#' + esc(tag) + '</span>'
  ).join('');
  const study = item.study ? '<span class="toolbox-study">' + esc(item.study) + '</span>' : '';
  return (tags || study) ? '<div class="' + className + '">' + tags + study + '</div>' : '';
}

function renderFilterChips(containerId, values, activeFilter, setterName) {
  const el = document.getElementById(containerId);
  if (!el) return;
  const unique = [...new Set(values)].sort();
  if (unique.length === 0) { el.innerHTML = ''; return; }
  el.innerHTML = unique.map(v =>
    '<button class="todo-filter-btn' + (activeFilter === v ? ' active' : '') +
    '" onclick="' + setterName + '(\'' + v.replace(/'/g, "\\'") + '\')">' + esc(v) + '</button>'
  ).join('');
  if (activeFilter) {
    el.innerHTML += '<button class="todo-filter-btn" onclick="' + setterName + '(\'\')" title="Clear">&times;</button>';
  }
}

// ── Toolbox autocomplete (reuses dashboard's .tag-autocomplete CSS) ───────────

// Builds an autocomplete input that works locally — no API calls, just callbacks.
// Returns { wrapper, input } using the same CSS classes as createItemInput().
function _createAutocomplete(getKnown, opts) {
  const prefix = opts.prefix || '';
  const wrapper = document.createElement('div');
  wrapper.className = 'tag-autocomplete';
  wrapper.style.cssText = 'display:inline-block;position:relative';
  const input = document.createElement('input');
  input.type = 'text';
  input.placeholder = opts.placeholder || '+ add';
  input.className = 'name-edit-input';
  input.style.cssText = opts.style || 'width:100px;font-size:12px;padding:4px 6px';
  const dropdown = document.createElement('div');
  dropdown.className = 'tag-autocomplete-list';
  dropdown.style.display = 'none';
  wrapper.appendChild(input);
  wrapper.appendChild(dropdown);
  let activeIdx = -1;

  function showSuggestions() {
    const val = input.value.trim().toLowerCase();
    const exclude = new Set((opts.getExcluded ? opts.getExcluded() : []).map(s => s.toLowerCase()));
    let suggestions = getKnown().filter(t => !exclude.has(t.name.toLowerCase()));
    if (val) suggestions = suggestions.filter(t => t.name.toLowerCase().includes(val));
    suggestions = suggestions.slice(0, 8);
    if (val && !suggestions.some(t => t.name.toLowerCase() === val) && !exclude.has(val)) {
      suggestions.unshift({ name: val, count: 0, isNew: true });
    }
    if (!suggestions.length) { dropdown.style.display = 'none'; return; }
    dropdown.innerHTML = suggestions.map((t, i) =>
      '<div class="tag-autocomplete-item' + (i === activeIdx ? ' active' : '') +
      '" data-val="' + esc(t.name) + '">' +
      (t.isNew ? '<span class="tag-autocomplete-new">create "' + esc(t.name) + '"</span>'
               : '<span>' + prefix + esc(t.name) + '</span>') +
      '<span class="tag-count">' + (t.count || '') + '</span></div>'
    ).join('');
    dropdown.style.display = 'block';
    dropdown.querySelectorAll('.tag-autocomplete-item').forEach(item => {
      item.onmousedown = (ev) => { ev.preventDefault(); select(item.dataset.val); };
    });
  }

  function select(val) {
    if (!val) return;
    input.value = '';
    dropdown.style.display = 'none';
    activeIdx = -1;
    if (opts.onSelect) opts.onSelect(val);
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
      if (activeIdx >= 0 && items_el[activeIdx]) select(items_el[activeIdx].dataset.val);
      else if (input.value.trim()) select(input.value.trim());
    }
    else if (ev.key === 'Escape') { dropdown.style.display = 'none'; }
  });
  return { wrapper, input };
}

// Merge experiment-known + toolbox-local values into {name, count}[] for suggestions
function _mergeKnown(globalKnown, localValues) {
  const map = new Map();
  (globalKnown || []).forEach(t => {
    const name = typeof t === 'string' ? t : t.name;
    map.set(name, (map.get(name) || 0) + (t.count || 1));
  });
  localValues.forEach(v => { if (v) map.set(v, (map.get(v) || 0) + 1); });
  return [...map.entries()].map(([name, count]) => ({ name, count }))
    .sort((a, b) => b.count - a.count);
}

// Storage for each form's meta state: { getTags(), getStudy(), clear() }
let _toolboxMeta = {};

function setupToolboxMeta(prefix) {
  const container = document.getElementById(prefix + '-meta-row');
  if (!container || container.dataset.init) return;
  container.dataset.init = '1';

  let tags = [];
  let study = '';

  // Tag chips area
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

  // Tag autocomplete
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

  // Study autocomplete
  const studyLabel = document.createElement('span');
  studyLabel.className = 'toolbox-study-display';
  container.appendChild(studyLabel);

  function renderStudy() {
    if (study) {
      studyLabel.innerHTML = '<span class="toolbox-study toolbox-chip">' + esc(study) +
        '<span class="toolbox-chip-x" id="' + prefix + '-study-clear">&times;</span></span>';
      studyLabel.querySelector('.toolbox-chip-x').onmousedown = (ev) => {
        ev.preventDefault(); study = ''; renderStudy();
      };
    } else {
      studyLabel.innerHTML = '';
    }
  }

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

  _toolboxMeta[prefix] = {
    getTags: () => [...tags],
    getStudy: () => study,
    clear: () => { tags = []; study = ''; renderChips(); renderStudy(); }
  };
}

"""
