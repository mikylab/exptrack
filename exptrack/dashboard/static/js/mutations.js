

function esc(s) {
  if (s == null) return '';
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
}

// JS-string-context escaper for values placed inside an inline event handler.
// Inside such an attribute the browser HTML-decodes the value BEFORE the JS
// engine parses it, so esc() alone (which yields &#39;) decodes back to ' and
// breaks/injects into the JS string. Prefer escJsAttr() (below) at call sites.
function escJs(s) {
  if (s == null) return '';
  return String(s).replace(/\\/g,'\\\\').replace(/'/g,"\\'").replace(/"/g,'\\"')
                  .replace(/</g,'\\x3c').replace(/>/g,'\\x3e')
                  .replace(/\n/g,'\\n').replace(/\r/g,'\\r');
}

// Handler-attribute escaper: the correct composition for a value placed inside
// an inline on*="fn('…')" handler — JS-escape first, then HTML-escape. Call this
// at every such site (rather than nesting esc()/escJs() by hand) so the order
// can't be transposed. See CLAUDE.md "Rules for Changes".
function escJsAttr(s) { return esc(escJs(s)); }


// deleteExp() now lives in JS_TRASH (opens a confirm modal showing scope).

async function finishExp(id) {
  if (!confirm('Mark this experiment as done?')) return;
  const d = await postApi('/api/experiment/' + id + '/finish');
  if (d.ok) {
    refreshDetail(id);
    loadStats();
    loadExperiments();
  } else alert(d.error || 'Failed');
}

// ── Diff compact / export ────────────────────────────────────────────────────

function fmtFreed(b) { return b > 1024 ? (b/1024).toFixed(1) + ' KB' : b + ' B'; }

function _compactBtnHtml(exp) {
  const cs = exp.compact_status || {};
  const hasCompactable = cs.diff === 'stored' || cs.cells === 'stored' || cs.cells === 'partial' || cs.timeline === 'stored';
  if (!hasCompactable) {
    const wasCompacted = cs.diff === 'compacted' || cs.cells === 'compacted' || cs.timeline === 'compacted';
    if (wasCompacted) return '<span style="color:var(--muted);font-size:12px;padding:4px 8px">compacted</span>';
    return '';
  }
  return '<button class="action-btn" onclick="compactExp(\'' + exp.id + '\')">Compact</button>';
}

function _compactStatusHtml(exp) {
  const cs = exp.compact_status || {};
  const parts = [];
  if (cs.diff === 'compacted') parts.push('<span style="color:var(--green)">diff stripped</span>');
  if (cs.cells === 'compacted') parts.push('<span style="color:var(--green)">cells stripped</span>');
  if (cs.cells === 'shared') parts.push('<span style="color:var(--yellow)">cells shared</span>');
  if (cs.timeline === 'compacted') parts.push('<span style="color:var(--green)">timeline stripped</span>');
  if (!parts.length) return '';
  return '<div style="margin-top:6px;font-size:12px;color:var(--muted)">Compacted: ' + parts.join(', ') + '</div>';
}

async function compactExp(id) {
  // Dry-run first to show what will be removed
  const preview = await postApi('/api/bulk-compact', {ids: [id], mode: 'deep', dry_run: true});
  if (preview.error) { alert('Error: ' + preview.error); return; }
  if (!preview.will_remove || !preview.will_remove.length) {
    alert('Nothing to compact \u2014 this experiment has no stored diffs or cell data to strip.');
    return;
  }
  const msg = 'Compact this experiment?\n\nWill remove:\n'
    + preview.will_remove.map(function(s) { return '  \u2022 ' + s; }).join('\n')
    + '\n\nTotal: ~' + preview.total_fmt
    + '\n\nWhat is kept:\n  \u2022 All metrics, params, and results\n  \u2022 Variable change history\n  \u2022 Cell execution order and lineage\n  \u2022 Artifact records'
    + '\n\nThis cannot be undone.';
  if (!confirm(msg)) return;
  const d = await postApi('/api/bulk-compact', {ids: [id], mode: 'deep'});
  if (d.error) { alert('Compact error: ' + d.error); return; }
  if (d.ok && d.freed > 0) {
    owlSay('Compacted! Freed ~' + fmtFreed(d.freed), 'owl-bounce');
    await loadExperiments();
    // refreshDetail restores the active tab (and reloads its content) itself.
    await refreshDetail(id);
  } else {
    alert('Nothing to compact \u2014 already fully compacted.');
  }
}

async function compactDiff(id) {
  return compactExp(id);
}

async function exportDiff(id) {
  const d = await postApi('/api/experiment/' + id + '/export-diff');
  if (d.error) { alert(d.error); return; }
  const blob = new Blob([d.markdown], {type: 'text/markdown'});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = d.filename || 'diff.md';
  a.click();
  URL.revokeObjectURL(a.href);
  owlSay('Exported diff as markdown');
}

async function bulkCompact() {
  const ids = [...selectedIds];
  if (!ids.length) { alert('Select experiments first (click checkboxes in the list).'); return; }
  const preview = await postApi('/api/bulk-compact', {ids, mode: 'deep', dry_run: true});
  if (preview.error) { alert('Error: ' + preview.error); return; }
  if (!preview.will_remove || !preview.will_remove.length) {
    alert('Nothing to compact \u2014 selected experiments have no stored diffs or cell data.');
    return;
  }
  const msg = 'Compact ' + ids.length + ' experiment(s)?\n\nWill remove:\n'
    + preview.will_remove.map(function(s) { return '  \u2022 ' + s; }).join('\n')
    + '\n\nTotal: ~' + preview.total_fmt
    + '\n\nThis cannot be undone.';
  if (!confirm(msg)) return;
  const d = await postApi('/api/bulk-compact', {ids, mode: 'deep'});
  if (d.error) { alert('Compact error: ' + d.error); return; }
  if (d.ok && d.freed > 0) {
    owlSay('Compacted ' + d.compacted + ' experiment(s), freed ~' + fmtFreed(d.freed), 'owl-bounce');
    await loadExperiments();
    if (currentDetailId) await refreshDetail(currentDetailId);
  } else {
    alert('Nothing to compact \u2014 already fully compacted.');
  }
}

// ── Add artifact ─────────────────────────────────────────────────────────────

async function addArtifact(id) {
  const label = document.getElementById('art-label-' + id).value.trim();
  const path = document.getElementById('art-path-' + id).value.trim();
  if (!label && !path) { alert('Provide a label or path'); return; }
  const d = await postApi('/api/experiment/' + id + '/artifact', {label, path});
  if (d.ok) { refreshDetail(id); }
  else alert(d.error || 'Failed');
}

// ── Edit/delete tags, notes, artifacts ────────────────────────────────────────



async function deleteTagInline(id, tag) {
  // Optimistic removal: hide the tag chip immediately
  const exp = allExperiments.find(e => e.id === id);
  if (exp) exp.tags = (exp.tags||[]).filter(t => t !== tag);
  const area = document.getElementById('detail-tags-area');
  if (area) {
    area.querySelectorAll('.tag-removable').forEach(el => {
      if (el.textContent.trim().replace(/×$/, '').trim() === '#' + tag) el.remove();
    });
  }
  const d = await postApi('/api/experiment/' + id + '/delete-tag', {tag});
  if (d.ok) { loadAllTags(); loadTodos(); loadCommands(); loadExperiments().then(() => refreshDetail(id)); }
}

function startDetailNoteEdit(id, el) {
  const currentText = el.textContent.trim();
  const isPlaceholder = el.querySelector('span[style]') !== null;
  const textarea = document.createElement('textarea');
  textarea.className = 'notes-edit-area';
  textarea.value = isPlaceholder ? '' : currentText;
  textarea.style.cssText = 'width:100%;box-sizing:border-box;min-height:70px;font-size:13px;font-family:inherit;border:1px solid var(--blue);border-radius:4px;padding:7px 9px';
  el.innerHTML = '';
  el.appendChild(textarea);
  // The field opens on a single click, so the handler has to come off while
  // the editor is up — a click into the textarea bubbles back to this element
  // and would rebuild the editor under the cursor. refreshDetail re-renders
  // the span (handler and all) when the edit finishes.
  el.onclick = null;
  el.removeAttribute('onclick');
  textarea.focus();

  let saved = false;
  async function doSave() {
    if (saved) return;
    saved = true;
    const notes = textarea.value;
    await postApi('/api/experiment/' + id + '/edit-notes', {notes});
    const exp = allExperiments.find(e => e.id === id);
    if (exp) exp.notes = notes;
    refreshDetail(id);
  }
  textarea.addEventListener('blur', doSave);
  textarea.addEventListener('keydown', (ev) => {
    if (ev.key === 'Enter' && !ev.shiftKey) { ev.preventDefault(); textarea.blur(); }
    if (ev.key === 'Escape') { saved = true; refreshDetail(id); }
  });
}


async function deleteArtifact(id, label, path) {
  if (!confirm('Delete artifact "' + label + '"?')) return;
  const d = await postApi('/api/experiment/' + id + '/delete-artifact', {label, path});
  if (d.ok) { refreshDetail(id); }
  else alert(d.error || 'Failed');
}

async function editArtifact(id, oldLabel, oldPath) {
  const newLabel = prompt('Edit label:', oldLabel);
  if (newLabel === null) return;
  const newPath = prompt('Edit path:', oldPath);
  if (newPath === null) return;
  const d = await postApi('/api/experiment/' + id + '/edit-artifact', {old_label: oldLabel, old_path: oldPath, new_label: newLabel.trim(), new_path: newPath.trim()});
  if (d.ok) { refreshDetail(id); }
  else alert(d.error || 'Failed');
}

function parseCSV(text, delimiter) {
  const rows = [];
  let current = '', inQuote = false, row = [], i = 0;
  while (i < text.length) {
    const ch = text[i];
    if (inQuote) {
      if (ch === '"' && text[i+1] === '"') { current += '"'; i += 2; }
      else if (ch === '"') { inQuote = false; i++; }
      else { current += ch; i++; }
    } else {
      if (ch === '"') { inQuote = true; i++; }
      else if (ch === delimiter) { row.push(current); current = ''; i++; }
      else if (ch === '\n' || (ch === '\r' && text[i+1] === '\n')) { row.push(current); current = ''; rows.push(row); row = []; i += (ch === '\r' ? 2 : 1); }
      else if (ch === '\r') { row.push(current); current = ''; rows.push(row); row = []; i++; }
      else { current += ch; i++; }
    }
  }
  if (current || row.length) { row.push(current); rows.push(row); }
  return rows.filter(r => r.length > 0 && !(r.length === 1 && r[0] === ''));
}

// Server-side truncation notice: the server sends a window of a large text
// file rather than the whole thing (X-Exptrack-Truncated: head|tail), so the
// viewer has to say the file continues past what it is showing.
function _truncationNote(where, totalBytes) {
  if (!where) return '';
  const which = where === 'tail' ? 'end' : 'start';
  return '<div style="color:var(--status-warning);margin-bottom:8px">' +
         'Large file (' + esc(fmtBytes(totalBytes)) + ') — showing the ' + which +
         ' of it only.</div>';
}

async function viewLogFile(path, label) {
  try {
    const resp = await fetch(fileUrl(path));
    if (!resp.ok) { alert('Could not load file: ' + resp.statusText); return; }
    const text = await resp.text();
    // Whether the server sent a window rather than the file is a fact the row
    // and line counts below both depend on — read it once, don't infer it from
    // the truthiness of the note's markup.
    const srvTrunc = resp.headers.get('X-Exptrack-Truncated') || '';
    const truncNote = _truncationNote(
      srvTrunc, parseInt(resp.headers.get('X-Exptrack-Total-Bytes') || '0', 10));

    const overlay = document.createElement('div');
    overlay.className = 'img-modal-overlay';
    overlay.onclick = (ev) => { if (ev.target === overlay) overlay.remove(); };

    const content = document.createElement('div');
    content.className = 'img-modal-content';
    content.style.cssText = 'max-width:900px;width:90vw';

    const ext = (path || '').split('.').pop().toLowerCase();
    const isCSV = ext === 'csv';
    const isTSV = ext === 'tsv';
    const isJSON = ext === 'json' || ext === 'jsonl';

    let logHtml = '<div class="img-modal-header">';
    logHtml += '<span class="img-modal-name">' + esc(label) + '</span>';

    if (isCSV || isTSV) {
      // CSV/TSV table rendering
      const delimiter = isTSV ? '\t' : ',';
      const rows = parseCSV(text, delimiter);
      const maxRows = 200;
      const truncated = rows.length > maxRows + 1;
      logHtml += '<span style="color:var(--muted);font-size:12px;margin-left:8px">' + (rows.length - 1) + (srvTrunc ? ' rows loaded' : ' rows') + (truncated ? ' (showing first ' + maxRows + ')' : '') + '</span>';
      logHtml += '<button class="img-modal-close" onclick="this.closest(\'.img-modal-overlay\').remove()">&times;</button>';
      logHtml += '</div>';
      logHtml += '<div style="max-height:70vh;overflow:auto">';
      logHtml += truncNote;
      if (rows.length > 0) {
        logHtml += '<table class="metrics-table" style="font-size:12px;white-space:nowrap">';
        // Header row
        logHtml += '<tr>';
        for (const cell of rows[0]) {
          logHtml += '<th style="position:sticky;top:0;background:var(--card-bg);z-index:1">' + esc(cell) + '</th>';
        }
        logHtml += '</tr>';
        // Data rows
        const displayRows = truncated ? rows.slice(1, maxRows + 1) : rows.slice(1);
        for (const row of displayRows) {
          logHtml += '<tr>';
          for (const cell of row) {
            const num = parseFloat(cell);
            const isNum = !isNaN(num) && cell.trim() !== '';
            logHtml += '<td' + (isNum ? ' style="text-align:right;font-variant-numeric:tabular-nums"' : '') + '>' + esc(cell) + '</td>';
          }
          logHtml += '</tr>';
        }
        logHtml += '</table>';
      }
      logHtml += '</div>';
    } else if (isJSON) {
      // JSON / JSONL rendering
      logHtml += '<button class="img-modal-close" onclick="this.closest(\'.img-modal-overlay\').remove()">&times;</button>';
      logHtml += '</div>';
      let jsonRows = [];
      if (ext === 'jsonl') {
        jsonRows = text.trim().split('\n').filter(l => l.trim()).map(l => { try { return JSON.parse(l); } catch { return null; } }).filter(Boolean);
      } else {
        try {
          const parsed = JSON.parse(text);
          jsonRows = Array.isArray(parsed) ? parsed : [parsed];
        } catch { jsonRows = []; }
      }
      if (jsonRows.length && typeof jsonRows[0] === 'object' && !Array.isArray(jsonRows[0])) {
        const keys = [...new Set(jsonRows.flatMap(r => Object.keys(r)))];
        const maxRows = 200;
        const truncated = jsonRows.length > maxRows;
        logHtml += '<div style="max-height:70vh;overflow:auto">';
        logHtml += truncNote;
        logHtml += '<table class="metrics-table" style="font-size:12px;white-space:nowrap">';
        logHtml += '<tr>' + keys.map(k => '<th style="position:sticky;top:0;background:var(--card-bg);z-index:1">' + esc(k) + '</th>').join('') + '</tr>';
        const display = truncated ? jsonRows.slice(0, maxRows) : jsonRows;
        for (const row of display) {
          logHtml += '<tr>' + keys.map(k => { const v = row[k]; const s = v !== undefined ? String(v) : ''; const num = parseFloat(s); const isNum = !isNaN(num) && s.trim() !== '' && typeof v === 'number'; return '<td' + (isNum ? ' style="text-align:right;font-variant-numeric:tabular-nums"' : '') + '>' + esc(s.slice(0,100)) + '</td>'; }).join('') + '</tr>';
        }
        logHtml += '</table></div>';
      } else {
        // Fallback: pretty-print JSON
        logHtml += '<div class="source-view" style="max-height:70vh;font-size:12px;line-height:1.5"><pre>' + esc(JSON.stringify(jsonRows.length === 1 ? jsonRows[0] : jsonRows, null, 2).slice(0, 50000)) + '</pre></div>';
      }
    } else {
      // Plain text / log rendering (original behavior)
      const lines = text.split('\n');
      const maxLines = 500;
      const truncated = lines.length > maxLines;
      const displayLines = truncated ? lines.slice(-maxLines) : lines;
      const lineNums = displayLines.map((_, i) => (truncated ? lines.length - maxLines + i + 1 : i + 1));
      // With a server-side window the file has more lines than we received,
      // so don't report this count as the file's length.
      logHtml += '<span style="color:var(--muted);font-size:12px;margin-left:8px">' +
                 lines.length + (srvTrunc ? ' lines loaded' : ' lines') + '</span>';
      logHtml += '<button class="img-modal-close" onclick="this.closest(\'.img-modal-overlay\').remove()">&times;</button>';
      logHtml += '</div>';
      logHtml += '<div class="source-view" style="max-height:70vh;font-size:12px;line-height:1.5">';
      logHtml += truncNote;
      if (truncated) logHtml += '<div style="color:var(--muted);margin-bottom:8px">Showing last ' + maxLines + ' of ' + lines.length + ' lines</div>';
      for (let i = 0; i < displayLines.length; i++) {
        logHtml += '<div><span class="line-num">' + lineNums[i] + '</span>' + esc(displayLines[i]) + '</div>';
      }
      logHtml += '</div>';
    }

    content.innerHTML = logHtml;
    overlay.appendChild(content);
    document.body.appendChild(overlay);

    const handler = (ev) => { if (ev.key === 'Escape') { overlay.remove(); document.removeEventListener('keydown', handler); } };
    document.addEventListener('keydown', handler);
  } catch(e) {
    alert('Error loading file: ' + e.message);
  }
}

