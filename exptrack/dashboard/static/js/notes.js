
// ── Run notes: the editor and the rendered view ─────────────────────────────
//
// A run's notes are where the question it answers and the answer it gave get
// written down, so they are markdown and they read as markdown. The editor
// used to be a one-line-high textarea in which Enter saved, Tab left the
// field and nothing rendered: a heading stayed `## Result`, a sub-point could
// not be indented, and the only way to write a second line was Shift+Enter.
//
// Two rules hold the rest together. **The markdown the user typed is what is
// stored** — nothing here rewrites it; the rendering is display only, and the
// exports render the same text server-side (core/export_render.py). **Closing
// the editor commits**, as every other inline editor does: clicking outside
// it, Ctrl+Enter, the Save button, or a refresh of the detail view all save;
// only Esc discards, and only after a second press when something changed.

const NOTES_TEMPLATE = [
  '## Question', '', '',
  '## Hypothesis', '', '',
  '## Result', '', '',
  '## Next', '- [ ] ', '',
].join('\n');

const NOTES_PLACEHOLDER = 'What question does this run answer, and what did it show?\n\n'
  + 'Markdown works: ## heading · - list (Tab to indent) · 1. numbered · '
  + '- [ ] task · **bold** · `code` · > quote';

// The raw text behind each rendered notes block, by run id. The rendered view
// is HTML, so the editor cannot seed itself from the element's text.
const _noteSource = {};
let _noteEdit = null;   // {id, commit} while an editor is open

// ── Rendering ───────────────────────────────────────────────────────────────
// The grammar is exactly `core/export_render.markdown_to_html`'s, so what the
// dashboard shows is what Copy and Export produce: `-`/`*` bullets (not `+`,
// which is how a stray changed line reads), `1.` steps, `[ ]` tasks, `**bold**`,
// `_italic_`, `code`, http(s) links, `>` quotes, pipe tables with `\|` escapes,
// and fences that open at column 0 and close on an identical line.
// tests/test_dashboard_js_integrity.py runs one fixture through both.

const _NOTES_LI = /^(\s*)([-*]|(\d{1,9})[.)])\s+(.*)$/;
const _NOTES_TASK = /^\[([ xX])\](?:\s+(.*))?$/;
const _NOTES_FENCE = /^(`{3,})(\w*)\s*$/;

function _notesInline(s) {
  // Code spans come out first so nothing inside them is read as emphasis.
  const codes = [];
  let t = String(s).replace(/`([^`]+)`/g, (m, c) => {
    codes.push(c);
    return '\u0000' + (codes.length - 1) + '\u0000';
  });
  t = esc(t);
  // Only http(s) targets — a note must not be able to carry a javascript: link.
  t = t.replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g,
    (m, label, href) => '<a href="' + href + '" target="_blank" rel="noopener">' + label + '</a>');
  t = t.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
  t = t.replace(/(^|[^\w])_(\S(?:.*?\S)?)_(?!\w)/g, '$1<em>$2</em>');
  return t.replace(/\u0000(\d+)\u0000/g, (m, i) => '<code>' + esc(codes[+i]) + '</code>');
}

function _notesListHtml(items) {
  let html = '';
  const stack = [];   // {indent, tag} of each open list
  for (const it of items) {
    const tag = it.ordered ? 'ol' : 'ul';
    while (stack.length && it.indent < stack[stack.length - 1].indent) {
      html += '</li></' + stack.pop().tag + '>';
    }
    const top = stack[stack.length - 1];
    if (top && it.indent === top.indent && top.tag !== tag) {
      html += '</li></' + stack.pop().tag + '>';
    }
    if (!stack.length || it.indent > stack[stack.length - 1].indent) {
      const start = it.ordered && it.num !== 1 ? ' start="' + it.num + '"' : '';
      html += '<' + tag + start + '>';
      stack.push({indent: it.indent, tag});
    } else {
      html += '</li>';
    }
    const task = it.text.match(_NOTES_TASK);
    if (task) {
      html += '<li class="notes-task"><input type="checkbox" data-line="' + it.line + '"'
        + (task[1] === ' ' ? '' : ' checked') + ' title="Tick to mark done"> '
        + _notesInline(task[2] || '');
    } else {
      html += '<li>' + _notesInline(it.text);
    }
  }
  while (stack.length) html += '</li></' + stack.pop().tag + '>';
  return html;
}

function _notesTableHtml(rows) {
  const cells = r => r.trim().replace(/^\|/, '').replace(/(?<!\\)\|$/, '')
    .split(/(?<!\\)\|/).map(c => c.trim().replace(/\\\|/g, '|'));
  let html = '<table class="notes-table"><tr>'
    + cells(rows[0]).map(c => '<th>' + _notesInline(c) + '</th>').join('') + '</tr>';
  for (const r of rows.slice(2)) {
    html += '<tr>' + cells(r).map(c => '<td>' + _notesInline(c) + '</td>').join('') + '</tr>';
  }
  return html + '</table>';
}

// Markdown → HTML for the detail view. Everything is escaped before any
// markup is added; a task's checkbox carries its source line so ticking it
// can flip exactly that line.
function renderNotesMd(text) {
  const lines = String(text || '').replace(/\r\n?/g, '\n').split('\n');
  const out = [];
  let para = [];
  const flush = () => {
    if (para.length) out.push('<p>' + para.map(_notesInline).join('<br>') + '</p>');
    para = [];
  };
  let i = 0;
  while (i < lines.length) {
    const ln = lines[i];
    const fence = ln.match(_NOTES_FENCE);
    if (fence) {
      flush();
      const body = [];
      i++;
      while (i < lines.length && lines[i].replace(/\s+$/, '') !== fence[1]) body.push(lines[i++]);
      out.push('<pre class="notes-code">' + esc(body.join('\n')) + '</pre>');
      i++;
      continue;
    }
    const h = ln.match(/^(#{1,6})\s+(.*)$/);
    if (h) {
      flush();
      const lvl = Math.min(h[1].length, 4);
      out.push('<div class="notes-h notes-h' + lvl + '" role="heading" aria-level="' + (lvl + 2) + '">'
        + _notesInline(h[2]) + '</div>');
      i++;
      continue;
    }
    if (_NOTES_LI.test(ln)) {
      flush();
      const items = [];
      while (i < lines.length && _NOTES_LI.test(lines[i])) {
        const m = lines[i].match(_NOTES_LI);
        items.push({indent: m[1].replace(/\t/g, '    ').length, ordered: m[3] != null,
                    num: m[3] != null ? parseInt(m[3], 10) : 0, text: m[4], line: i});
        i++;
      }
      out.push(_notesListHtml(items));
      continue;
    }
    if (/^\s*>/.test(ln)) {
      flush();
      const q = [];
      while (i < lines.length && /^\s*>/.test(lines[i])) q.push(lines[i++].replace(/^\s*>\s?/, ''));
      out.push('<blockquote class="notes-quote">' + q.map(_notesInline).join('<br>') + '</blockquote>');
      continue;
    }
    if (/^\s*\|/.test(ln) && i + 1 < lines.length && /^\s*\|?\s*:?-{3,}/.test(lines[i + 1])) {
      flush();
      const rows = [ln, lines[i + 1]];
      i += 2;
      while (i < lines.length && /^\s*\|/.test(lines[i])) rows.push(lines[i++]);
      out.push(_notesTableHtml(rows));
      continue;
    }
    if (/^\s*([-*_])(\s*\1){2,}\s*$/.test(ln)) { flush(); out.push('<hr class="notes-rule">'); i++; continue; }
    if (!ln.trim()) flush();
    else para.push(ln.replace(/\s+$/, ''));
    i++;
  }
  flush();
  return out.join('');
}

// One line for places with no room (the table's Notes column): the first line
// that says something, without the markdown around it. A heading is only a
// fallback — a templated note opens with `## Question`, and a column of
// "Question" says nothing about any run.
function notesSummary(text) {
  let heading = '';
  for (const raw of String(text || '').split('\n')) {
    if (/^`{3,}/.test(raw.trim())) continue;
    const isHeading = /^\s*#{1,6}\s/.test(raw);
    const ln = raw.replace(/^\s*(#{1,6}\s+|>\s?|[-*]\s+(\[[ xX]\]\s*)?|\d+[.)]\s+)/, '')
      .replace(/\*\*|`/g, '').trim();
    if (!ln) continue;
    if (!isHeading) return ln;
    if (!heading) heading = ln;
  }
  return heading;
}

// ── The detail view's Notes section ────────────────────────────────────────

function notesSectionHtml(exp) {
  _noteSource[exp.id] = exp.notes || '';
  const idA = escJsAttr(exp.id);
  const body = exp.notes
    // Capped at ~10 lines with a "more" toggle (shown only on overflow, see
    // _syncNotesCap) — long notes made Overview scroll like long params did.
    ? '<div class="notes-capped' + (_notesCapOpen ? ' open' : '') + '" id="notes-capped"><div class="notes-rendered">'
      + renderNotesMd(exp.notes) + '</div></div>'
      + '<button class="notes-more" onclick="event.stopPropagation();toggleNotesCap(this)">' + (_notesCapOpen ? 'less ▴' : 'more ▾') + '</button>'
    : '<div class="notes-empty">Nothing written yet — the question this run answers, what you expected, what it showed.'
      + '<div class="notes-empty-actions">'
      + '<button class="action-btn" onclick="event.stopPropagation();startDetailNoteEdit(\'' + idA + '\')">Write notes</button>'
      + '<button class="action-btn" onclick="event.stopPropagation();startDetailNoteEdit(\'' + idA + '\', null, {template: true})" title="Question / Hypothesis / Result / Next">Start from template</button>'
      + '</div></div>';
  const actions = exp.notes
    ? '<button class="copy-btn" onclick="startDetailNoteEdit(\'' + idA + '\')">Edit</button>'
      + '<button class="copy-btn" title="Copy the notes — markdown for editors, formatted for OneNote/Word" onclick="copyExportFmt(\'' + idA + '\',\'notes-md\')">Copy</button>'
      + '<button class="copy-btn" title="Download the notes as a .md file" onclick="downloadExportFmt(\'' + idA + '\',\'notes-md\')">Export</button>'
    : '';
  return '<h2 class="section-toggle" onclick="this.classList.toggle(\'collapsed\')">Notes'
    + '<span class="section-actions" onclick="event.stopPropagation()">' + actions + '</span></h2>'
    + '<div class="section-body"><div id="detail-notes" class="detail-notes" '
    + 'onclick="_notesViewClick(event, \'' + idA + '\')" title="Click to edit">' + body + '</div></div>';
}

// A click on the rendered notes edits them — unless it was on a link, a task
// box, or the end of selecting text to copy.
function _notesViewClick(ev, id) {
  const t = ev.target;
  if (t.closest('a') || t.closest('button')) return;
  if (t.matches('input[type=checkbox][data-line]')) {
    _notesToggleTask(id, parseInt(t.dataset.line, 10), t.checked);
    return;
  }
  const sel = window.getSelection && window.getSelection();
  if (sel && String(sel).length) return;
  startDetailNoteEdit(id);
}

async function _notesToggleTask(id, line, checked) {
  const lines = (_noteSource[id] || '').split('\n');
  if (line < 0 || line >= lines.length) return;
  lines[line] = lines[line].replace(/\[( |x|X)\]/, checked ? '[x]' : '[ ]');
  await _saveNotes(id, lines.join('\n'));
}

async function _saveNotes(id, notes) {
  const res = await postApi('/api/experiment/' + id + '/edit-notes', {notes});
  if (!res || !res.ok) {
    owlSay('Could not save the notes' + (res && res.error ? ': ' + res.error : '') + '.');
    return false;
  }
  _noteSource[id] = notes;
  const exp = allExperiments.find(e => e.id === id);
  if (exp) exp.notes = notes;
  _repaintNotes(id);
  return true;
}

// Repaint the section in place: a full refreshDetail rebuilt the whole panel
// and moved the reader's scroll position for a change to one field.
function _repaintNotes(id) {
  const el = document.getElementById('detail-notes');
  if (!el || currentDetailId !== id) return;
  const section = el.closest('.section-body');
  const head = section && section.previousElementSibling;
  if (!section || !head) return;
  const tmp = document.createElement('div');
  tmp.innerHTML = notesSectionHtml({id, notes: _noteSource[id] || ''});
  head.replaceWith(tmp.children[0]);
  section.replaceWith(tmp.children[0]);
  _syncNotesCap();
}

// Called before the detail view is rebuilt, so a refresh saves the draft
// rather than deleting it.
function _commitOpenNoteEdit() {
  if (_noteEdit) _noteEdit.commit();
}

// ── Editing helpers (pure on a textarea) ────────────────────────────────────

function _notesReplace(ta, start, end, text, selStart, selEnd) {
  ta.focus();
  ta.setSelectionRange(start, end);
  // execCommand keeps the edit on the browser's undo stack; setRangeText is
  // the fallback where it is unavailable.
  let done = false;
  try { done = document.execCommand('insertText', false, text); } catch (e) { done = false; }
  if (!done || ta.value.slice(start, start + text.length) !== text) {
    ta.setRangeText(text, start, end, 'end');
  }
  const s = selStart != null ? selStart : start + text.length;
  ta.setSelectionRange(s, selEnd != null ? selEnd : s);
  ta.dispatchEvent(new Event('input'));
}

function _notesLineBounds(value, start, end) {
  const ls = value.lastIndexOf('\n', start - 1) + 1;
  let le = value.indexOf('\n', end > start && value[end - 1] === '\n' ? end - 1 : end);
  if (le < 0) le = value.length;
  return [ls, le];
}

// Indent or outdent every line the selection touches by two spaces.
function _notesIndent(ta, outdent) {
  const {value, selectionStart: s, selectionEnd: e} = ta;
  const [ls, le] = _notesLineBounds(value, s, e);
  const lines = value.slice(ls, le).split('\n');
  let first = 0, total = 0;
  const next = lines.map((ln, k) => {
    let d;
    if (outdent) {
      const n = ln.match(/^ {1,2}|^\t/);
      d = n ? -n[0].length : 0;
      ln = n ? ln.slice(n[0].length) : ln;
    } else {
      d = 2;
      ln = '  ' + ln;
    }
    if (k === 0) first = d;
    total += d;
    return ln;
  });
  const ns = Math.max(ls, s + first);
  _notesReplace(ta, ls, le, next.join('\n'), ns, s === e ? ns : e + total);
}

// Enter inside a list item starts the next item; Enter on an empty item
// outdents it, or at the top level ends the list with a blank line — without
// one, markdown reads the next line as part of the last item. Returns false
// when the caret is not in a list item.
function _notesContinueList(ta) {
  const {value, selectionStart: s, selectionEnd: e} = ta;
  if (s !== e) return false;
  const ls = value.lastIndexOf('\n', s - 1) + 1;
  const line = value.slice(ls, s);
  const m = line.match(/^(\s*)([-*]|(\d{1,9})([.)]))\s+(\[[ xX]\]\s+)?(.*)$/);
  if (!m) return false;
  if (!m[6].trim() && s === ls + line.length) {
    _notesReplace(ta, ls, s, m[1].length >= 2 ? m[1].slice(2) : '\n');
    return true;
  }
  const marker = m[3] != null ? (parseInt(m[3], 10) + 1) + m[4] : m[2];
  _notesReplace(ta, s, s, '\n' + m[1] + marker + ' ' + (m[5] ? '[ ] ' : ''));
  return true;
}

function _notesWrap(ta, before, after) {
  const {value, selectionStart: s, selectionEnd: e} = ta;
  const inner = value.slice(s, e);
  if (inner.startsWith(before) && inner.endsWith(after) && inner.length >= before.length + after.length) {
    const bare = inner.slice(before.length, inner.length - after.length);
    _notesReplace(ta, s, e, bare, s, s + bare.length);
    return;
  }
  _notesReplace(ta, s, e, before + inner + after, s + before.length, s + before.length + inner.length);
}

// Toggle a line prefix (`## `, `- `, `1. `, `- [ ] `) on every selected line.
function _notesPrefix(ta, kind) {
  const {value, selectionStart: s, selectionEnd: e} = ta;
  const [ls, le] = _notesLineBounds(value, s, e);
  const lines = value.slice(ls, le).split('\n');
  const pat = {heading: /^##\s+/, bullet: /^(\s*)[-*]\s+(?!\[)/, number: /^(\s*)\d+[.)]\s+/,
               task: /^(\s*)[-*]\s+\[[ xX]\]\s+/}[kind];
  const all = lines.every(ln => pat.test(ln));
  const next = lines.map((ln, k) => {
    if (all) return ln.replace(pat, '$1');
    const indent = (ln.match(/^\s*/) || [''])[0];
    const bare = ln.slice(indent.length).replace(/^(#{1,6}\s+|[-*]\s+(\[[ xX]\]\s+)?|\d+[.)]\s+)/, '');
    const mark = {heading: '## ', bullet: '- ', number: (k + 1) + '. ', task: '- [ ] '}[kind];
    return kind === 'heading' ? mark + bare : indent + mark + bare;
  });
  const text = next.join('\n');
  _notesReplace(ta, ls, le, text, ls + text.length, ls + text.length);
}

// The template fills an empty note; into one that has text it adds only the
// sections that are missing, at the end, so it never duplicates a heading.
function _notesApplyTemplate(ta) {
  const cur = ta.value;
  if (!cur.trim()) {
    _notesReplace(ta, 0, cur.length, NOTES_TEMPLATE, '## Question\n'.length);
    return;
  }
  const missing = NOTES_TEMPLATE.split(/\n(?=## )/).filter(sec => {
    const head = sec.split('\n')[0].trim().toLowerCase();
    return !cur.split('\n').some(ln => ln.trim().toLowerCase() === head);
  });
  if (!missing.length) { owlSay('Every template section is already here.'); return; }
  const add = (cur.endsWith('\n\n') ? '' : cur.endsWith('\n') ? '\n' : '\n\n') + missing.join('\n');
  _notesReplace(ta, cur.length, cur.length, add, cur.length + add.indexOf('\n', add.indexOf('## ')) + 1);
}

// ── The editor ──────────────────────────────────────────────────────────────

// One editor for every place notes are written — a run's Notes and Compare's
// write-up: the toolbar, Write/Preview, the writing keys, auto-grow, Ctrl+Enter
// and the two-press Esc. The two used to be built separately and had already
// drifted (only one disabled its tools in Preview, showed an empty-preview
// state, or re-grew as you typed). A caller supplies only what saving means.
//
// opts: {value, ariaLabel, placeholder?, extraTools?(ta) → [button], saveLabel,
//        saveTitle, cancelTitle, hint, escMessage, onSave(text), onDiscard()}
// `onSave` may return false to keep the editor open (a partial failure).
function _notesEditorShell(opts) {
  const make = (tag, cls) => { const n = document.createElement(tag); n.className = cls; return n; };
  const wrap = make('div', 'notes-editor');
  wrap.onclick = ev => ev.stopPropagation();
  const bar = make('div', 'notes-toolbar');
  const ta = make('textarea', 'notes-textarea');
  ta.spellcheck = true;
  ta.value = opts.value;
  if (opts.placeholder) ta.placeholder = opts.placeholder;
  ta.setAttribute('aria-label', opts.ariaLabel);
  const preview = make('div', 'notes-preview notes-rendered');
  preview.hidden = true;
  const foot = make('div', 'notes-editor-foot');
  const status = make('span', 'notes-status');
  const hint = make('span', 'notes-hint');
  hint.textContent = opts.hint;

  let closed = false;
  let escArmed = 0;
  const shell = {
    wrap, ta,
    status: msg => { status.textContent = msg; },
    async save() {
      if (closed) return;
      closed = true;
      if (await opts.onSave(ta.value.replace(/\s+$/, '')) === false) closed = false;
    },
    discard() {
      if (closed) return;
      closed = true;
      opts.onDiscard();
    },
  };

  const tabWrite = _notesButton('Write', 'Edit the markdown', () => showPreview(false), 'notes-tab active');
  const tabPreview = _notesButton('Preview', 'See it as it will read', () => showPreview(true), 'notes-tab');
  const tools = _notesToolButtons(ta);
  const extra = opts.extraTools ? opts.extraTools(ta) : [];
  bar.append(tabWrite, tabPreview, _notesSep(), ...tools, ...(extra.length ? [_notesSep(), ...extra] : []));
  foot.append(_notesButton(opts.saveLabel, opts.saveTitle, () => shell.save(), 'action-btn notes-save'),
              _notesButton('Cancel', opts.cancelTitle, () => shell.discard(), 'action-btn'),
              status, hint);
  wrap.append(bar, ta, preview, foot);

  function showPreview(on) {
    preview.hidden = !on;
    ta.hidden = on;
    tabPreview.classList.toggle('active', on);
    tabWrite.classList.toggle('active', !on);
    tools.concat(extra).forEach(b => { b.disabled = on; });
    if (!on) { ta.focus(); return; }
    preview.innerHTML = ta.value.trim() ? renderNotesMd(ta.value)
      : '<span class="notes-muted">Nothing to preview yet.</span>';
    preview.style.minHeight = ta.style.height;
  }
  const grow = () => {
    ta.style.height = 'auto';
    ta.style.height = Math.min(Math.max(ta.scrollHeight + 2, 180), window.innerHeight * 0.7) + 'px';
  };
  ta.addEventListener('input', () => {
    grow();
    escArmed = 0;
    status.textContent = ta.value !== opts.value ? 'Unsaved changes' : '';
  });
  ta.addEventListener('keydown', ev => {
    if (ev.key === 'Enter' && (ev.ctrlKey || ev.metaKey)) { ev.preventDefault(); shell.save(); return; }
    if (ev.key === 'Escape') {
      ev.preventDefault();
      if (ta.value === opts.value || (escArmed && Date.now() - escArmed < 2500)) { shell.discard(); return; }
      escArmed = Date.now();
      status.textContent = opts.escMessage;
      return;
    }
    _notesEditKeys(ta, ev);
  });
  // Called once the wrap is in the page — scrollHeight is 0 before that.
  shell.focusEnd = () => {
    grow();
    ta.focus();
    ta.setSelectionRange(ta.value.length, ta.value.length);
  };
  return shell;
}

// Kept as the name the detail view and older inline handlers call.
// `opts.template` opens the editor with the template already in it.
function startDetailNoteEdit(id, el, opts) {
  el = el || document.getElementById('detail-notes');
  if (!el) return;
  if (_noteEdit) {
    if (_noteEdit.id === id) return;
    _noteEdit.commit();
  }
  const original = _noteSource[id] != null ? _noteSource[id]
    : ((allExperiments.find(e => e.id === id) || {}).notes || '');
  const outside = ev => { if (!shell.wrap.contains(ev.target)) shell.save(); };
  function finish() {
    document.removeEventListener('mousedown', outside, true);
    if (_noteEdit && _noteEdit.id === id) _noteEdit = null;
  }
  const shell = _notesEditorShell({
    value: original,
    ariaLabel: 'Run notes (markdown)',
    placeholder: NOTES_PLACEHOLDER,
    extraTools: ta => [_notesButton('Template', 'Add Question / Hypothesis / Result / Next sections',
                                    () => _notesApplyTemplate(ta), 'notes-tool notes-tool-wide')],
    saveLabel: 'Save', saveTitle: 'Save (Ctrl+Enter)', cancelTitle: 'Discard changes (Esc)',
    hint: 'Tab indents · Enter continues a list · Ctrl+Enter saves · Esc cancels',
    escMessage: 'Press Esc again to discard your changes',
    async onSave(text) {
      finish();
      // A template nobody filled in is not a note.
      if (text === NOTES_TEMPLATE.replace(/\s+$/, '')) text = '';
      if (text === original.replace(/\s+$/, '')) { _repaintNotes(id); return; }
      shell.status('Saving…');
      if (!(await _saveNotes(id, text))) _repaintNotes(id);
    },
    onDiscard() { finish(); _repaintNotes(id); },
  });

  el.innerHTML = '';
  el.appendChild(shell.wrap);
  // The rendered view opens the editor on click; while editing, that handler
  // would rebuild the editor under the cursor.
  el.onclick = null;
  el.removeAttribute('onclick');
  el.removeAttribute('title');
  // Closing commits, as every inline editor does — including a click elsewhere.
  document.addEventListener('mousedown', outside, true);
  _noteEdit = {id, commit: () => shell.save()};
  shell.focusEnd();
  if (opts && opts.template) _notesApplyTemplate(shell.ta);
}


// ── Shared by every notes editor (the run's, and Compare's write-up) ────────

function _notesButton(label, title, fn, cls) {
  const b = document.createElement('button');
  b.type = 'button';
  b.className = cls || 'notes-tool';
  b.textContent = label;
  b.title = title;
  // mousedown would move focus out of the textarea and lose the selection
  // the button is about to act on.
  b.addEventListener('mousedown', ev => ev.preventDefault());
  b.addEventListener('click', ev => { ev.preventDefault(); fn(); });
  return b;
}

function _notesToolButtons(ta) {
  const mkBtn = _notesButton;
  return [
    mkBtn('H', 'Heading (## )', () => _notesPrefix(ta, 'heading')),
    mkBtn('B', 'Bold (Ctrl+B)', () => _notesWrap(ta, '**', '**')),
    mkBtn('I', 'Italic (Ctrl+I)', () => _notesWrap(ta, '_', '_')),
    mkBtn('</>', 'Code (Ctrl+E)', () => _notesWrap(ta, '`', '`')),
    mkBtn('• List', 'Bulleted list', () => _notesPrefix(ta, 'bullet')),
    mkBtn('1. List', 'Numbered list', () => _notesPrefix(ta, 'number')),
    mkBtn('☐ Task', 'Checkbox task — tick it later in the rendered notes', () => _notesPrefix(ta, 'task')),
    mkBtn('←', 'Outdent (Shift+Tab)', () => _notesIndent(ta, true)),
    mkBtn('→', 'Indent (Tab)', () => _notesIndent(ta, false)),
  ];
}

// The writing keys: Tab/Shift+Tab indent, Enter continues a list, Ctrl+B/I/E
// wrap. Saving and cancelling are the caller's.
function _notesEditKeys(ta, ev) {
  const mod = ev.ctrlKey || ev.metaKey;
  if (ev.key === 'Tab') {
    const {value, selectionStart: s, selectionEnd: e} = ta;
    const lineStart = value.lastIndexOf('\n', s - 1) + 1;
    const inList = _NOTES_LI.test(value.slice(lineStart, value.indexOf('\n', s) < 0 ? value.length : value.indexOf('\n', s)));
    ev.preventDefault();
    if (ev.shiftKey || s !== e || inList || s === lineStart) _notesIndent(ta, ev.shiftKey);
    else _notesReplace(ta, s, e, '  ');
    return;
  }
  if (ev.key === 'Enter' && !ev.shiftKey && !mod && !ev.altKey) {
    if (_notesContinueList(ta)) ev.preventDefault();
    return;
  }
  if (mod && !ev.shiftKey && !ev.altKey) {
    const k = ev.key.toLowerCase();
    if (k === 'b') { ev.preventDefault(); _notesWrap(ta, '**', '**'); }
    else if (k === 'i') { ev.preventDefault(); _notesWrap(ta, '_', '_'); }
    else if (k === 'e') { ev.preventDefault(); _notesWrap(ta, '`', '`'); }
  }
}

function _notesSep() {
  const s = document.createElement('span');
  s.className = 'notes-sep';
  return s;
}

// ── Writing up a comparison ─────────────────────────────────────────────────
// The answer to a question usually appears in Compare, and the only place to
// write it down was one run's notes — reached by leaving the comparison,
// opening a run, and writing about the others from memory. The write-up is
// appended to the notes of *every* run compared, with the runs named by what
// tells them apart and a link that reopens the comparison, so the conclusion
// is found from whichever run someone opens later. The runs are fixed when the
// editor opens: re-running a different comparison underneath it must not
// change where a draft goes.

function _compareNoteDraft(exps) {
  const spans = _cmpSpansProjects(exps);
  const lk = _cmpLabelKeysFor(exps);
  const lines = ['## Compared ' + exps.length + ' runs (' + new Date().toISOString().slice(0, 10) + ')', ''];
  for (const e of exps) {
    const label = _cmpRunLabel(e, spans, lk);
    lines.push('- ' + label + (label === e.name ? '' : ' — `' + e.name + '`'));
  }
  if (String(window.location.hash || '').startsWith('#compare=')) {
    lines.push('', '[Open this comparison](' + window.location.href + ')');
  }
  lines.push('', '**Result:** ');
  return lines.join('\n');
}

function openCompareNote() {
  const host = document.getElementById('compare-note');
  if (!host) return;
  // Fixed now: a comparison re-run under the draft must not redirect it.
  let exps = ((_lastComparison && _lastComparison.data && _lastComparison.data.experiments) || []).slice();
  if (exps.length < 2) { owlSay('Run a comparison first.'); return; }
  if (host.firstChild) { const t = host.querySelector('textarea'); if (t) t.focus(); return; }

  const shell = _notesEditorShell({
    value: _compareNoteDraft(exps),
    ariaLabel: 'Write-up of this comparison (markdown)',
    saveLabel: 'Add to ' + exps.length + ' runs’ notes',
    saveTitle: 'Append this to the notes of every run compared (Ctrl+Enter)',
    cancelTitle: 'Discard (Esc)',
    hint: 'Appended to each run’s notes, with a link back to this comparison',
    escMessage: 'Press Esc again to discard the write-up',
    async onSave(text) {
      if (!text.trim()) { host.innerHTML = ''; return; }
      shell.status('Saving…');
      // Sequential on purpose: each append is its own write transaction, and
      // a burst of them contends for the database's single writer.
      const failed = [];
      for (const e of exps) {
        const res = await postApi('/api/experiment/' + e.id + '/note', {note: text}, e.project_id);
        if (!res || !res.ok) failed.push(e);
      }
      if (failed.length) {
        // Only the failed runs are retried: a second Save must not append the
        // write-up twice to the runs that already took it.
        shell.status('Added to ' + (exps.length - failed.length) + ' of ' + exps.length
          + ' runs; failed: ' + failed.map(e => e.name || e.id).join(', ') + '. Save again to retry those.');
        exps = failed;
        return false;
      }
      host.innerHTML = '';
      owlSay('Added the write-up to the notes of the compared runs.');
      loadExperiments();
    },
    onDiscard() { host.innerHTML = ''; },
  });
  host.appendChild(shell.wrap);
  shell.focusEnd();
}

// Open/closed survives a live run's rebuild; another run starts closed.
let _notesCapOpen = false;

function toggleNotesCap(btn) {
  _notesCapOpen = btn.previousElementSibling.classList.toggle('open');
  btn.textContent = _notesCapOpen ? 'less ▴' : 'more ▾';
}
