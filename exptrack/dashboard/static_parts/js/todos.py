"""Todos panel: add, toggle, tag, filter, delete todos."""

JS_TODOS = r"""

// ── Todos state ───────────────────────────────────────────────────────────────
let _todos = [];
let _todoFilter = 'all';  // 'all' | 'active' | 'done'
let _todoTagFilter = '';

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

  // Apply filters
  let items = _todos;
  if (_todoFilter === 'active') items = items.filter(t => !t.done);
  if (_todoFilter === 'done') items = items.filter(t => t.done);
  if (_todoTagFilter) items = items.filter(t => (t.tags || []).includes(_todoTagFilter));

  // Update filter buttons
  document.querySelectorAll('.todo-filter-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.filter === _todoFilter);
  });

  // Update counts
  const active = _todos.filter(t => !t.done).length;
  const done = _todos.filter(t => t.done).length;
  const countEl = document.getElementById('todo-count');
  if (countEl) countEl.textContent = active ? active + ' remaining' : (done ? 'all done' : '');

  // Render tag filter chips
  const allTags = [...new Set(_todos.flatMap(t => t.tags || []))].sort();
  const tagBar = document.getElementById('todo-tag-filters');
  if (tagBar) {
    if (allTags.length === 0) {
      tagBar.innerHTML = '';
    } else {
      tagBar.innerHTML = allTags.map(tag =>
        '<button class="todo-filter-btn' + (_todoTagFilter === tag ? ' active' : '') +
        '" onclick="setTodoTagFilter(\'' + tag.replace(/'/g, "\\'") + '\')">' + esc(tag) + '</button>'
      ).join('');
      if (_todoTagFilter) {
        tagBar.innerHTML += '<button class="todo-filter-btn" onclick="setTodoTagFilter(\'\')" title="Clear tag filter">&times;</button>';
      }
    }
  }

  if (items.length === 0) {
    const msg = _todoFilter === 'done' ? 'No completed todos'
              : _todoFilter === 'active' ? 'Nothing to do — nice!'
              : 'No todos yet. Add one above.';
    list.innerHTML = '<div class="todo-empty">' + msg + '</div>';
    return;
  }

  // Render: active first, then done
  const sorted = [...items].sort((a, b) => {
    if (a.done !== b.done) return a.done ? 1 : -1;
    return 0;  // preserve order within group
  });

  list.innerHTML = sorted.map(t => {
    const tags = (t.tags || []).map(tag =>
      '<span class="todo-tag">' + esc(tag) + '</span>'
    ).join('');
    const study = t.study ? '<span class="todo-study">' + esc(t.study) + '</span>' : '';
    const meta = (tags || study) ? '<div class="todo-meta">' + tags + study + '</div>' : '';

    return '<div class="todo-item' + (t.done ? ' done' : '') + '">' +
      '<input type="checkbox" class="todo-check"' + (t.done ? ' checked' : '') +
      ' onchange="toggleTodo(\'' + t.id + '\')">' +
      '<div class="todo-content">' +
        '<div class="todo-text">' + esc(t.text) + '</div>' +
        meta +
      '</div>' +
      '<button class="todo-delete" onclick="deleteTodo(\'' + t.id + '\')" title="Delete">&times;</button>' +
    '</div>';
  }).join('');
}

function setTodoFilter(f) {
  _todoFilter = f;
  renderTodos();
}

function setTodoTagFilter(tag) {
  _todoTagFilter = _todoTagFilter === tag ? '' : tag;
  renderTodos();
}

async function addTodo() {
  const textEl = document.getElementById('todo-text-input');
  const tagsEl = document.getElementById('todo-tags-input');
  const studyEl = document.getElementById('todo-study-select');
  const text = (textEl.value || '').trim();
  if (!text) { textEl.focus(); return; }

  const tags = (tagsEl.value || '').split(',').map(s => s.trim()).filter(Boolean);
  const study = studyEl ? studyEl.value : '';

  await postApi('/api/todos/add', { text, tags, study });
  textEl.value = '';
  tagsEl.value = '';
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

// Populate study dropdown with known studies
function populateTodoStudies() {
  const sel = document.getElementById('todo-study-select');
  if (!sel) return;
  const current = sel.value;
  sel.innerHTML = '<option value="">no study</option>';
  (allKnownStudies || []).forEach(s => {
    const name = typeof s === 'string' ? s : s.name;
    sel.innerHTML += '<option value="' + esc(name) + '">' + esc(name) + '</option>';
  });
  sel.value = current;
}

"""
