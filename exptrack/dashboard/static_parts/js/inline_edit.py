"""Double-click inline editing for names, tags, and notes."""

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
