

// ── One inline editor at a time ──────────────────────────────────────────────
// Every editable cell replaces its own contents with an editor, and nothing
// used to close the one already open — so working down a row left the tags,
// studies, stage and notes editors all live at once. The table is
// `table-layout: fixed` with narrow columns, so each editor overflows its own
// column and a later <td> paints over an earlier one's overflow: they stack on
// top of each other, and one editor's ✓ button lands inside the next one's
// input. Opening an editor now closes whichever was open, committing it
// exactly as a blur would.
let _openCellEditor = null;

let _editorSeq = 0;

// Clicking anywhere outside the open editor closes it (committing, exactly as
// blurring does). Without this the only ways out were opening another editor
// or tabbing away, so an editor opened by mistake — or one you were simply
// done with — stayed on screen over the row indefinitely. Capture-phase
// mousedown so it runs before the click can move focus somewhere that would
// re-render underneath us; a click *inside* the cell (a chip's ×, a
// suggestion, the ✓) is left alone.
document.addEventListener('mousedown', (ev) => {
  const cur = _openCellEditor;
  if (!cur || !cur.el || cur.el.contains(ev.target)) return;
  closeOpenCellEditor();
}, true);

// Call once the editor is built; returns the token that identifies it. `close`
// must commit — closing is a save, not a discard, matching what blurring the
// editor already does. `restore` puts the cell back to its rendered form; see
// closeOpenCellEditor.
function _registerCellEdit(el, close, restore) {
  const token = ++_editorSeq;
  _openCellEditor = { token, el, close, restore: restore || (() => _restoreEditedCell(el)) };
  if (el && el.classList) el.classList.add('cell-editing');
  return token;
}

// Put a closed editor's cell back to its rendered form. Closing has to do this
// *now*: the commit is async and the re-render it schedules is deliberately
// skipped while another editor is open, so without it the closed cell kept its
// dead editor on screen — four cells edited in a row left four of them stacked
// across the table, which is the pile-up this whole mechanism exists to end.
//
// It replaces exactly one <td>, never the row. The editor being opened is
// usually a sibling cell in the same row, and re-rendering the row would
// detach the very node that editor is about to be built in — it would then
// render into a dead node and simply never appear.
function _restoreEditedCell(el) {
  if (!el || !el.isConnected) return;
  const td = el.closest ? el.closest('td') : null;
  const tr = td ? td.parentElement : null;
  const exp = (tr && tr.dataset.id)
    ? (typeof allExperiments !== 'undefined' ? allExperiments : [])
        .find(e => e.id === tr.dataset.id)
    : null;
  if (!exp || typeof renderExpRow !== 'function') return;
  // Rebuilt from live data, so the cell shows what was just saved rather than
  // what it held before the edit. A <tr> will not parse inside a <div>, hence
  // the throwaway <tbody>; the cell index is right by construction because it
  // is the same renderer that drew the row.
  const tmp = document.createElement('tbody');
  tmp.innerHTML = renderExpRow(exp);
  const fresh = tmp.querySelector('tr');
  if (fresh && fresh.children[td.cellIndex]) td.replaceWith(fresh.children[td.cellIndex]);
}

// Forget whatever editor is registered for `el`, without committing it. Only
// for the case where a re-render dropped the editor's node on the floor
// (_preserveActiveRename's no-slot path) — everything else goes through
// _afterInlineEdit.
function _dropCellEditor(el) {
  if (el && el.classList) el.classList.remove('cell-editing');
  if (_openCellEditor && _openCellEditor.el === el) _openCellEditor = null;
}

function closeOpenCellEditor() {
  const cur = _openCellEditor;
  _openCellEditor = null;
  if (!cur) return;
  if (cur.el && cur.el.classList) cur.el.classList.remove('cell-editing');
  // A re-render can detach the editor before anything closes it (see
  // _preserveActiveRename); committing a dead input would save whatever it
  // held when it left the document.
  if (cur.el && cur.el.isConnected === false) return;
  try { cur.close(); } catch (err) { console.error(err); }
  // Immediately, not when the server answers — the dead editor must not
  // outlive the click that closed it.
  try { cur.restore(); } catch (err) { console.error(err); }
}

// Finishes the edit identified by `token` and refreshes the lists. One call,
// not two: every site that finished an edit had to remember to clear the
// registration *before* asking for the re-render, and forgetting it left a
// stale `_openCellEditor` that silently suppressed the render — a failure with
// no error and no visible cause.
//
// The **token**, not the cell, identifies the editor. A cell can host a second
// editor while the first one's save is still in flight (re-open the same cell
// during the round trip), and matching on the element let that stale save
// close the editor which had replaced it — the cell went blank on its own.
//
// The render is deferred because the commit may be running as a side effect of
// opening a *different* editor, and rebuilding the table synchronously would
// detach the cell that editor is about to be built in — it would render into a
// dead node and never appear. It is skipped entirely while an editor is open;
// that editor's own close refreshes the list.
function _afterInlineEdit(token) {
  if (_openCellEditor && _openCellEditor.token === token) {
    if (_openCellEditor.el && _openCellEditor.el.classList) {
      _openCellEditor.el.classList.remove('cell-editing');
    }
    _openCellEditor = null;
  }
  setTimeout(() => {
    if (_openCellEditor) return;   // another editor opened in the meantime
    // The shared post-mutation refresh: inline edits change names, tags and
    // studies, which feed the "Needs naming" count, the metric-sort options
    // and the truncation notice as much as the two list renders do.
    _renderExpViews();
  }, 0);
}

// ── Inline rename ────────────────────────────────────────────────────────────
// `activeRename` tracks the in-progress rename so that re-renders triggered by
// other UI events (e.g. mutations.py reload, refreshDetail) don't yank the
// input out from under a user mid-type. renderExperiments and renderExpList
// preserve the input via _preserveActiveRename().
let activeRename = null;

function startInlineRename(id, el) {
  closeOpenCellEditor();
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
  let editToken = 0;
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
    _afterInlineEdit(editToken);
  }

  activeRename = { id, input, commit, where };
  // The input replaced the cell's span, so restoring means putting that exact
  // node back — outside the main table (sidebar, detail header) there is no
  // row to re-render.
  editToken = _registerCellEdit(input, () => commit(true), () => {
    if (where === 'table') { _restoreEditedCell(input); return; }
    if (input.isConnected) input.replaceWith(el);
  });

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
      // user never confirmed. Clear the cell-editor registration too — it
      // still points at this now-detached input, and the two records of
      // "which editor is open" must not be able to disagree.
      rename.remounting = false;
      activeRename = null;
      _dropCellEditor(input);
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
  closeOpenCellEditor();
  const exp = allExperiments.find(e => e.id === id);
  if (!exp) return;
  let editToken = 0;
  const items = [...(exp[opts.expKey] || [])];
  // The cell carries title="Double-click to edit". Once the editor is open that
  // hint is both wrong and in the way: the browser renders the native tooltip
  // above the autocomplete list, covering its first suggestion. The row is
  // rebuilt on save/escape, which restores the attribute.
  el.removeAttribute('title');
  // `.cell-edit-pop` floats the editor out of its column — see components.css.
  // These columns are routinely 60px wide (the empty-column collapse), which
  // is exactly the width they have when you go to add the first tag or study.
  const container = document.createElement('div');
  container.className = 'cell-edit-pop';
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
      // A class, not inline styles: removing a tag was a 7px glyph with 2px of
      // margin, which is the other half of "hard to add/remove".
      x.className = 'chip-x';
      x.title = 'Remove';
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
    }, {
      onEscape: () => _afterInlineEdit(editToken)
    });
    container.appendChild(wrapper);
    setTimeout(() => input.focus(), 0);
  }
  el.innerHTML = '';
  el.appendChild(container);
  render();
  // Each chip is saved the moment it is added or removed, so closing has
  // nothing to commit — it just puts the cell back to its rendered form.
  editToken = _registerCellEdit(el, () => _afterInlineEdit(editToken));
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
  closeOpenCellEditor();
  const exp = allExperiments.find(e => e.id === id);
  if (!exp) return;
  let editToken = 0;
  const textarea = document.createElement('textarea');
  textarea.value = exp.notes || '';
  textarea.className = 'name-edit-input';
  // box-sizing so the padding stays inside the column; without it a
  // width:100% textarea is wider than the cell it lives in.
  textarea.style.cssText = 'width:100%;box-sizing:border-box;min-height:50px;font-size:12px;font-family:inherit;resize:vertical;padding:4px 6px';
  textarea.onclick = (ev) => ev.stopPropagation();
  const pop = document.createElement('div');
  pop.className = 'cell-edit-pop';
  pop.onclick = (ev) => ev.stopPropagation();
  pop.appendChild(textarea);
  el.innerHTML = '';
  el.appendChild(pop);
  textarea.focus();

  let saved = false;
  async function doSave() {
    if (saved) return;
    saved = true;
    const newNotes = textarea.value.trim();
    await postApi('/api/experiment/' + id + '/edit-notes', {notes: newNotes});
    if (exp) exp.notes = newNotes;
    _afterInlineEdit(editToken);
    if (currentDetailId === id) {
      const notesEl = document.getElementById('detail-notes');
      if (notesEl) notesEl.innerHTML = newNotes ? '<div class="notes-display">'+esc(newNotes)+'<button class="notes-edit-btn" onclick="startDetailNoteEdit(\''+id+'\', document.getElementById(\'detail-notes\'))">edit</button></div>' : '<span style="color:var(--muted)">none</span>';
    }
  }
  textarea.addEventListener('blur', doSave);
  textarea.addEventListener('keydown', (ev) => {
    if (ev.key === 'Enter' && ev.ctrlKey) { ev.preventDefault(); textarea.blur(); }
    if (ev.key === 'Escape') { saved = true; _afterInlineEdit(editToken); }
  });
  editToken = _registerCellEdit(el, doSave);
}
