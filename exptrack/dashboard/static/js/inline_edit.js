

// ── Inline rename ────────────────────────────────────────────────────────────
// `activeRename` tracks the in-progress rename so that re-renders triggered by
// other UI events (e.g. mutations.py reload, refreshDetail) don't yank the
// input out from under a user mid-type. renderExperiments and renderExpList
// preserve the input via _preserveActiveRename().
let activeRename = null;

function startInlineRename(id, el) {
  // Seed from the run's real name, never from the rendered cell text: the main
  // table middle-ellipsizes long names (midEllipsis), so `el.textContent` is
  // `Jul28_ablate__…__2aac1081` — committing that wrote the literal `…` and
  // destroyed the middle of the name. The row's `title` attribute holds the
  // full name and is the fallback; the raw text is only a last resort.
  const exp = (typeof allExperiments !== 'undefined' ? allExperiments : []).find(e => e.id === id);
  const iconEl = el.querySelector('.edit-icon');
  const rendered = iconEl ? el.textContent.replace(iconEl.textContent, '').trim() : el.textContent.trim();
  const titleAttr = (el.getAttribute && el.getAttribute('title')) || '';
  const currentName = (exp && typeof exp.name === 'string') ? exp.name
                    : (titleAttr || rendered);
  const where = el.closest('#exp-sidebar') ? 'sidebar'
              : el.closest('#detail-view') ? 'detail'
              : 'table';
  const input = document.createElement('input');
  input.type = 'text';
  input.className = 'name-edit-input';
  input.value = currentName;
  el.replaceWith(input);
  input.focus();
  input.select();

  let committed = false;
  async function commit(save) {
    if (committed) return;
    committed = true;
    const newName = input.value.trim();
    activeRename = null;
    if (save && newName && newName !== currentName) {
      const d = await postApi('/api/experiment/' + id + '/rename', {name: newName});
      if (d.ok) {
        const exp = allExperiments.find(e => e.id === id);
        if (exp) { exp.name = newName; exp.name_is_auto = false; }
        // Keep the row visible under "Needs naming" so the user sees the
        // rename took effect (the row would otherwise drop out instantly).
        recentlyRenamedIds.add(id);
        if (currentDetailId === id) {
          const nameEl = document.getElementById('detail-name');
          if (nameEl) nameEl.textContent = newName;
        }
      }
    }
    renderExperiments();
    renderExpList();
    updateAutoNamedCount();
  }

  activeRename = { id, input, commit, where };

  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter')  { e.preventDefault(); commit(true);  }
    if (e.key === 'Escape') { e.preventDefault(); commit(false); }
  });
  // A re-render clearing the input's focus is NOT the user finishing an edit.
  // `remounting` is set while the input is detached by _preserveActiveRename and
  // cleared only once it is back in the DOM *and* focused again (or the user
  // focuses it themselves). Without it, a background loadExperiments() cycle
  // that fails to restore focus auto-committed whatever was half-typed.
  input.addEventListener('focus', () => {
    if (activeRename && activeRename.input === input) activeRename.remounting = false;
  });
  input.addEventListener('blur', () => {
    setTimeout(() => {
      if (!activeRename || activeRename.input !== input) return;
      if (activeRename.remounting) return;  // re-render moved the input, not the user
      if (!input.isConnected) return;  // detached by re-render; preserve handler will re-mount
      if (document.activeElement === input) return;  // refocused
      commit(true);
    }, 0);
  });
}

// Called by renderExperiments/renderExpList/refreshDetail before they overwrite
// innerHTML. Returns a function to call AFTER the re-render that re-mounts the
// input in the row's name cell (preserving value and cursor). If no rename is
// active, returns a no-op.
//
// `scopeId` is the element whose innerHTML is about to be replaced. It matters
// because a single loadExperiments() cycle renders the table and the sidebar
// back to back (_renderExpViews): without a scope check the sidebar render
// would detach the input the table render had just re-mounted, re-mount it into
// whichever slot it found first, and leave the user typing into a moving target.
// Only the render that actually owns the input touches it.
function _preserveActiveRename(scopeId) {
  if (!activeRename) return () => {};
  const input = activeRename.input;
  if (!input || !input.isConnected) return () => {};
  if (scopeId) {
    const scope = document.getElementById(scopeId);
    if (scope && !scope.contains(input)) return () => {};
  }
  const rename = activeRename;
  const id = rename.id;
  const value = input.value;
  const selStart = input.selectionStart;
  const selEnd = input.selectionEnd;
  // Detach so the parent's innerHTML reset doesn't destroy our node. Until it's
  // back and focused, a blur is a side effect of the re-render, not the user.
  rename.remounting = true;
  input.remove();
  const where = rename.where;
  return () => {
    if (activeRename !== rename) return;   // committed while we were re-rendering
    const rootId = where === 'sidebar' ? 'exp-sidebar' : where === 'detail' ? 'detail-view' : 'exp-body';
    const root = document.getElementById(rootId);
    let slot = root && root.querySelector('[data-rename-slot="' + id + '"]');
    if (!slot) {
      // Original view re-rendered without this row (e.g. filter changed) —
      // try the other view as a fallback so the input doesn't vanish silently.
      slot = document.querySelector('[data-rename-slot="' + id + '"]');
    }
    if (!slot) {
      // Nowhere to put it back: drop the edit rather than committing text the
      // user never confirmed.
      rename.remounting = false;
      activeRename = null;
      return;
    }
    slot.replaceWith(input);
    input.value = value;
    try { input.setSelectionRange(selStart, selEnd); } catch (_) {}
    input.focus();
    // Focus can fail (hidden/collapsed container). Staying "remounting" then
    // keeps the blur handler from committing behind the user's back; their next
    // click into the input clears it via the focus listener.
    rename.remounting = document.activeElement !== input;
  };
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
      if (notesEl) notesEl.innerHTML = newNotes ? '<div class="notes-display">'+esc(newNotes)+'<button class="notes-edit-btn" onclick="startDetailNoteEdit(\''+id+'\', document.getElementById(\'detail-notes\'))">edit</button></div>' : '<span style="color:var(--muted)">none</span>';
    }
  }
  textarea.addEventListener('blur', doSave);
  textarea.addEventListener('keydown', (ev) => {
    if (ev.key === 'Enter' && ev.ctrlKey) { ev.preventDefault(); textarea.blur(); }
    if (ev.key === 'Escape') { saved = true; renderExperiments(); renderExpList(); }
  });
}
