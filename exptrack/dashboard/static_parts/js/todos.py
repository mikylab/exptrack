"""Todos panel: add, toggle, tag, filter, delete todos."""

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
    return '<div class="todo-item' + (t.done ? ' done' : '') + '">' +
      '<input type="checkbox" class="todo-check"' + (t.done ? ' checked' : '') +
      ' onchange="toggleTodo(\'' + t.id + '\')">' +
      '<div class="todo-content">' +
        '<div class="todo-text">' + esc(t.text) + '</div>' +
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
  const tagsEl = document.getElementById('todo-tags-input');
  const studyEl = document.getElementById('todo-study-select');
  const text = (textEl.value || '').trim();
  if (!text) { textEl.focus(); return; }

  await postApi('/api/todos/add', {
    text, tags: parseTags(tagsEl), study: studyEl ? studyEl.value : ''
  });
  textEl.value = ''; tagsEl.value = '';
  if (studyEl) studyEl.value = '';
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

function parseTags(inputEl) {
  return (inputEl.value || '').split(',').map(s => s.trim()).filter(Boolean);
}

function renderItemMeta(item, className) {
  const tags = (item.tags || []).map(tag =>
    '<span class="toolbox-tag">' + esc(tag) + '</span>'
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

function populateToolboxStudies() {
  ['todo-study-select', 'cmd-study-select', 'cmd-edit-study'].forEach(id => {
    const sel = document.getElementById(id);
    if (!sel) return;
    const current = sel.value;
    let html = '<option value="">no study</option>';
    (allKnownStudies || []).forEach(s => {
      const name = typeof s === 'string' ? s : s.name;
      html += '<option value="' + esc(name) + '">' + esc(name) + '</option>';
    });
    sel.innerHTML = html;
    sel.value = current;
  });
}

async function createToolboxStudy(prefix) {
  const input = document.getElementById(prefix + '-new-study');
  const name = (input.value || '').trim();
  if (!name) { input.focus(); return; }
  await postApi('/api/studies/create', { name });
  input.value = '';
  await loadAllStudies();
  populateToolboxStudies();
  const sel = document.getElementById(prefix + '-study-select');
  if (sel) sel.value = name;
}

"""
