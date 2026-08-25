// ── Run picker ───────────────────────────────────────────────────────────────
// One searchable list of runs, shared by every surface that has to ask "which
// runs?". Before this, all three of them asked with a native <select>: Pair
// Compare with two single selects, Multi Compare with a `multiple` list box
// needing Ctrl/Cmd-click, and the parameter matrix not at all — it analysed
// whatever the experiment list happened to be filtered to, so choosing a set
// meant leaving the view and rewriting a search box.
//
// A native <select> can only show one line of text per run, and auto-named runs
// differ in a tail that line cuts off — so the picker's whole job was performed
// by the run's *name*, which is exactly what the user doesn't know. Here each
// run is a row carrying its parameters, status and date, and the search box
// matches all of them: `lr=0.01`, `failed`, a script name, a date, an id
// prefix. You can find the run you mean without ever knowing what it is called.
//
// The run list, its paging and its truncation notice are the Compare pickers'
// (`_loadCmpExps` in js/detail.js) — one cache, so the picker can never be
// searching a different set of runs than the filter box beside it.

// Rows rendered per query. The cache can hold the whole project; painting
// thousands of rows on every keystroke is what the search box exists to avoid.
// Anything beyond this is *stated*, never silently dropped.
const RP_MAX_ROWS = 300;
// Params shown per row before the rest are folded into a "+N" chip.
const RP_MAX_CHIPS = 6;

let _rpSelected = new Set();
let _rpMode = 'multi';
let _rpOnConfirm = null;
let _rpConfirmLabel = 'Use selection';
let _rpQuery = '';

// `opts`: {title, mode: 'multi'|'single', preselect, confirmLabel, onConfirm(ids)}.
// The picks are handed to `onConfirm` as an argument and never written to a
// global for the caller to read back — the same rule `compareRuns(ids)` follows,
// and for the same reason: three surfaces use this and each owns a different
// selection.
async function openRunPicker(opts) {
  const o = opts || {};
  _rpMode = o.mode === 'single' ? 'single' : 'multi';
  _rpSelected = new Set(o.preselect ? [...o.preselect] : []);
  _rpOnConfirm = o.onConfirm || null;
  _rpConfirmLabel = o.confirmLabel || 'Use selection';
  _rpQuery = '';
  _rpMount(o.title || 'Choose runs');
  // Painted before the fetch resolves so the dialog never opens as a blank
  // rectangle; the row list says it is loading until the cache is warm.
  _rpRenderRows();
  await _loadCmpExps();
  _rpRenderRows();
  const box = document.getElementById('rp-search');
  if (box) box.focus();
}

function _rpMount(title) {
  closeRunPicker();
  const overlay = document.createElement('div');
  overlay.className = 'dc-overlay rp-overlay';
  overlay.id = 'run-picker-overlay';
  overlay.innerHTML =
    '<div class="dc-dialog rp-dialog">' +
      '<div class="dc-header"><h3>' + esc(title) + '</h3>' +
        '<button class="dc-close" onclick="closeRunPicker()" title="Close">&times;</button></div>' +
      '<div class="rp-toolbar">' +
        '<input type="search" id="rp-search" class="rp-search" oninput="onRunPickerSearch()" ' +
          'placeholder="Search name, id, param (lr=0.01), status, script, tag, date">' +
        '<span class="rp-count" id="rp-count"></span>' +
      '</div>' +
      '<div class="dc-body rp-body" id="rp-rows"></div>' +
      '<div class="dc-footer">' +
        '<div class="dc-footer-left" id="rp-bulk"></div>' +
        '<div class="dc-footer-right">' +
          '<button class="dc-button" onclick="closeRunPicker()">Cancel</button>' +
          '<button class="dc-button primary" id="rp-confirm" onclick="rpConfirm()"></button>' +
        '</div>' +
      '</div>' +
    '</div>';
  overlay.addEventListener('click', ev => { if (ev.target === overlay) closeRunPicker(); });
  document.addEventListener('keydown', _rpEsc);
  document.body.appendChild(overlay);
}

function _rpEsc(ev) {
  if (ev.key === 'Escape') closeRunPicker();
}

function closeRunPicker() {
  document.removeEventListener('keydown', _rpEsc);
  const el = document.getElementById('run-picker-overlay');
  if (el) el.remove();
}

const onRunPickerSearch = debounce(function () {
  const box = document.getElementById('rp-search');
  _rpQuery = box ? box.value.trim().toLowerCase() : '';
  _rpRenderRows();
}, 120);

// Matches over the cache's `hay` — the run's id, name, every user parameter as
// `key=value`, its script, tags, status and date — so a run is reachable by
// anything the user actually remembers about it.
//
// The query is the only thing that decides what is listed. Selected runs were
// briefly force-included so a pick could always be un-ticked — which sounds
// careful and is not: the matrix opens this dialog with its *entire* analysed
// set preselected, so every row was exempt from the filter and typing narrowed
// nothing at all. A search box that cannot narrow is worse than no search box,
// because it looks like it worked. Picks the query hides are reported in the
// footer instead, and Clear is always one press away.
function _rpFiltered() {
  if (!_rpQuery) return _cmpExps;
  return _cmpExps.filter(e => e.hay.includes(_rpQuery));
}

function _rpRenderRows() {
  const host = document.getElementById('rp-rows');
  if (!host) return;
  if (!_cmpExps.length) {
    host.innerHTML = '<div class="rp-empty">Loading runs…</div>';
    _rpRenderFooter(0, 0);
    return;
  }
  const rows = _rpFiltered();
  const shown = rows.slice(0, RP_MAX_ROWS);
  host.innerHTML = shown.length
    ? shown.map(_rpRowHtml).join('') + _rpNoticesHtml(rows.length)
    : '<div class="rp-empty">No run matches <code>' + esc(_rpQuery) + '</code>.' +
      _rpNoticesHtml(0) + '</div>';
  _rpRenderFooter(rows.length, _cmpExps.length);
}

// Two different reasons the list in front of the user is not every run, and
// they lead to different actions: too many matched to paint (narrow the
// search), or the cache itself is a page of the project (load the rest).
function _rpNoticesHtml(nMatched) {
  let h = '';
  if (nMatched > RP_MAX_ROWS) {
    h += '<div class="rp-notice">Showing the first ' + RP_MAX_ROWS + ' of ' +
      nMatched.toLocaleString() + ' matching runs — narrow the search to see the rest.</div>';
  }
  if (_cmpHasMore) {
    const of = _cmpTotal > _cmpExps.length ? ' of ' + _cmpTotal.toLocaleString() : '';
    h += '<div class="rp-notice">Searching the ' + _cmpExps.length.toLocaleString() +
      ' most recent runs' + of + '. ' +
      '<button class="btn-sm" onclick="rpLoadAll()">Load all runs</button></div>';
  }
  return h;
}

async function rpLoadAll() {
  const btn = document.querySelector('#rp-rows .rp-notice button');
  if (btn) { btn.disabled = true; btn.textContent = 'Loading…'; }
  await _loadCmpExps(true, true);
  _rpRenderRows();
}

function _rpRowHtml(entry) {
  const e = entry.e || {};
  const on = _rpSelected.has(entry.id);
  const params = Object.entries(e.params || {}).filter(([k]) => isUserParamKey(k));
  const chips = params.slice(0, RP_MAX_CHIPS).map(([k, v]) =>
    '<span class="rp-chip">' + esc(paramColLabel(k)) + '=' + esc(String(v)) + '</span>').join('');
  const more = params.length > RP_MAX_CHIPS
    ? '<span class="rp-chip rp-chip-more" title="' +
      esc(params.length - RP_MAX_CHIPS + ' more parameters') + '">+' +
      (params.length - RP_MAX_CHIPS) + '</span>'
    : '';
  return '<div class="rp-row' + (on ? ' rp-on' : '') + '" role="button" tabindex="0" ' +
    'data-id="' + esc(entry.id) + '" ' +
    'onclick="rpToggle(\'' + escJsAttr(entry.id) + '\')">' +
    (_rpMode === 'multi'
      ? '<input type="checkbox" class="rp-cb"' + (on ? ' checked' : '') +
        ' tabindex="-1" aria-label="Select ' + esc(e.name || entry.id) + '">'
      : '<span class="rp-cb rp-cb-single" aria-hidden="true">›</span>') +
    '<div class="rp-main">' +
      '<div class="rp-line1">' +
        '<span class="rp-status rp-status-' + esc(e.status || 'unknown') + '">' +
          esc(e.status || '—') + '</span>' +
        '<span class="rp-name">' + esc(e.name || entry.id) + '</span>' +
        '<span class="rp-id">' + esc(String(entry.id).slice(0, 6)) + '</span>' +
      '</div>' +
      '<div class="rp-line2">' + (chips + more || '<span class="rp-noparams">no parameters captured</span>') +
        '<span class="rp-date">' + esc(fmtDt(e.created_at)) + '</span>' +
      '</div>' +
    '</div></div>';
}

// Footer state: the counts and the bulk actions, which only exist in multi
// mode — "Select all shown" on a picker that takes one run is an action whose
// result cannot be honoured.
function _rpRenderFooter(nShown, nTotal) {
  const count = document.getElementById('rp-count');
  if (count) {
    count.textContent = nShown === nTotal
      ? nTotal.toLocaleString() + ' runs'
      : nShown.toLocaleString() + ' of ' + nTotal.toLocaleString() + ' runs';
  }
  const bulk = document.getElementById('rp-bulk');
  if (bulk) {
    // Picks the current query hides are counted, not hidden: confirming takes
    // the whole selection, so a footer reading "4 selected" over a list showing
    // one of them has to say where the other three went.
    const shownIds = new Set(_rpFiltered().map(e => e.id));
    const offscreen = [..._rpSelected].filter(id => !shownIds.has(id)).length;
    bulk.innerHTML = _rpMode === 'multi'
      ? '<button class="dc-button" onclick="rpSelectAllShown()">Select all shown</button>' +
        '<button class="dc-button" onclick="rpClearSelection()">Clear</button>' +
        '<span class="rp-selcount">' + _rpSelected.size + ' selected' +
        (offscreen ? ' (' + offscreen + ' not matching this search)' : '') + '</span>'
      : '<span class="rp-selcount">Click a run to choose it</span>';
  }
  const go = document.getElementById('rp-confirm');
  if (go) {
    go.textContent = _rpMode === 'multi'
      ? _rpConfirmLabel + ' (' + _rpSelected.size + ')' : _rpConfirmLabel;
    go.style.display = _rpMode === 'multi' ? '' : 'none';
  }
}

// A click on a row in single mode *is* the answer — an extra Confirm press for
// a choice that cannot be ambiguous is a step with no decision in it.
function rpToggle(id) {
  if (_rpMode === 'single') {
    _rpSelected = new Set([id]);
    rpConfirm();
    return;
  }
  if (_rpSelected.has(id)) _rpSelected.delete(id);
  else _rpSelected.add(id);
  // Repaint the row in place rather than the list: rebuilding it would lose the
  // scroll position halfway through assembling a selection.
  const row = document.querySelector('#rp-rows .rp-row[data-id="' + CSS.escape(id) + '"]');
  if (row) {
    row.classList.toggle('rp-on', _rpSelected.has(id));
    const cb = row.querySelector('.rp-cb');
    if (cb) cb.checked = _rpSelected.has(id);
  }
  _rpRenderFooter(_rpFiltered().length, _cmpExps.length);
}

// "Shown", not "all": the button acts on the rows in front of the user, which
// is what a search box narrowing them to nine runs promises it will do.
function rpSelectAllShown() {
  _rpFiltered().slice(0, RP_MAX_ROWS).forEach(e => _rpSelected.add(e.id));
  _rpRenderRows();
}

function rpClearSelection() {
  _rpSelected.clear();
  _rpRenderRows();
}

function rpConfirm() {
  const ids = [..._rpSelected];
  const cb = _rpOnConfirm;
  closeRunPicker();
  if (cb) cb(ids);
}
