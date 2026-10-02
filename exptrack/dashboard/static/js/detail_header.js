// ── Run navigator ────────────────────────────────────────────────────────────
// Prev / position / next in the current list, so you can flip between runs
// without going back to the table. It replaced a strip of run cards that became
// an unreadable sideways scroller past a few dozen runs; the run list and
// Compare show every run's metric better. Each neighbour is labelled by what
// differs between runs in the list, so ‹ › says where it goes. Reuses
// getFilteredExperiments() — the same order as the table and sidebar.

// The params that differ across the strip's runs, in key order — what a card
// is labelled by. A sweep's runs share a script and most settings, so their
// names (`Oct01_train__lr0.003_batch_si128_…`) cut to the same prefix on every
// 150px card; the values that differ are the only part worth the space.
function _fsVaryingKeys(exps) {
  return paramColCandidates(exps).filter(c => c.varies).map(c => c.key).sort();
}

// A param key as a card shows it — the same rule as a generated run name
// (core/naming._short_key): a long multi-word key becomes its initials, so
// `batch_size` is `bs` and `weight_decay` is `wd`.
function _fsShortKey(key) {
  const k = paramColLabel(String(key).split('.').pop());
  if (k.length <= 8) return k;
  const words = k.split(/[_-]+/).filter(Boolean);
  return words.length > 1 ? words.map(w => w[0]).join('') : k.slice(0, 8);
}

// A card's label: a name the user chose, as written; otherwise the values of
// the varying params (`lr 0.001 · bs 128 · seed 2`), falling back to the auto
// name without its date.
function _fsLabel(e, varying) {
  if (!e.name_is_auto) return e.name;
  const p = e.params || {};
  const bits = varying.filter(k => k in p)
    .map(k => _fsShortKey(k) + ' ' + (typeof p[k] === 'string' ? p[k] : JSON.stringify(p[k])));
  return bits.length ? bits.join(' · ') : shortRunLabel(e.name, true);
}

function renderRunNavigator(currentId) {
  const nav = document.getElementById('detail-nav');
  if (!nav) return;
  const exps = getFilteredExperiments();
  const idx = exps.findIndex(e => e.id === currentId);
  // A single run (or one filtered out of the list) has nothing to flip through.
  if (exps.length < 2 || idx < 0) { nav.innerHTML = ''; nav.style.display = 'none'; return; }
  nav.style.display = '';
  const varying = _fsVaryingKeys(exps);
  const side = (e, dir) => {
    const cls = 'run-nav-side ' + (dir < 0 ? 'run-nav-prev' : 'run-nav-next');
    if (!e) return '<span class="' + cls + ' disabled"></span>';
    const step = dir < 0 ? 'filmstripStep(-1)' : 'filmstripStep(1)';
    const label = esc(_fsLabel(e, varying));
    return '<button class="' + cls + '" onclick="' + step + '" title="' + esc(e.name)
      + (dir < 0 ? ' (←)' : ' (→)') + '">'
      + (dir < 0 ? '‹ ' : '') + '<span class="status-dot status-' + esc(e.status) + '"></span>'
      + label + (dir > 0 ? ' ›' : '') + '</button>';
  };
  nav.innerHTML = side(exps[idx - 1], -1)
    + '<button class="run-nav-pos" onclick="openRunNavigatorPicker()"'
    + ' title="Position in the list as it is filtered and sorted — click to jump to a run">'
    + (idx + 1) + ' of ' + exps.length + ' ▾</button>'
    + side(exps[idx + 1], 1);
}

function openRunNavigatorPicker() {
  openRunPicker({
    mode: 'single', title: 'Jump to run', confirmLabel: 'Open', minPicks: 1,
    preselect: currentDetailId ? [currentDetailId] : [],
    onConfirm: ids => { if (ids && ids[0]) refreshDetail(ids[0], {keepSidebar: true}); },
  });
}

// Step to the adjacent run in the current list. dir = -1 (previous/left) or
// +1 (next/right). No-op at either end.
function filmstripStep(dir) {
  const exps = getFilteredExperiments();
  const idx = exps.findIndex(e => e.id === currentDetailId);
  if (idx < 0) return;
  const next = idx + dir;
  if (next < 0 || next >= exps.length) return;
  refreshDetail(exps[next].id, {keepSidebar: true});
}

// The code chip. `source_changed` is this run's own code (the same snapshots and
// cells the Code-changes panel diffs); `code_changed` is the wider repository
// state, which moves when *any* tracked file differs. Reporting the wide one as
// "code changed" put an amber chip on a byte-identical rerun and contradicted
// the panel directly below it, so the two facts get two different chips.
function _vsCodeChip(d) {
  if (d.source_changed) {
    return '<span class="vs-chip vs-chip-code" title="This run\'s code differs from'
      + ' the previous run\'s — see Code changes below">code changed</span>';
  }
  if (!d.code_changed) return '';
  if (d.source_changed === false) {
    return '<span class="vs-chip vs-chip-repo" title="This run\'s own code is'
      + ' identical. Something else in the repository differed — another file, or a'
      + ' different commit.">repo changed elsewhere</span>';
  }
  // source_changed === null: neither run captured code to compare, so the
  // repository signal is all we have. Say only what it supports.
  return '<span class="vs-chip vs-chip-repo" title="The repository state differed.'
    + ' Neither run captured code, so exptrack cannot say whether this run\'s own'
    + ' code changed.">repo changed</span>';
}

// "Previous" means the next-older run of the same script — spelled out here
// because the newest-first list puts that run below the current one.
const _VS_PREV_LABEL = '<span class="vs-prev-label" title="Compared against the'
  + ' last run of this script started before this one">vs previous run</span>';

// The chips for a delta payload — shared by the "vs previous" and "vs
// reference" strips, which differ only in which baseline they name. Two copies
// would be two places for the polarity colouring and the precision widening to
// drift, on the one surface whose whole job is stating a comparison accurately.
// Returns '' when nothing moved, so the caller can render its own empty note.
//
// Two labelled rows, settings then results, with the metric this run is judged
// by first. One run of chips mixing `lr 0.003→0.001` (a setting) with `lr
// 0.0021→1.54e-6 ▼` (a logged metric) and `train/loss …` had to be read chip
// by chip to tell which side of "what I changed / what happened" each was on.
function _vsChipsHtml(d) {
  const pcs = d.param_changes || [];
  const mcs = _vsPrimaryFirst(d.metric_changes || []);
  if (pcs.length === 0 && mcs.length === 0 && !d.code_changed) return '';
  let settings = '';
  for (const c of pcs.slice(0, 6)) {
    settings += '<span class="vs-chip vs-chip-param">' + esc(c.key) + ' '
      + esc(_vsFmt(c.from)) + '→' + esc(_vsFmt(c.to)) + '</span>';
  }
  if (pcs.length > 6) settings += '<span class="vs-chip">+' + (pcs.length - 6) + ' params</span>';
  settings += _vsCodeChip(d);
  let results = '';
  for (const c of mcs.slice(0, 6)) {
    // Colour by better/worse (polarity-aware), not by the sign of the change —
    // a rising loss is a regression and must not read green.
    let cls = 'vs-chip vs-chip-metric', arrow = '', title = '';
    if (c.delta != null && c.delta !== 0) {
      const vis = _deltaVisual(c.key, c.delta);
      cls += vis.better ? ' vs-chip-better' : ' vs-chip-worse';
      arrow = c.delta > 0 ? ' ▲' : ' ▼';
      title = ' title="' + esc(vis.title) + '"';
    }
    if (c.$primary) cls += ' vs-chip-primary';
    // Chips round to 4dp, which prints a genuine 1e-7 move as "0.5→0.5" next to
    // an arrow claiming it moved — widen just that chip until the two differ.
    const [sf, st] = _vsFmtPair(c.from, c.to);
    results += '<span class="' + cls + '"' + title + '>' + esc(c.key) + ' '
      + esc(sf) + '→' + esc(st) + arrow + '</span>';
  }
  if (mcs.length > 6) results += '<span class="vs-chip">+' + (mcs.length - 6) + ' metrics</span>';
  return _vsRow('Settings', settings || '<span class="vs-prev-none">same settings</span>')
    + _vsRow('Results', results || '<span class="vs-prev-none">no shared metric moved</span>');
}

function _vsRow(label, body) {
  return '<div class="vs-row"><span class="vs-row-label">' + label + '</span>' + body + '</div>';
}

// The metric this run is judged by goes first, marked — it is the one the
// comparison is about. Read from the list row, which already carries the
// resolved primary metric; the payload is not mutated.
function _vsPrimaryFirst(mcs) {
  const row = (Array.isArray(allExperiments) ? allExperiments : [])
    .find(e => e.id === currentDetailId);
  const pk = ((row && row.primary_metric) || {}).key;
  if (!pk) return mcs;
  const first = mcs.filter(c => c.key === pk).map(c => Object.assign({$primary: true}, c));
  return first.concat(mcs.filter(c => c.key !== pk));
}

// The strip's first line: which comparison this is, against which run.
function _vsHead(label, link) {
  return '<div class="vs-head">' + label + link + '</div>';
}

async function loadVsPrevious(id) {
  let d;
  try {
    d = await api('/api/run-delta/' + id);
  } catch (e) { return; }
  // Bail if the user navigated away while we were fetching.
  if (currentDetailId !== id) return;
  const strip = document.getElementById('vs-prev-strip');
  if (!strip) return;
  if (!d || d.error || !d.previous) { strip.style.display = 'none'; return; }
  _markChangedParams((d.param_changes || []).map(c => c.key));
  const chips = _vsChipsHtml(d)
    || '<div class="vs-row"><span class="vs-prev-none">no params, code, or metrics changed</span></div>';
  strip.innerHTML = _vsHead(_VS_PREV_LABEL, _vsPrevLink(d.previous, d.current_created_at)) + chips;
  strip.style.display = '';
}

// ── vs the reference run ─────────────────────────────────────────────────────
// A second, deliberately separate comparison. "vs previous" is lineage — what
// changed since last time; this is a fixed target — is it better than the thing
// I am trying to beat. They are shown as two strips rather than one switchable
// one precisely because they answer different questions and routinely disagree.
//
// Every state names its own baseline and where that choice was made. A number
// whose origin the reader has to guess is the failure this whole feature exists
// to avoid, so there is no state here that renders a bare delta.

// The number this run is judged by, in the header line — with where that choice
// came from, since a heuristic pick is exptrack's guess and should read as one.
// A configured-but-unlogged metric says so rather than borrowing another key.
function _primaryMetricSummary(exp) {
  const p = exp.primary_metric || {};
  if (!p.key) return '';
  _pmDetailCtx = {id: exp.id, keys: (exp.metrics || []).map(m => m.key),
                  primary: p, studies: exp.studies || []};
  // The label is the way in: clicking it changes what runs are judged by.
  const open = ' role="button" tabindex="0" onclick="openPrimaryMetricPickerForRun(this)"'
    + ' onkeydown="if(event.key===\'Enter\')openPrimaryMetricPickerForRun(this)"';
  if (p.missing) {
    return '<span class="sum-item sum-primary pm-open"' + open
      + ' title="' + esc(p.key) + ' is this project\'s metric, but this run never'
      + ' logged it. Click to change it.">' + esc(p.key) + ': <strong class="primary-missing">not logged</strong>'
      + '<span class="pm-caret">▾</span></span>';
  }
  const guess = p.source === 'heuristic';
  const note = guess
    ? 'Guessed from this run\'s own metrics. Click to choose the metric runs are judged by.'
    : 'The metric set for this ' + p.source + '. Click to change it.';
  return '<span class="sum-item sum-primary pm-open"' + open + ' title="'
    + esc(note) + '">' + esc(p.key) + ': <strong>' + esc(fmtMetricVal(p.final)) + '</strong>'
    + (guess ? '<span class="primary-guess-tag">guessed</span>' : '')
    + '<span class="pm-caret">▾</span></span>';
}

// ── Choosing the primary metric ─────────────────────────────────────────────
// The primary metric decides the Result column, the table's sort, the Matrix's
// best row and effect charts, and the filmstrip — and it could only be set
// with `exptrack primary-metric`. With nothing set, the guess (often
// `train_loss`, the alphabetically-first loss) ranked everything, and the
// dashboard's only advice was a terminal command. One picker serves the run
// header and the Matrix; it writes the level the reader names, exactly as the
// CLI does (a guessed level would leave a setting shadowed by a more specific
// one and appearing to do nothing).

let _pmDetailCtx = null;
let _pmPicker = null;       // {el, dispose} while the picker is open

function openPrimaryMetricPickerForRun(anchor) {
  const c = _pmDetailCtx;
  if (!c) return;
  openPrimaryMetricPicker(anchor, {keys: c.keys, current: c.primary,
                                   runId: c.id, studies: c.studies});
}

function closePrimaryMetricPicker() {
  if (!_pmPicker) return;
  _pmPicker.dispose();
  _pmPicker.el.remove();
  _pmPicker = null;
}

// opts: {keys, current: {key, goal, source}, runId?, studies?}
function openPrimaryMetricPicker(anchor, opts) {
  closePrimaryMetricPicker();
  const keys = [...new Set(opts.keys || [])].sort();
  const cur = opts.current || {};
  if (!keys.length) { owlSay('No metrics logged yet to judge runs by.'); return; }
  // A guess is what the reader opened this to replace, so it offers the likely
  // evaluation metric first rather than the guess back.
  const suggest = keys.find(k => /val|test|acc|f1|auc/i.test(k) && metricGoodDirection(k) > 0);
  const start = cur.source !== 'heuristic' && keys.includes(cur.key) ? cur.key
    : (suggest || (keys.includes(cur.key) ? cur.key : keys[0]));
  const levelOf = {run: 'run', study: 'study', project: 'project'}[cur.source] || 'project';
  const studies = opts.studies || [];
  // Clear removes the level that answered, so it needs that level's target:
  // a run setting read from the Matrix has no run named to clear.
  const canClear = cur.source && cur.source !== 'heuristic'
    && (cur.source !== 'run' || opts.runId) && (cur.source !== 'study' || cur.study);

  const pop = document.createElement('div');
  pop.className = 'pm-picker';
  pop.setAttribute('role', 'dialog');
  pop.setAttribute('aria-label', 'Metric runs are judged by');
  const radio = (value, label, checked, extra) => '<label class="pm-level"><input type="radio" name="pm-level" value="'
    + esc(value) + '"' + (checked ? ' checked' : '') + '> ' + label + (extra || '') + '</label>';
  let levels = radio('project', 'Every run in this project', levelOf === 'project');
  if (studies.length) {
    levels += radio('study', 'Runs in study', levelOf === 'study',
      ' <select class="select-sm pm-study">' + studies.map(s => '<option>' + esc(s) + '</option>').join('') + '</select>');
  }
  if (opts.runId) levels += radio('run', 'Only this run', levelOf === 'run');
  pop.innerHTML =
    '<div class="pm-title">Judge runs by</div>'
    + '<div class="pm-row"><select class="select-sm pm-key">'
    + keys.map(k => '<option' + (k === start ? ' selected' : '') + '>' + esc(k) + '</option>').join('')
    + '</select><select class="select-sm pm-goal">'
    + '<option value="max">higher is better</option><option value="min">lower is better</option></select></div>'
    + '<div class="pm-levels">' + levels + '</div>'
    + '<div class="pm-note">Used for the Result column, sorting, the Matrix\'s best run and its effect charts.'
    + (cur.source === 'heuristic' ? ' Right now <b>' + esc(cur.key) + '</b> is only a guess.' : '') + '</div>'
    + '<div class="pm-actions"><button class="action-btn pm-save">Save</button>'
    + '<button class="action-btn pm-cancel">Cancel</button>'
    + (canClear
      ? '<button class="action-btn pm-clear" title="Remove the ' + esc(cur.source) + ' setting">Clear ' + esc(cur.source) + ' setting</button>' : '')
    + '</div>';
  document.body.appendChild(pop);
  const keySel = pop.querySelector('.pm-key');
  const goalSel = pop.querySelector('.pm-goal');
  const syncGoal = () => {
    goalSel.value = keySel.value === cur.key && cur.goal ? cur.goal
      : (metricGoodDirection(keySel.value) < 0 ? 'min' : 'max');
  };
  syncGoal();
  keySel.addEventListener('change', syncGoal);
  if (levelOf === 'study' && cur.study) {
    const ss = pop.querySelector('.pm-study');
    if (ss) ss.value = cur.study;
  }

  const r = anchor.getBoundingClientRect();
  pop.style.top = Math.min(r.bottom + 6, window.innerHeight - pop.offsetHeight - 8) + 'px';
  pop.style.left = Math.max(8, Math.min(r.left, window.innerWidth - pop.offsetWidth - 8)) + 'px';

  const level = () => (pop.querySelector('input[name=pm-level]:checked') || {}).value || 'project';
  const send = (key) => {
    const lv = level();
    const study = (pop.querySelector('.pm-study') || {}).value || '';
    return _savePrimaryMetric({key, goal: key ? goalSel.value : '', level: lv, study, run: opts.runId || ''});
  };
  pop.querySelector('.pm-save').addEventListener('click', () => send(keySel.value));
  pop.querySelector('.pm-cancel').addEventListener('click', closePrimaryMetricPicker);
  const clear = pop.querySelector('.pm-clear');
  if (clear) {
    clear.addEventListener('click', () => _savePrimaryMetric({
      key: '', goal: '', level: cur.source, study: cur.study || '', run: opts.runId || ''}));
  }
  pop.addEventListener('keydown', ev => { if (ev.key === 'Escape') closePrimaryMetricPicker(); });
  _pmPicker = {el: pop, dispose: _dismissOnOutsideClick(pop, null, closePrimaryMetricPicker)};
  keySel.focus();
}

async function _savePrimaryMetric(body) {
  const res = await postApi('/api/primary-metric', body);
  if (!res || !res.ok) {
    owlSay('Could not set the metric' + (res && res.error ? ': ' + res.error : '') + '.');
    return;
  }
  closePrimaryMetricPicker();
  const where = {project: 'every run in this project', study: 'study ' + body.study,
                 run: 'this run'}[body.level];
  owlSay(body.key
    ? 'Runs are now judged by ' + body.key + ' (' + (body.goal === 'min' ? 'lower' : 'higher')
      + ' is better) for ' + where + '.'
    : 'Cleared the ' + body.level + ' setting.');
  await loadExperiments();
  if (document.body.classList.contains('matrix-active')) loadParamMatrix();
  else if (currentDetailId) refreshDetail(currentDetailId, {keepSidebar: true});
}

// The pin lives in the run header, because deciding a reference happens while
// looking at a run — either "this is the one to beat" or "this is no longer it".
// A run that is the reference by way of a *study* setting is not offered an
// unpin here: the button would clear the project level and appear to do
// nothing, since the study setting still shadows it.
function _referenceBtnHtml(exp) {
  const ref = exp.reference;
  const isRef = ref && !ref.stale && ref.id === exp.id;
  if (isRef && ref.source === 'study') {
    return '<button class="action-btn" disabled title="This run is the reference'
      + ' for study “' + esc(ref.study) + '”. Change it with'
      + ' `exptrack reference --study ' + esc(ref.study) + '`.">reference ✓</button>';
  }
  if (isRef) {
    return '<button class="action-btn" onclick="setAsReference(\'' + escJsAttr(exp.id)
      + '\', true)" title="Stop measuring runs against this one">Unpin reference</button>';
  }
  return '<button class="action-btn" onclick="setAsReference(\'' + escJsAttr(exp.id)
    + '\', false)" title="Measure every run against this one — a fixed target,'
    + ' separate from each run\'s own previous-run comparison">Set as reference</button>';
}

// Plain text, escaped at each insertion point — the codebase rule. Returning
// pre-escaped markup meant the tooltip had to strip tags back out of it, which
// double-escaped the study name and made a no-op regex look like sanitizing.
function _refSourceNote(ref) {
  return ref.source === 'study'
    ? 'set for study “' + ref.study + '”'
    : 'set for this project';
}

async function loadVsReference(id) {
  let d;
  try {
    d = await api('/api/reference-delta/' + id);
  } catch (e) { return; }
  if (currentDetailId !== id) return;
  const strip = document.getElementById('vs-ref-strip');
  if (!strip) return;
  // No reference configured: the strip is absent rather than empty. Nothing is
  // substituted for an unset reference — that is the point of the feature.
  if (!d || d.error || !d.reference) { strip.style.display = 'none'; return; }
  const ref = d.reference;

  // A stale reference is stated, not hidden. Rendering nothing here would read
  // as "no reference set" and quietly conceal that the comparison the user has
  // been reading stopped happening.
  if (ref.stale) {
    strip.innerHTML = _VS_REF_LABEL + '<span class="vs-ref-stale">' +
      (ref.stale === 'trashed'
        ? 'the reference run is in the Trash — restore it, or pick another'
        : 'the reference run no longer exists — pick another') +
      ' <span class="vs-ref-where">(' + esc(_refSourceNote(ref)) + ')</span></span>';
    strip.style.display = '';
    return;
  }

  if (d.is_reference) {
    strip.innerHTML = _VS_REF_LABEL +
      '<span class="vs-ref-self">this run <em>is</em> the reference ' +
      '<span class="vs-ref-where">(' + esc(_refSourceNote(ref)) + ')</span></span>';
    strip.style.display = '';
    return;
  }

  const chips = _vsChipsHtml(d)
    || '<div class="vs-row"><span class="vs-prev-none">identical to the reference</span></div>';
  strip.innerHTML = _vsHead(_VS_REF_LABEL, _vsRefLink(ref, d.current_created_at)) + chips;
  strip.style.display = '';
}

const _VS_REF_LABEL = '<span class="vs-prev-label vs-ref-label" title="Compared'
  + ' against the run pinned as this project\'s reference — a fixed target, not'
  + ' the previous run">vs reference</span>';

function _vsRefLink(ref, curCreatedAt) {
  const label = ref.name ? shortRunLabel(ref.name) : ref.id.slice(0, 6);
  const when = relEarlier(ref.created_at, curCreatedAt);
  return '<a class="vs-prev-open" href="#" onclick="showDetail(\'' + escJsAttr(ref.id)
    + '\');return false" title="Open the reference run — ' + esc(_refSourceNote(ref))
    + '">' + esc(label)
    + (when ? ' <span class="vs-prev-when">' + esc(when) + '</span>' : '')
    + _baselineFailedTag(ref.status)
    + '</a><span class="vs-ref-where">' + esc(_refSourceNote(ref)) + '</span>';
}

// Pin / unpin from the run's own header — the two places you decide a reference
// are while looking at a strong run and while looking at the current one.
async function setAsReference(id, clear) {
  const r = await postApi('/api/experiment/' + id + '/set-reference',
                          {study: '', clear: !!clear});
  if (!r || r.error) { alert((r && r.error) || 'Could not set the reference.'); return; }
  refreshDetail(id, {keepSidebar: true});
}

// A failed baseline is still the right baseline — "it broke, I fixed it, what
// changed?" is the loop this card exists for — but its metrics stop wherever it
// crashed, so an unqualified "acc 0.41 → 0.87" reads as a result that was never
// measured. Both surfaces say so instead of hiding the comparison.
function _baselineFailedTag(status) {
  if (status !== 'failed') return '';
  return '<span class="wc-baseline-failed" title="The run being compared against'
    + ' failed. Its parameters and code are exact; its metrics stop where it'
    + ' crashed.">failed</span>';
}

function _baselineFailedNote(status, metricRowCount) {
  if (status !== 'failed' || !metricRowCount) return '';
  return '<p class="wc-baseline-warn">The previous run failed, so the metric'
    + ' values below are wherever it stopped — not a finished result. Parameter'
    + ' and code changes are unaffected.</p>';
}

// The baseline chip carries its start time, not just its name. "Previous" is
// ambiguous on its own: the run list is newest-first, so the run this compares
// against sits *below* the current row and reads as the next one — the date is
// what makes it checkable at a glance.
function _vsPrevLink(prev, curCreatedAt) {
  if (!prev || !prev.id) return '';
  const label = prev.name ? shortRunLabel(prev.name) : prev.id.slice(0, 6);
  const when = relEarlier(prev.created_at, curCreatedAt);
  const full = prev.created_at ? ' (' + fmtDtFull(prev.created_at) + ')' : '';
  return '<a class="vs-prev-open" href="#" onclick="showDetail(\'' + escJsAttr(prev.id)
    + '\');return false" title="Open this run — the last run of this script started before'
    + ' the one you\'re viewing' + esc(full) + '">'
    + esc(label) + (when ? ' <span class="vs-prev-when">' + esc(when) + '</span>' : '')
    + _baselineFailedTag(prev.status)
    + '</a>';
}

// How much earlier the baseline ran, e.g. "2 min earlier", "2 days earlier".
// An absolute timestamp can't answer the question this needs to answer: `fmtDt`
// only resolves to the minute, so two runs launched seconds apart print the same
// string, and the newest-first list puts the older run *below* the current row —
// leaving no way to tell which direction the comparison runs. A relative age
// can't be misread.
function relEarlier(prevIso, curIso) {
  if (!prevIso || !curIso) return '';
  const a = expDate(prevIso), b = expDate(curIso);
  if (!a || !b || isNaN(a) || isNaN(b)) return '';
  const secs = Math.round((b.getTime() - a.getTime()) / 1000);
  if (secs < 0) return 'started LATER — not a previous run';   // never expected
  const units = [['day', 86400], ['hr', 3600], ['min', 60]];
  for (const [name, size] of units) {
    if (secs >= size) {
      const n = Math.round(secs / size);
      return n + ' ' + name + (n === 1 || name === 'min' || name === 'hr' ? '' : 's') + ' earlier';
    }
  }
  // Sub-second gaps ("0s earlier" reads as a contradiction) — back-to-back runs.
  return secs >= 1 ? secs + 's earlier' : 'just before';
}

// Both sides of a chip, at enough precision to differ (see fmtMetricPair).
function _vsFmtPair(a, b) {
  const sa = _vsFmt(a), sb = _vsFmt(b);
  if (sa !== sb || typeof a !== 'number' || typeof b !== 'number') return [sa, sb];
  return fmtMetricPair(a, b);
}

function _vsFmt(v) {
  if (v === null || v === undefined) return '∅';
  // Zero is below every magnitude threshold, and `seed 1→0` read `0.00e+0`.
  if (typeof v === 'number') return (v === 0 || (Math.abs(v) >= 1e-4 && Math.abs(v) < 1e6))
    ? String(Math.round(v * 10000) / 10000) : v.toExponential(2);
  const s = String(v);
  return s.length <= 20 ? s : s.slice(0, 18) + '…';
}

// ── Header: name, status line, actions ──────────────────────────────────────

// One menu, one row per format: Download and Copy side by side. The rule is
// that every Export has a Copy beside it, and two parallel menus kept them a
// click and a menu apart. Formats with no clipboard form (CSV/TSV/HTML) and the
// PDF report are download-only.
const _EXPORT_ROWS = [
  ['json', 'JSON', true], ['json-full', 'JSON (full)', true],
  ['markdown', 'Markdown / tables', true], ['plain', 'Plain text', true],
  ['csv', 'CSV', false], ['tsv', 'TSV', false], ['html', 'HTML', false],
];

function _exportMenuHtml(exp) {
  const id = escJsAttr(exp.id);
  const rows = _EXPORT_ROWS.map(([fmt, label, canCopy]) =>
    '<div class="export-row"><span class="export-row-label">' + label + '</span>'
    + '<button class="action-btn" onclick="closeDetailExport(this);downloadExportFmt(\'' + id + '\',\'' + fmt + '\')">Download</button>'
    + (canCopy ? '<button class="action-btn" onclick="closeDetailExport(this);copyExportFmt(\'' + id + '\',\'' + fmt + '\')">Copy</button>' : '')
    + '</div>').join('');
  return '<span class="detail-menu"><button class="action-btn primary" onclick="toggleDetailExport(this)">Export ▾</button>'
    + '<div class="export-dropdown-menu export-grid" style="display:none">' + rows
    + '<div class="export-row"><span class="export-row-label">PDF report</span>'
    + '<button class="action-btn" onclick="closeDetailExport(this);openPrintableReport({ids: [\'' + id + '\']})"'
    + ' title="Opens this run\'s report in a new tab; use its Save as PDF button">Open</button></div>'
    + '</div></span>';
}

// Name, a one-line status (what the old summary bar said, minus the counts the
// tab and card headers now carry), and four actions. Tools holds the analyses
// that used to be tabs; ⋯ holds what should take a second click.
function _detailHeaderHtml(exp, prevId) {
  const id = escJsAttr(exp.id);
  const live = exp.status === 'running'
    ? ' <span class="live-badge" id="live-badge"><span class="live-dot"></span>live</span>' : '';
  const tools = '<span class="detail-menu"><button class="action-btn" onclick="toggleDetailExport(this)">Tools ▾</button>'
    + '<div class="export-dropdown-menu" style="display:none">'
    + '<button class="action-btn" onclick="closeDetailExport(this);switchDetailTab(\'compare-within\',\'' + id + '\')">Compare within</button>'
    + '<button class="action-btn" onclick="closeDetailExport(this);switchDetailTab(\'confusion\',\'' + id + '\')"'
    + ' title="Calculate accuracy, precision, recall, F1 from a confusion matrix">Confusion matrix</button>'
    + (prevId ? '<button class="action-btn" onclick="closeDetailExport(this);compareWithPrevious(\''
      + escJsAttr(prevId) + '\',\'' + id + '\')">Compare with previous</button>' : '')
    + _referenceBtnHtml(exp)
    + '</div></span>';
  const more = '<span class="detail-menu"><button class="action-btn" onclick="toggleDetailExport(this)" title="More actions">⋯</button>'
    + '<div class="export-dropdown-menu" style="display:none">'
    + _compactBtnHtml(exp)
    + '<button class="action-btn danger" onclick="closeDetailExport(this);deleteExp(\'' + id + '\',\'' + escJsAttr(exp.name) + '\')">Delete</button>'
    + '</div></span>';
  return '<div class="detail-header">'
    + '<div class="detail-title"><h2 id="detail-name" class="editable-hint" data-rename-slot="' + esc(exp.id)
    + '" ondblclick="startInlineRename(\'' + id + '\',this)" title="Double-click to rename">' + esc(exp.name) + '</h2>'
    + '<div class="detail-subtitle"><span class="sum-item"><strong class="status-' + esc(exp.status || '') + '">'
    + esc(exp.status || '--') + '</strong>' + live + '</span>'
    + _primaryMetricSummary(exp)
    + '<span class="sum-item" title="Branch @ commit">' + esc(exp.git_branch || '--') + ' @ ' + _commitHtml(exp) + '</span>'
    + '<span class="sum-item" title="Started">' + fmtDt(exp.created_at) + '</span>'
    + '<span class="sum-item" title="Duration">' + fmtDur(exp.duration_s) + '</span></div></div>'
    + '<div class="detail-actions">'
    + (exp.status === 'running' ? '<button class="action-btn primary" onclick="finishExp(\'' + id + '\')">Finish Run</button>' : '')
    + _exportMenuHtml(exp) + tools + more
    + '<button class="close-btn" onclick="showWelcome()" title="Back to list">&times;</button>'
    + '</div></div>';
}
