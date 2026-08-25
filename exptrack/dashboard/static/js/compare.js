

// ── Export ──────────────────────────────────────────────────────────────────────

let _exportCache = {};

async function exportExp(id) {
  owlSpeak('export');
  _exportCache = {};
  const container = document.getElementById('export-container');
  const fmts = ['json','markdown','csv','tsv','plain'];
  let btns = fmts.map(f =>
    '<button class="action-btn" id="export-btn-' + f + '" onclick="doExport(\'' + id + '\',\'' + f + '\')">' +
    f.toUpperCase().replace('PLAIN','Plain Text').replace('MARKDOWN','Markdown') + '</button>'
  ).join('');
  container.innerHTML = '<div class="export-panel">' +
    '<div class="export-actions">' + btns +
    '<button class="action-btn" onclick="downloadExport()">Download File</button>' +
    '<button class="action-btn" onclick="copyExport()">Copy to Clipboard</button>' +
    '<button class="action-btn" onclick="this.closest(\'.export-panel\').remove()">Close</button>' +
    '</div><pre id="export-content" style="display:none"></pre></div>';
}

function toggleDetailExport(btn) {
  const menu = btn.nextElementSibling;
  menu.style.display = menu.style.display === 'none' ? 'flex' : 'none';
}
function closeDetailExport(btn) {
  btn.closest('.export-dropdown-menu').style.display = 'none';
}

async function _fetchExportText(id, fmt) {
  const ext = {json:'.json', 'json-full':'.full.json', markdown:'.md', csv:'.csv',
               tsv:'.tsv', plain:'.txt',
               params:'.params.txt', 'params-flags':'.params.txt', 'params-json':'.params.json',
               'params-md':'.params.md', 'params-tsv':'.params.tsv'};
  // 'json-full' is the same endpoint asked for the complete (round-trippable)
  // payload — every metric point, every artifact — rather than the summary.
  const full = fmt === 'json-full';
  const fileExt = ext[fmt] || '.txt';
  if (full) fmt = 'json';
  let text;
  if (fmt === 'csv' || fmt === 'tsv') {
    const data = await postApi('/api/bulk-export', {ids: [id], format: fmt});
    // api()/postApi() report the failure themselves; returning null lets the
    // callers stop rather than throwing mid-download on a null body.
    if (!data || data.error) return null;
    text = data.content || JSON.stringify(data, null, 2);
  } else {
    const data = await api('/api/export/' + id + '?format=' + (fmt === 'plain' ? 'json' : fmt) +
                           (full ? '&full=1' : ''));
    if (!data || data.error) return null;
    if (fmt === 'markdown') text = data.markdown || JSON.stringify(data, null, 2);
    else if (fmt === 'plain') text = _formatExpPlainText(data.data || data);
    else if (fmt.startsWith('params')) {
      text = data.params_text != null ? data.params_text : JSON.stringify(data, null, 2);
    }
    else text = JSON.stringify(data, null, 2);
  }
  const exp = allExperiments.find(e => e.id.startsWith(id));
  const name = exp ? exp.name.replace(/[^a-zA-Z0-9_-]/g, '_') : id.slice(0,8);
  const mime = (fmt === 'json' || fmt === 'params-json') ? 'application/json' : 'text/plain';
  return {text, filename: name + fileExt, mime};
}

async function downloadExportFmt(id, fmt) {
  owlSpeak('export');
  const d = await _fetchExportText(id, fmt);
  if (!d) return;
  await saveOrDownload(d.text, d.filename, d.mime);
}

async function copyExportFmt(id, fmt) {
  owlSpeak('export');
  const d = await _fetchExportText(id, fmt);
  if (!d) return;
  navigator.clipboard.writeText(d.text).then(() => owlSay('Copied ' + fmt.toUpperCase() + ' to clipboard!'));
}

// Legacy compat — used by bulk export sidebar
async function doExport(id, fmt) { await downloadExportFmt(id, fmt); }
function downloadExport() {}
function copyExport() {}

// ── Compare ────────────────────────────────────────────────────────────────────

let onlyDiffers = false;

// `preselect` is forwarded to the multi picker — a caller comparing its own set
// of runs passes that set, rather than writing it into the global selection to
// be read back (see compareRuns in js/detail.js).
// Kept as the name every caller already uses, but there is one view now: this
// only stages the runs. Compare had two tabs answering the same question at
// different arities, and the split cost more than it bought — the code diff,
// the variable table and the A/B image overlay lived on the pair tab and were
// unreachable from a three-run comparison, while the run picker, the chip
// staging, the config table and the curve overlay lived on the multi tab and
// were unreachable from a two-run one. The panels that genuinely need exactly
// two runs now appear when the set happens to be two.
function switchCompareTab(_tab, preselect) {
  populateMultiCompareSelector(preselect);
}

// ── Multi Compare: which runs ───────────────────────────────────────────────
// The set being compared, held here rather than read off a `<select multiple>`.
// The list box needed Ctrl/Cmd-click to pick a second run (stated in fine print
// under it, and routinely missed — one plain click silently *replaced* the
// selection), and it could only show one line per run, so choosing depended on
// recognizing a name. Now the ids live here, the chips below the button show
// what is staged, and the picking happens in the shared run picker, which can
// search parameters.
let _multiPicked = new Set();

// `preselect` is the set of ids to stage, defaulting to the table selection —
// a caller comparing its own set of runs (the parameter matrix) passes that
// set instead, rather than writing it into `selectedIds` to be read back here.
async function populateMultiCompareSelector(preselect) {
  _multiPicked = new Set(preselect ? [...preselect] : [...selectedIds]);
  renderMultiPicked();
  // The labels come from the shared cache; the staged ids are already correct
  // without it, so the chips are painted first and relabelled once it lands.
  if (await _loadCmpExps()) renderMultiPicked();
}

function renderMultiPicked() {
  const host = document.getElementById('cmp-multi-picked');
  if (!host) return;
  const ids = [..._multiPicked];
  host.innerHTML = ids.length
    // Middle-ellipsis, not a CSS overflow clip: clipping cuts the tail, which
    // is the only part of an auto-generated name that differs — six chips all
    // reading `Aug12_train__lr0.05_epochs20_modelcnn…` name one run six times.
    ? ids.map(id => '<span class="cmp-chip" title="' + esc(_cmpLabelFor(id)) + '">' +
        esc(midEllipsis(_cmpLabelFor(id), 30)) +
        '<button class="cmp-chip-x" title="Remove from this comparison" ' +
        'onclick="unpickMultiRun(\'' + escJsAttr(id) + '\')">&times;</button></span>').join('')
    : '<span class="cmp-picked-empty">No runs chosen yet — <strong>Choose runs…</strong> ' +
      'opens a searchable list of every run with its parameters.</span>';
  const go = document.getElementById('cmp-multi-go');
  if (go) {
    go.textContent = ids.length ? 'Compare ' + ids.length + ' runs' : 'Compare';
    go.disabled = ids.length < 2;
    go.title = ids.length < 2 ? 'Choose at least two runs' : '';
  }
}

function openMultiRunPicker() {
  openRunPicker({
    title: 'Choose runs to compare',
    mode: 'multi',
    preselect: _multiPicked,
    confirmLabel: 'Compare these runs',
    onConfirm: ids => {
      _multiPicked = new Set(ids);
      renderMultiPicked();
      if (ids.length >= 2) doMultiCompare(ids);
    },
  });
}

function unpickMultiRun(id) {
  _multiPicked.delete(id);
  renderMultiPicked();
}

// Clearing the staged set has to clear what that set produced. Emptying only
// the chips left the whole rendered comparison — tables, curves, bar charts —
// standing under a control bar that said no runs were chosen, so the one
// visible thing on the page was the thing Clear was pressed to get rid of, and
// the button read as broken. `_discardComparison` is the single teardown:
// the token bump matters as much as the blank, or a comparison already in
// flight lands after the clear and repaints everything that was just removed.
function clearMultiPicked() {
  _multiPicked.clear();
  renderMultiPicked();
  _discardComparison();
}

function _discardComparison() {
  _multiCmpToken++;
  Object.values(multiCharts).forEach(c => c.destroy());
  multiCharts = {};
  _lastComparison = null;
  const host = document.getElementById('multi-compare-result');
  if (host) host.innerHTML = '';
  // The address named a comparison that no longer exists; leaving it there
  // makes Copy link offer a link to nothing and Back restore what was cleared.
  if (String(window.location.hash || '').startsWith('#compare=')) _clearCompareHash();
}

// Staging the table's selection is a copy, not a live binding: editing the
// comparison must not reach back and change what the table has ticked.
function multiPickFromTable() {
  if (!selectedIds.size) { owlSay('Nothing is selected in the experiments table.'); return; }
  _multiPicked = new Set(selectedIds);
  renderMultiPicked();
}

function doMultiCompareFromSelector() {
  const ids = [..._multiPicked];
  if (ids.length < 2) { owlSay('Choose at least 2 experiments'); return; }
  doMultiCompare(ids);
}

function selectAllMultiCompare() {
  _multiPicked = new Set(_cmpExps.map(e => e.id));
  renderMultiPicked();
}

// Files whose working-tree diff differs between two runs — i.e. code that moved
// between the attempts but isn't either run's own script. Both runs' stored
// `git_diff` bodies are already on the /api/compare payload, so this needs no
// request; a sentinel ('[compacted…]', '[capture-failed]') is a status, not diff
// text, so a pair carrying one is skipped rather than reported as a difference.
function _cmpWorkingTreeFiles(a, b) {
  const da = (a && a.git_diff) || '', db = (b && b.git_diff) || '';
  if (!da && !db) return [];
  // Every diff sentinel is a bracketed marker ('[compacted…]', '[capture-failed]',
  // '[diff-unavailable]') — a status, never diff text. Two runs carrying
  // different markers are not two runs whose code differed.
  if (da.startsWith('[') || db.startsWith('[')) return [];
  if (da === db || typeof _parseDiff !== 'function') return [];
  // Per file, keep two things: a key for "did this differ between the runs?",
  // and the file's post-image *as this run saw it* — the hunks' context and
  // added lines, i.e. what the file actually contained when the run started.
  // Diffing the two post-images is what turns "helper.py differed" into the
  // line that moved.
  const byFile = d => {
    const m = {};
    for (const f of _parseDiff(String(d)).files) {
      if (!f.hunks.length) continue;
      const key = f.hunks.map(
        h => h.header + '\n' + h.rows.map(r => r.kind + r.text).join('\n')).join('\n');
      const post = f.hunks.map(
        h => h.rows.filter(r => r.kind !== 'del').map(r => r.text).join('\n')).join('\n');
      m[_shortFileLabel(f.header)] = { key, post };
    }
    return m;
  };
  const ma = byFile(da), mb = byFile(db);
  return [...new Set([...Object.keys(ma), ...Object.keys(mb)])]
    .filter(k => (ma[k] || {}).key !== (mb[k] || {}).key)
    .sort()
    .map(k => ({ file: k, a: (ma[k] || {}).post || '', b: (mb[k] || {}).post || '' }));
}

// One code-diff block, used by both branches of the Code changes panel.
// `lineNumbers` is false for a working-tree reconstruction, whose line numbers
// would be those of the hunks rather than of the file.
function _cmpCodeBlockHtml(label, a, b, lineNumbers) {
  const rows = (typeof _lineDiffRows === 'function') ? _lineDiffRows(a || '', b || '') : null;
  return '<div class="cmp-code-block"><div class="cmp-code-label">' + esc(label) + '</div>'
    + (rows ? _renderDiffRows(rows, lineNumbers)
            : '<pre class="cell-code">' + esc(b || a || '') + '</pre>')
    + '</div>';
}

// Render the "Code changes" panel for the Compare view: the cell edit (or
// script-source edit) between the two attempts, using the shared line/word-diff
// renderer. `cd` is the /api/compare `code_diff` payload
// ({mode, cells:[{pos,label,a,b}]}). Older attempt → newer attempt.
// Which run is the "before" in this panel is decided by the *server*, which
// orders the pair chronologically (see queries.compare_run_code) — while the
// tables above keep the order the user picked. So the panel could read in the
// opposite direction to the columns beside it, and its working-tree fallback,
// which used pick order, could disagree with the panel's own main branch.
// Everything below runs in the server's order and says whose code is whose.
function _cmpCodeOrder(cd, expA, expB) {
  const byId = {};
  if (expA && expA.id) byId[expA.id] = expA;
  if (expB && expB.id) byId[expB.id] = expB;
  const before = byId[cd && cd.base_id] || expA;
  const after = byId[cd && cd.new_id] || expB;
  return [before, after];
}

function _cmpDirectionNote(before, after) {
  const nb = (before && before.name) || 'the earlier run';
  const na = (after && after.name) || 'the later run';
  return '<p class="cmp-code-dir">' + esc(nb) + ' \u2192 ' + esc(na)
    + ' (oldest first, whichever order you picked them)</p>';
}

function _renderCompareCodeDiff(cd, expA, expB) {
  if (!cd || !cd.mode || cd.mode === 'none') return '';
  const [before, after] = _cmpCodeOrder(cd, expA, expB);
  const cells = cd.cells || [];
  const kind = cd.mode === 'script' ? 'Script source' : 'Cell edits';
  if (!cells.length) {
    // "No code change" is only true of the code this compares — the run's own
    // script or cells. A run routinely differs from the last one by an edit to
    // a file it *imports*: run train.py, tweak helper.py. That edit is captured
    // (it's in each run's working-tree diff) but it is not the run's own source,
    // so this panel found nothing and said, flatly, that nothing changed — the
    // exact opposite of what happened, on the one screen built to answer it.
    const moved = _cmpWorkingTreeFiles(before, after);
    if (moved.length) {
      let h = '<details open><summary style="cursor:pointer;font-size:16px;font-weight:600;margin:12px 0">'
        + 'Code changes <span class="cmp-code-count">'
        + moved.length + ' other file' + (moved.length === 1 ? '' : 's')
        + ' differed</span></summary>'
        + '<p style="color:var(--muted);font-size:12px;margin:4px 0 8px">These runs executed identical '
        + (cd.mode === 'script' ? 'script source' : 'cells')
        + ', but a file around them changed between the attempts. Reconstructed from '
        + 'each run\'s working-tree diff, so it covers the changed regions of the '
        + 'file rather than the whole of it.</p>'
        + _cmpDirectionNote(before, after);
      for (const m of moved) h += _cmpCodeBlockHtml(m.file, m.a, m.b, false);
      return h + '</details>';
    }
    return '<details><summary style="cursor:pointer;font-size:16px;font-weight:600;margin:12px 0">' +
      'Code changes <span class="cmp-code-none">no code change between these runs</span></summary>' +
      '<p style="color:var(--muted);font-size:12px;margin:4px 0 12px">' +
      'These two runs executed identical ' + (cd.mode === 'script' ? 'script source.' : 'cells.') +
      '</p></details>';
  }
  let h = '<details open><summary style="cursor:pointer;font-size:16px;font-weight:600;margin:12px 0">' +
    'Code changes <span class="cmp-code-count">' + cells.length + ' ' +
    (cd.mode === 'script' ? 'file' : (cells.length === 1 ? 'cell' : 'cells')) + ' changed</span></summary>'
    + _cmpDirectionNote(before, after);
  for (const c of cells) h += _cmpCodeBlockHtml(c.label || kind, c.a, c.b, true);
  h += '</details>';
  return h;
}

// ── The two-run panels ───────────────────────────────────────────────────────
// Compare had two tabs answering the same question at different arities, and
// the split cost more than it bought: three of the four things only the pair
// tab could do — the code diff between two attempts, the notebook variable
// table, the A/B image swipe — were simply *absent* from the multi view, so a
// three-run comparison could not reach them at all, and getting to them meant
// knowing to switch tabs and re-pick both runs in a different picker. There is
// one view now, and it grows these panels when the set happens to be a pair.
//
// Fetched alongside the comparison rather than inside the renderer: repainting
// (a polarity flip, the differences toggle) must not re-request, so the payload
// is attached to `data._pair` and every render reads it from there.
async function _fetchPairExtras(id1, id2) {
  const [cmp, vars1, vars2, img1, img2] = await Promise.all([
    api('/api/compare?id1=' + id1 + '&id2=' + id2),
    api('/api/vars-at/' + id1 + '?seq=999999'),
    api('/api/vars-at/' + id2 + '?seq=999999'),
    api('/api/images/' + id1),
    api('/api/images/' + id2),
  ]);
  // api() returns null on failure and reports it itself; the pair panels are an
  // addition to the comparison, so a failure here must not take the whole view
  // down with it.
  if (!cmp || cmp.error || cmp.exp1?.error || cmp.exp2?.error) return null;
  const imgs1 = ((img1 || {}).images || []).slice();
  const imgs2 = ((img2 || {}).images || []).slice();
  mergeArtifactImages(imgs1, (img1 || {}).artifact_images);
  mergeArtifactImages(imgs2, (img2 || {}).artifact_images);
  return {cmp: cmp, vars1: vars1 || {}, vars2: vars2 || {}, imgs1: imgs1, imgs2: imgs2};
}

// Every parameter, not only the varying ones, with the differences toggle. The
// multi view's Configuration panel deliberately leads with what varies; over
// exactly two runs "show me everything, and mark what moved" is the older and
// still-useful reading, so it stays available.
function _pairParamsHtml(pair) {
  const e1 = pair.cmp.exp1, e2 = pair.cmp.exp2;
  const keys = [...new Set([...Object.keys(e1.params || {}),
                            ...Object.keys(e2.params || {})])].filter(isUserParamKey).sort();
  if (!keys.length) return '';
  let h = '<details><summary style="cursor:pointer;font-size:16px;font-weight:600;margin:12px 0">'
    + 'All parameters <span class="cmp-bestkey">both runs, differences marked</span></summary>'
    + '<label class="only-differs-toggle"><input type="checkbox" ' + (onlyDiffers ? 'checked' : '')
    + ' onchange="setOnlyDiffers(this.checked)"> Show only differences</label>'
    + '<table class="params-table"><tr><th>Key</th><th title="' + esc(e1.name) + '">'
    + esc(_cmpColName(e1.name)) + '</th><th title="' + esc(e2.name) + '">'
    + esc(_cmpColName(e2.name)) + '</th></tr>';
  for (const k of keys) {
    const row = paramDiffRow(k, e1.params, e2.params);
    if (onlyDiffers && !row.differs) continue;
    h += row.html;
  }
  return h + '</table></details>';
}

// Final variable state from each notebook run's execution timeline.
function _pairVariablesHtml(pair) {
  const e1 = pair.cmp.exp1, e2 = pair.cmp.exp2;
  const keys = [...new Set([...Object.keys(pair.vars1), ...Object.keys(pair.vars2)])].sort();
  if (!keys.length) return '';
  let h = '<details><summary style="cursor:pointer;font-size:16px;font-weight:600;margin:12px 0">'
    + 'Variables <span class="help-icon" title="Final variable state from the execution '
    + 'timeline of each experiment.">?</span></summary><table class="params-table">'
    + '<tr><th>Variable</th><th title="' + esc(e1.name) + '">' + esc(_cmpColName(e1.name))
    + '</th><th title="' + esc(e2.name) + '">' + esc(_cmpColName(e2.name)) + '</th></tr>';
  for (const k of keys) {
    // Compare the full values, truncate only for display. Comparing the 60-char
    // prefixes made two long reprs that differ past char 60 read as equal — and
    // vanish entirely under "Show only differences".
    const full1 = String(pair.vars1[k] ?? '--');
    const full2 = String(pair.vars2[k] ?? '--');
    const differs = full1 !== full2;
    if (onlyDiffers && !differs) continue;
    h += '<tr><td class="var-name">' + esc(k) + '</td>'
      + '<td' + (differs ? ' class="diff-removed"' : '') + '>' + esc(full1.slice(0, 60)) + '</td>'
      + '<td' + (differs ? ' class="diff-added"' : '') + '>' + esc(full2.slice(0, 60)) + '</td></tr>';
  }
  return h + '</table></details>';
}

// Side-by-side thumbnails plus the A/B bar that drives the swipe/overlay
// comparison (js/image_compare.js). The multi view groups images by label
// across every run, which answers "did this plot change"; this answers "show me
// these two, superimposed", and only exists for a pair.
function _pairImagesHtml(pair) {
  const e1 = pair.cmp.exp1, e2 = pair.cmp.exp2;
  if (!pair.imgs1.length && !pair.imgs2.length) return '';
  return '<details><summary style="cursor:pointer;font-size:16px;font-weight:600;margin:12px 0">'
    + 'Overlay two images <span class="cmp-bestkey">pick one from each run</span></summary>'
    + '<div class="compare-images-section"><div class="compare-images-cols">'
    + _cmpImageCol(_cmpColName(e1.name), pair.imgs1, 1)
    + _cmpImageCol(_cmpColName(e2.name), pair.imgs2, 2)
    + '</div><div class="compare-select-bar" id="cross-cmp-bar">'
    + '<span class="cmp-sel-a">A: (none)</span>'
    + '<span style="color:var(--muted)">vs</span>'
    + '<span class="cmp-sel-b">B: (none)</span>'
    + '<button class="cmp-compare-btn" onclick="doCrossCompare()" disabled>Compare</button>'
    + '<button class="cmp-clear-btn" onclick="clearCrossCompare()">Clear</button>'
    + '</div></div></details>';
}

function _pairExtrasHtml(pair) {
  if (!pair) return '';
  crossCmpA = null; crossCmpB = null;
  return _pairParamsHtml(pair)
    + _renderCompareCodeDiff(pair.cmp.code_diff, pair.cmp.exp1, pair.cmp.exp2)
    + _pairVariablesHtml(pair)
    + _pairImagesHtml(pair);
}

// The differences toggle repaints from the payload rather than re-running the
// comparison — it decides which rows are drawn, not what was measured.
function setOnlyDiffers(on) {
  onlyDiffers = !!on;
  _repaintComparison();
}

// Canvas ids are positional, never a sanitized metric key: `val/acc` and
// `val_acc` both sanitize to `val_acc`, and a duplicate id makes the second
// `new Chart(...)` throw — which killed every later chart on the page while the
// table above still rendered.
// How many images each side of the compare grid renders. The count in the
// heading is the real total; anything beyond this is reported, never dropped
// silently.
const CMP_IMG_LIMIT = 60;

// One side of the compare image grid. Both sides were spelled out in full,
// differing only in which run they read — so the truncation note had to be
// added to each copy, and a change to one column silently applied to half the
// comparison.
function _cmpImageCol(name, imgs, side) {
  let h = '<div class="compare-images-col"><h4>' + esc(name) + ' (' + imgs.length + ')</h4>';
  if (!imgs.length) {
    return h + '<p style="color:var(--muted);font-size:12px">No image paths '
      + 'configured. Set them in the experiment\'s Images tab.</p></div>';
  }
  h += '<div class="cmp-img-grid">';
  for (const img of imgs.slice(0, CMP_IMG_LIMIT)) {
    const src = fileUrl(img.path);
    h += '<div class="cmp-img-thumb" data-side="' + side + '" data-src="' + esc(src)
      + '" onclick="selectCrossImg(\'' + escJsAttr(src) + '\',\''
      + escJsAttr(img.name) + '\',' + side + ')">';
    h += '<img src="' + src + '" loading="lazy" alt="' + esc(img.name) + '">';
    h += '<div class="cmp-thumb-name">' + esc(img.name) + '</div>';
    h += '</div>';
  }
  h += '</div>';
  // The header counts every image; the grid renders at most CMP_IMG_LIMIT.
  // Say which, rather than showing 60 under a heading that reads (200).
  if (imgs.length > CMP_IMG_LIMIT) {
    h += '<p class="cmp-trunc-note">showing ' + CMP_IMG_LIMIT + ' of '
      + imgs.length + '</p>';
  }
  return h + '</div>';
}
function multiChartId(i) { return 'multi-chart-' + i; }

// ── Multi Compare ───────────────────────────────────────────────────────────

const MULTI_COLORS = ['#2c5aa0','#2d7d46','#c0392b','#7c3aed','#d4820f','#1abc9c','#e74c3c','#3498db','#9b59b6','#f39c12'];
let multiCharts = {};

// Request tokens for the two compare surfaces. Two rapid clicks interleave —
// their awaits resolve in whatever order the server answers — so the older
// result could land last, painting a comparison the user is no longer looking
// at and leaking the loser's Chart instances. Same guard `refreshDetail` uses
// with `currentDetailId`.
let _multiCmpToken = 0;

// "What configuration produced these numbers" is the other half of a
// comparison, and it used to live only in the parameter matrix — a view
// Compare doesn't link to. Varying params lead: with six runs the constant ones
// are context you already have, and they push the differences off screen — but
// they are kept, folded, because "what did these runs have in common" is the
// question the differences are read against. The script row appears whenever
// the runs aren't all the same model, which is the first thing you need to know
// in a bake-off.
//
// The panel renders unconditionally. It used to return an empty string when
// nothing varied, so the one screen built to answer "what changed" answered by
// showing nothing at all — indistinguishable from the panel being missing, or
// from the comparison having failed to load it.
function _multiConfigTable(exps, varyingKeys) {
  const scripts = exps.map(e => String(e.script || ''));
  // The server decides what varies, through the same param-equality rule the
  // matrix and the CLI use — `0.01` and `"0.01"` are one setting, which the
  // raw string comparison this used to do called two. Internal `_`-prefixed
  // bookkeeping (dataset manifests, snapshots, tracebacks) is not a setting the
  // user chose, and it differs on nearly every run — it would have been the
  // loudest row here while saying nothing.
  const varying = (varyingKeys || []).filter(isUserParamKey);
  const showScript = new Set(scripts).size > 1;

  let h = '<details open><summary style="cursor:pointer;font-size:16px;font-weight:600;margin:12px 0">'
    + 'Parameters <span class="cmp-bestkey">'
    + (varying.length
        ? varying.length + ' differ across these runs'
        : 'identical across these runs')
    + '</span></summary>';
  if (!varying.length && !showScript) {
    h += '<p class="cmp-trunc-note">Every parameter these runs captured holds the same '
      + 'value, so any difference in the numbers below came from something else — '
      + 'the code, the data, or run-to-run variance.</p>';
  } else {
    h += _multiConfigRowsHtml(exps, varying, scripts, showScript);
  }
  return h + _multiConstantsHtml(exps, varying) + '</details>';
}

// One row per differing key, one column per run. The first run is the reading
// baseline: cells that differ from it are marked, so a twelve-column row can be
// scanned for *where* it changed instead of read value by value.
function _multiConfigRowsHtml(exps, varying, scripts, showScript) {
  let h = '<div style="overflow-x:auto"><table class="params-table"><tr><th>Key</th>';
  for (const e of exps) {
    h += '<th title="' + esc(e.name) + '">' + esc(_cmpColName(e.name)) + '</th>';
  }
  h += '</tr>';
  if (showScript) {
    h += '<tr><td class="var-name">script</td>';
    for (const sc of scripts) {
      const cls = sc === scripts[0] ? '' : ' class="differs"';
      h += '<td' + cls + '>' + esc(sc ? sc.split('/').pop() : '--') + '</td>';
    }
    h += '</tr>';
  }
  for (const k of varying) {
    h += '<tr><td class="var-name">' + esc(k) + '</td>';
    const base = _multiParamCell((exps[0].params || {})[k]);
    for (const e of exps) {
      const cell = _multiParamCell((e.params || {})[k]);
      // A key a run never had is a *variation*, not a blank — the same reading
      // the matrix takes — so it is spelled out rather than left as an empty
      // cell that reads as "not shown".
      const cls = cell === base ? '' : ' class="differs"';
      h += '<td' + cls + '>' + esc(cell) + '</td>';
    }
    h += '</tr>';
  }
  return h + '</table></div>';
}

function _multiParamCell(v) {
  return v === undefined ? 'not set' : String(v);
}

// Held constant: every user param some run captured that the server did not
// call varying. Folded, because it is the background to the differences rather
// than the answer — but present, because "all six ran at batch_size=64" is
// routinely the thing that explains the result.
function _multiConstantsHtml(exps, varying) {
  const varySet = new Set(varying);
  const keys = [...new Set(exps.flatMap(e => Object.keys(e.params || {})))]
    .filter(k => isUserParamKey(k) && !varySet.has(k)).sort();
  if (!keys.length) return '';
  const items = keys.map(k => {
    const hit = exps.find(e => (e.params || {})[k] !== undefined);
    return '<div class="cmp-const-item"><span class="cmp-const-key">' + esc(k) +
      '</span><span class="cmp-const-val">' +
      esc(_multiParamCell((hit || {params: {}}).params[k])) + '</span></div>';
  }).join('');
  return '<details class="cmp-constants"><summary>Held constant across these runs (' +
    keys.length + ')</summary><div class="cmp-const-grid">' + items + '</div></details>';
}

// ── Shareable comparisons ───────────────────────────────────────────────────
//
// A comparison had no address: you could build it, but not send it to anyone
// or come back to it — and combined with the picker only holding recent runs,
// there was no path at all to compare two specific *old* runs by id. The hash
// is written whenever a comparison renders and read once on load.
//
// Deliberately the fragment, not a query param: it never reaches the server,
// so a shared link leaks nothing to logs, and it needs no route.

// Pushed, not replaced. A replaced entry gave the comparison an address but no
// *position*: Back from a full-screen comparison skipped straight out of the
// dashboard, because no in-app navigation had ever left a history entry to go
// back to. `_pushViewHash` (js/sidebar.js) is the one writer, and it no-ops
// when the hash is already what a `popstate` restore just set — so restoring a
// comparison from the Back button cannot push the entry it came from again.
function _writeCompareHash(kind, ids) {
  _pushViewHash('#compare=' + kind + ':' + ids.join(','));
}

function _clearCompareHash() {
  _clearViewHash();
}

// Restore a comparison named in the URL. Returns true when it took over.
async function restoreCompareFromUrl() {
  const m = /^#compare=(pair|multi):(.+)$/.exec(String(window.location.hash || ''));
  if (!m) return false;
  const ids = m[2].split(',').map(s => s.trim()).filter(Boolean);
  if (ids.length < 2) return false;
  // `pair:` links from before the tabs merged still resolve — the ids are what
  // the address names, and two of them now render the pair panels anyway.
  showCompareView();
  switchCompareTab('', new Set(ids));
  await doMultiCompare(ids);
  return true;
}

// The computed comparison — the thing the user actually came for — could not
// leave the page in any format. Kept from the last render so Export doesn't
// re-request it.
let _lastComparison = null;

// Flip which direction is better for one metric, then repaint the comparison.
// Stored per browser (localStorage) because it is a reading preference, not a
// property of the project — two people can disagree about `drift` without
// either of them editing config.
// Repaint the current comparison from the payload it already has. Three
// controls change only how the numbers are *read* — the metric polarity, what
// the chart series are labelled by, and whether unchanged rows are shown — and
// none of them is worth a POST plus one /api/metrics request per run.
function _repaintComparison() {
  if (!_lastComparison || !_lastComparison.data) return;
  Object.values(multiCharts).forEach(c => c.destroy());
  multiCharts = {};
  _renderMultiComparison(_lastComparison.data, _lastComparison.ids,
                         ++_multiCmpToken, _lastComparison.series);
}

function toggleMetricPolarity(key) {
  const next = metricGoodDirection(key) < 0 ? 'higher' : 'lower';
  setMetricPolarity(key, next);
  // Repaint from the payload we already have. Re-running the comparison meant
  // a POST plus one /api/metrics request per run — 21 requests for a 20-run
  // comparison — to change which cell is tinted green.
  _repaintComparison();
}

function exportComparison() {
  if (!_lastComparison) {
    owlSay('Run a comparison first.');
    return;
  }
  const {exps, keys, basis} = _lastComparison;
  const paramKeys = [...new Set(exps.flatMap(e => Object.keys(e.params || {})))].sort();
  const rows = [['run', 'id', 'script', ...paramKeys.map(k => 'param:' + k),
                 ...keys.map(k => 'metric:' + k + ' (' + basis + ')')]];
  for (const e of exps) {
    rows.push([e.name, e.id, e.script || '',
               ...paramKeys.map(k => (e.params || {})[k]),
               ...keys.map(k => (e.metrics || {})[k])]);
  }
  const csv = rows.map(r => r.map(csvCell).join(',')).join('\n');
  // Through the shared saver, so this export honours the "save to
  // <project>/exports/" preference every other export on the page does —
  // hand-rolling the anchor silently opted it out.
  saveOrDownload(csv, 'exptrack_comparison_' + exps.length + '_runs.csv', 'text/csv');
  owlSay('Comparison exported.');
}

async function copyComparisonLink() {
  const hash = String(window.location.hash || '');
  if (!hash.startsWith('#compare=')) {
    owlSay('Run a comparison first.');
    return;
  }
  await navigator.clipboard.writeText(window.location.href);
  owlSay('Link copied — it reopens this comparison.');
}

// A run's name as a comparison column header. Auto-generated names
// (`Aug12_train__lr0.05_epochs20_modelcnn__68b202f3`) differ only in their tail
// and in the middle, so head-truncating them to 17 characters rendered a table
// whose every column read `Aug12_train__lr0…` — a comparison you cannot tell
// apart by the thing being compared. `midEllipsis` keeps both ends, and the
// full name is on the title.
function _cmpColName(name) { return midEllipsis(name, 24); }

// ── The colour key ───────────────────────────────────────────────────────────
// Chart.js draws its own legend from each series' label, which means the legend
// can only say as much as the label does — and a label built from one parameter
// is deliberately ambiguous: pick "label by lr" over a sweep and two runs
// sharing `lr=0.0001` get one entry each, identical, with nothing tying either
// to the run it came from. Labelling by everything is not the fix (that is the
// unreadable legend the labels replaced).
//
// So the charts get a key of their own, above them: one row per run, in series
// order, carrying the swatch, the run's full name, its id and the settings that
// distinguish it. It is rendered once per surface and serves every chart below
// it, because both chart kinds colour run *j* with colour *j*.
//
// `entries`: [{color, name, id, params: [[k, v], …]}] — assembled by the caller,
// since the pair view has two fixed colours and the multi view has a palette.
function _cmpSeriesKeyHtml(entries) {
  if (!entries.length) return '';
  return '<div class="cmp-key">' + entries.map(e =>
    '<a class="cmp-key-item" href="#" title="' + esc(e.name) +
      '" onclick="showDetail(\'' + escJsAttr(e.id) + '\');return false">' +
      '<span class="cmp-key-swatch" style="background:' + esc(e.color) + '"></span>' +
      '<span class="cmp-key-name">' + esc(midEllipsis(e.name, 34)) + '</span>' +
      '<span class="cmp-key-id">' + esc(String(e.id).slice(0, 6)) + '</span>' +
      (e.params.length
        ? '<span class="cmp-key-params">' + e.params.map(([k, v]) =>
            '<span class="cmp-key-chip">' + esc(paramColLabel(k)) + '=' +
            esc(midEllipsis(String(v), 16)) + '</span>').join('') + '</span>'
        : '') +
    '</a>').join('') + '</div>';
}

// The multi view's key. The settings shown are the ones the labels are built
// from when they are enough to tell the runs apart, and every varying key when
// they are not — the key is the surface that must never be ambiguous, so it
// does not inherit the label's three-key cap.
function _multiSeriesKeyHtml(exps, ranked) {
  const keys = (ranked && ranked.all) || [];
  return _cmpSeriesKeyHtml(exps.map((e, j) => ({
    color: MULTI_COLORS[j % MULTI_COLORS.length],
    name: e.name,
    id: e.id,
    params: keys.filter(k => (e.params || {})[k] !== undefined)
                .map(k => [k, (e.params || {})[k]]),
  })));
}

// ── What a chart series is called ────────────────────────────────────────────
// Every chart in Multi Compare labelled its series with the run's *name*. For a
// sweep those names are auto-generated and near-identical, so a five-run legend
// read as five copies of one string and the charts could not answer the only
// question they were opened for: which line is which setting. The label is now
// built from what actually differs.
//
// `_multiLabelBy` is '' for "the varying parameters" (the default, and a
// compound label like `lr=0.01 epochs=20`), a param key to label by one
// setting, or 'name' to get the run name back.
let _multiLabelBy = _storageGet('exptrack-multi-label-by') || '';

function setMultiLabelBy(key) {
  _multiLabelBy = key || '';
  _storageSet('exptrack-multi-label-by', _multiLabelBy);
  // A relabel is a render, not a request: re-running the comparison would cost
  // a POST plus one /api/metrics call per run to rewrite a legend.
  _repaintComparison();
}

// The keys the labels can be built from: what the *server* says varies, minus
// internal bookkeeping. A key that is constant across the set cannot separate
// two series, so offering it would just relabel every line identically.
function _multiLabelKeys(data) {
  return ((data && data.varying_params) || []).filter(isUserParamKey);
}

// How many settings the compound label names before it stops being readable.
// A five-parameter sweep run through a mid-ellipsis produced
// `batch_size=64 dr….05 model=cnn` — a label that hid `lr`, the one thing being
// swept, because it happened to sit in the middle alphabetically.
const MULTI_LABEL_MAX_KEYS = 3;

// The label keys that actually separate these runs, best first — chosen
// greedily, not by counting each key's values in isolation. Ranking by distinct
// count alone picked `batch_size, dropout, epochs` (two values each) over `lr`
// on a five-parameter sweep, so three of the five legend entries came out
// identical: the label named settings that happened to differ *somewhere* in the
// set instead of the ones that tell these particular runs apart. Each step picks
// the key that maximizes the number of distinct labels, and stops as soon as
// every run has its own — which is the property a legend actually needs.
//
// Ties keep the server's order, so the choice is stable across repaints, and
// the unchosen keys are returned after the chosen ones rather than dropped, so
// a caller wanting all of them still has them.
function _multiRankedLabelKeys(exps, keys) {
  const val = (e, k) => String((e.params || {})[k]);
  const distinctWith = ks =>
    new Set(exps.map(e => ks.map(k => val(e, k)).join('\u0000'))).size;
  const chosen = [];
  const rest = (keys || []).slice();
  while (rest.length && chosen.length < MULTI_LABEL_MAX_KEYS) {
    let bestAt = 0, bestN = -1;
    rest.forEach((k, i) => {
      const n = distinctWith(chosen.concat([k]));
      if (n > bestN) { bestN = n; bestAt = i; }
    });
    chosen.push(rest.splice(bestAt, 1)[0]);
    if (bestN >= exps.length) break;    // every run already has its own label
  }
  // `use` is what the label is built from; `all` is every varying key, so the
  // label can say when it is naming fewer settings than the runs actually
  // differ by. Slicing a single concatenated list would have quietly padded a
  // sufficient two-key label with a third key that separates nothing.
  return {use: chosen, all: (keys || []).slice()};
}

function _multiSeriesLabel(e, keys) {
  if (_multiLabelBy === 'name') return midEllipsis(e.name, 22);
  const params = e.params || {};
  const ranked = keys || {use: [], all: []};
  const use = _multiLabelBy ? [_multiLabelBy] : ranked.use;
  const parts = use
    .filter(k => params[k] !== undefined)
    // Values, not the whole label, are what can run long — a 40-character path
    // as a param value must not push the key names off the legend.
    .map(k => paramColLabel(k) + '=' + midEllipsis(String(params[k]), 14));
  // A run missing every label key still needs to be tellable from the others,
  // so it falls back to its name rather than to an empty legend entry.
  if (!parts.length) return midEllipsis(e.name, 22);
  const dropped = !_multiLabelBy && ranked.all.length > use.length;
  return parts.join(' ') + (dropped ? ' …' : '');
}

function _multiLabelControl(data, ranked) {
  const keys = _multiLabelKeys(data);
  if (!keys.length) return '';
  const used = (ranked && ranked.use.length) ? ranked.use : keys.slice(0, MULTI_LABEL_MAX_KEYS);
  const opt = (v, label) => '<option value="' + esc(v) + '"' +
    (v === _multiLabelBy ? ' selected' : '') + '>' + esc(label) + '</option>';
  return '<span class="cmp-label-by"><label for="cmp-label-by">Label series by</label>' +
    '<select id="cmp-label-by" class="select-sm" onchange="setMultiLabelBy(this.value)">' +
    opt('', 'what varied (' + used.map(paramColLabel).join(', ') + ')') +
    keys.map(k => opt(k, paramColLabel(k))).join('') +
    opt('name', 'run name') +
    '</select></span>';
}

// One chart per metric, one line per run. Series are fetched per run (the same
// endpoint the detail view polls) and aligned on x, never on array index — two
// runs logging at different cadences must not have their points paired by
// position.
async function _renderMultiCurves(exps, keys, token, cachedSeries, labelKeys) {
  const grid = document.getElementById('multi-curve-grid');
  if (!grid) return;
  const labelOf = e => _multiSeriesLabel(e, labelKeys);
  // *cachedSeries* is the series list from a previous render of the same run
  // set. A repaint that changes only how the numbers are *read* — flipping a
  // metric's polarity — must not re-fetch them: one request per run, for data
  // that cannot have changed.
  const series = cachedSeries || await Promise.all(
    exps.map(e => api('/api/metrics/' + e.id).then(d => d || {}).catch(() => ({}))));
  if (token !== _multiCmpToken) return;
  if (_lastComparison) _lastComparison.series = series;

  const charted = keys.filter(k => series.some(s => (s[k] || []).length > 1));
  if (!charted.length) {
    grid.innerHTML = '<p class="cmp-trunc-note">No run logged more than one '
      + 'point for these metrics, so there is nothing to plot over time.</p>';
    return;
  }
  grid.innerHTML = charted
    .map((k, i) => '<div class="chart-container"><canvas id="multi-curve-' + i + '"></canvas></div>')
    .join('');

  charted.forEach((k, i) => {
    const canvas = document.getElementById('multi-curve-' + i);
    if (!canvas) return;
    const datasets = [];
    exps.forEach((e, j) => {
      const pts = series[j][k] || [];
      if (pts.length < 2) return;
      datasets.push({
        label: labelOf(e),
        data: pts.map(p => ({x: p.step ?? p.i ?? 0, y: p.value})),
        borderColor: MULTI_COLORS[j % MULTI_COLORS.length],
        backgroundColor: MULTI_COLORS[j % MULTI_COLORS.length],
        borderWidth: 2, pointRadius: 0, tension: 0.15,
      });
    });
    if (!datasets.length) return;
    multiCharts['curve:' + k] = new Chart(canvas, {
      type: 'line',
      data: {datasets: datasets},
      options: {
        responsive: true,
        interaction: {mode: 'nearest', intersect: false},
        plugins: {legend: {display: true, labels: {font: {family: "'IBM Plex Mono'"}}}},
        scales: {
          x: {type: 'linear',
              title: {display: true, text: 'Step', font: {family: "'IBM Plex Mono'"}}},
          y: {title: {display: true, text: k, font: {family: "'IBM Plex Mono'"}}},
        },
      },
    });
  });
}

async function doMultiCompare(ids) {
  const token = ++_multiCmpToken;
  Object.values(multiCharts).forEach(c => c.destroy());
  multiCharts = {};
  if (!ids || ids.length < 2) {
    ids = [...selectedIds];
  }
  if (ids.length < 2) return;

  // POST, not a query string: the id set *is* the request, and ~5000 selected
  // runs exceeded http.server's 64 KiB request line and came back as a bare 414.
  const basisSel = document.getElementById('cmp-multi-basis');
  const basis = basisSel ? basisSel.value : 'final';
  // The reader's polarity overrides travel with the request. Without them the
  // server picked each metric's "best" point by its own heuristic while the
  // cell beside it was tinted by the override — so flipping `drift` to
  // lower-is-better tinted one run as the winner and showed another run's
  // number as its best value.
  const data = await postApi('/api/multi-compare',
                             {ids: ids, rank_by: basis,
                              metric_goals: metricPolarityGoals()});
  if (!data || data.error || !data.experiments || !data.experiments.length) {
    document.getElementById('multi-compare-result').innerHTML =
      '<p>Could not load experiments' +
      (data && data.error ? ' \u2014 ' + esc(String(data.error)) : '') + '.</p>';
    return;
  }
  if (token !== _multiCmpToken) return;   // a newer request superseded this one
  // Exactly two runs gets the pair-only panels: the code diff between the two
  // attempts, the notebook variable table and the A/B image overlay. Fetched
  // here rather than in the renderer so a repaint never re-requests.
  if (data.experiments.length === 2) {
    data._pair = await _fetchPairExtras(data.experiments[0].id, data.experiments[1].id);
    if (token !== _multiCmpToken) return;
  }
  _renderMultiComparison(data, ids, token);
}

// The metric table: one row per metric, one column per run, best tinted green
// and worst red. Extracted so the parameter matrix can render the same table
// inline under its own rows without a second implementation — this table used
// to tint max=green/min=red regardless of the metric, highlighting the *worst*
// run on loss or latency, and a copy of it elsewhere would be a second place
// for that to come back.
//
// `metricGoodDirection` is the shared answer (sync-tested against the server
// list) and honours the user's polarity overrides; the metric name doubles as
// the control that flips one.
function _multiMetricTableHtml(exps, keys) {
  // A delta is only defined between two runs — over three it is "against
  // which?" — so the column exists exactly when the set is a pair. It is the
  // one thing the old pair tab's metric table had that this one did not.
  const pair = exps.length === 2;
  let html = '<div style="overflow-x:auto"><table class="metrics-table"><tr><th>Key</th>';
  for (const e of exps) {
    html += '<th title="' + esc(e.name) + '">' + esc(_cmpColName(e.name)) + '</th>';
  }
  if (pair) html += '<th>Delta</th>';
  html += '</tr>';
  for (const k of keys) html += _multiMetricRowHtml(exps, k, pair);
  return html + '</table></div>';
}

function _multiMetricRowHtml(exps, k, pair) {
  // The metric name is a polarity control. `setMetricPolarity` has existed
  // since the Pareto goal selectors, but only that one view exposed it — so on
  // any metric the name heuristic reads wrong (`score_gap`, `drift`), the
  // best/worst tint here was simply wrong with no way to correct it.
  const lowerIsBetter = metricGoodDirection(k) < 0;
  let html = '<tr><td><button class="cmp-polarity" title="'
    + esc(lowerIsBetter ? 'lower is better — click to flip'
                        : 'higher is better — click to flip')
    + '" onclick="toggleMetricPolarity(\'' + escJsAttr(k) + '\')">'
    + esc(k) + ' <span class="cmp-polarity-arrow">'
    + (lowerIsBetter ? '\u2193' : '\u2191') + '</span></button></td>';
  const nums = exps.map(e => (e.metrics || {})[k]).filter(v => typeof v === 'number');
  const mn = nums.length ? Math.min(...nums) : null;
  const mx = nums.length ? Math.max(...nums) : null;
  const best = lowerIsBetter ? mn : mx;
  const worst = lowerIsBetter ? mx : mn;
  // The tint compares full-precision floats while the cells render 4 decimals,
  // so two values printing identically could be tinted green and red. Same
  // epsilon the pair view uses, and the same precision escalation when a real
  // difference is finer than the display.
  const spread = nums.length > 1 && metricMoved(mn, mx);
  for (const e of exps) {
    const v = (e.metrics || {})[k];
    let cls = '';
    if (typeof v === 'number' && spread) {
      if (v === best) cls = ' class="cmp-best-max"';
      else if (v === worst) cls = ' class="cmp-best-min"';
    }
    let cell = '--';
    if (v !== undefined) {
      cell = typeof v === 'number'
        ? esc(spread ? fmtMetricPair(v, best === v ? worst : best)[0] : v.toFixed(4))
        : esc(String(v));
    }
    html += '<td' + cls + '>' + cell + '</td>';
  }
  if (pair) {
    // `metricDelta` is the shared polarity-aware renderer the pair tab used, so
    // green still means better rather than bigger.
    const a = (exps[0].metrics || {})[k], b = (exps[1].metrics || {})[k];
    html += '<td>' + metricDelta(a, b, k).html + '</td>';
  }
  return html + '</tr>';
}

// Draw a comparison from a payload. Separate from the fetch so a change that
// only affects *rendering* \u2014 flipping a metric's polarity \u2014 can repaint from
// the cached payload instead of re-POSTing the comparison and re-fetching one
// metric series per run.
function _renderMultiComparison(data, ids, token, cachedSeries) {
  const exps = data.experiments;
  // Picking four runs and rendering three, with nothing saying so, is the
  // dishonesty the matrix and branch-compare surfaces already refuse.
  let missingNote = '';
  const unknown = data.unknown_ids || [];
  const dropped = ids.length - exps.length;
  if (unknown.length || dropped > 0) {
    const names = unknown.length ? unknown.map(i => String(i).slice(0, 8)).join(', ') : '';
    missingNote = '<p class="cmp-missing">Comparing ' + exps.length + ' of '
      + ids.length + ' selected runs'
      + (names ? ' \u2014 not found: ' + esc(names) : '') + '.</p>';
  }
  // Collect all unique metric keys
  const allKeys = new Set();
  for (const e of exps) {
    for (const k of Object.keys(e.metrics || {})) allKeys.add(k);
  }
  const keys = [...allKeys].sort();

  // Summary table — per metric row, the *best* value is tinted green and the
  // worst red. This used to tint max=green/min=red regardless of the metric,
  // so on `loss` or `latency` the worst run in the set was highlighted as the
  // winner — against the project's own "green means better, not bigger" rule,
  // and against the pair view's Delta column right next to it.
  // `metricGoodDirection` is the shared answer (sync-tested against the server
  // list) and honours the user's polarity overrides.
  // The basis is stated, never implied: "0.91" means different things when it
  // is the final value and when it is the best point ever reached.
  const labelKeys = _multiRankedLabelKeys(exps, _multiLabelKeys(data));
  const basisLabel = (data.rank_by === 'best') ? 'best value' : 'final value';
  let html = '<details open><summary style="cursor:pointer;font-size:16px;font-weight:600;margin:12px 0">Comparison Table <span class="cmp-bestkey">'
    + esc(basisLabel) + ' \u00b7 <span class="cmp-best-max">best</span> / <span class="cmp-best-min">worst</span> per row</span></summary>';
  html += _multiMetricTableHtml(exps, keys) + '</details>';
  html = missingNote + _multiSeriesKeyHtml(exps, labelKeys)
       + _multiConfigTable(exps, data.varying_params) + html
       + _pairExtrasHtml(data._pair);

  // Training-curve overlay across every selected run — the question a sweep is
  // actually asking ("how do these five learn?"), which had no answer anywhere:
  // the pair view overlays exactly two, and this view only bar-charted the last
  // value. Rendered under the bars because the bars answer "which won" and the
  // curves answer "how".
  if (keys.length) {
    html += '<details open><summary style="cursor:pointer;font-size:16px;font-weight:600;margin:12px 0">Training Curves</summary>'
      + _multiLabelControl(data, labelKeys)
      + '<div class="compare-charts-grid" id="multi-curve-grid"></div></details>';
  }

  // Bar charts
  if (keys.length) {
    html += '<details open><summary style="cursor:pointer;font-size:16px;font-weight:600;margin:12px 0">Bar Charts</summary><div class="compare-charts-grid">';
    // Id by *index*, never by a sanitized key: `val/acc` and `val_acc` both
    // sanitize to `val_acc`, and in the multi view the keys are the union
    // across runs — exactly the different-models case. The second
    // `new Chart(...)` on a canvas already owning one throws, and the
    // unhandled rejection killed every remaining chart while the table above
    // still looked healthy.
    keys.forEach((k, i) => {
      html += '<div class="chart-container"><canvas id="' + multiChartId(i) + '"></canvas></div>';
    });
    html += '</div></details>';
  }

  // Image comparison — group by label across experiments
  const allImageLabels = new Set();
  for (const e of exps) {
    for (const img of (e.images || [])) {
      allImageLabels.add(img.label || img.path.split('/').pop());
    }
  }
  if (allImageLabels.size > 0) {
    html += '<details open><summary style="cursor:pointer;font-size:16px;font-weight:600;margin:12px 0">Images</summary>';
    for (const label of [...allImageLabels].sort()) {
      html += '<div class="multi-compare-image-group"><h4 style="font-size:13px;color:var(--muted);margin:8px 0 4px">' + esc(label) + '</h4>';
      html += '<div class="multi-compare-image-row">';
      for (const e of exps) {
        const img = (e.images || []).find(i => (i.label || i.path.split('/').pop()) === label);
        const name = _cmpColName(e.name);
        html += '<div class="multi-compare-image-cell">';
        html += '<div style="font-size:11px;color:var(--muted);margin-bottom:4px">' + esc(name) + '</div>';
        if (img) {
          html += '<img src="' + fileUrl(img.path) + '" alt="' + esc(label) + '" onclick="openImageModal(this.src,\'' + escJsAttr(label) + '\')">';
        } else {
          html += '<div style="color:var(--muted);font-size:12px;padding:20px;text-align:center">No image</div>';
        }
        html += '</div>';
      }
      html += '</div></div>';
    }
    html += '</details>';
  }

  if (token !== _multiCmpToken) return;
  _lastComparison = {exps: exps, keys: keys, basis: data.rank_by || 'final',
                     data: data, ids: ids};
  _writeCompareHash('multi', exps.map(e => e.id));
  document.getElementById('multi-compare-result').innerHTML = html;

  // Create bar charts
  _renderMultiCurves(exps, keys, token, cachedSeries, labelKeys);

  keys.forEach((k, i) => {
    const canvas = document.getElementById(multiChartId(i));
    if (!canvas) return;
    const labels = exps.map(e => _multiSeriesLabel(e, labelKeys));
    const values = exps.map(e => e.metrics[k] ?? null);
    const colors = exps.map((_, j) => MULTI_COLORS[j % MULTI_COLORS.length]);
    multiCharts[k] = new Chart(canvas, {
      type: 'bar',
      data: {
        labels: labels,
        datasets: [{
          label: k,
          data: values,
          backgroundColor: colors.map(c => c + '33'),
          borderColor: colors,
          borderWidth: 1.5,
        }]
      },
      options: {
        responsive: true,
        plugins: { legend: { display: false } },
        scales: {
          x: { ticks: { font: { family: "'IBM Plex Mono'", size: 11 } } },
          y: { title: { display: true, text: k, font: { family: "'IBM Plex Mono'" } } }
        }
      }
    });
  });
}
