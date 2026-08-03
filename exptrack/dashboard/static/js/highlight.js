
// ── Python syntax highlighting ───────────────────────────────────────────────

const _PY_KW = new Set(['def','class','return','if','elif','else','for','while',
  'in','not','and','or','is','import','from','as','with','try','except','finally',
  'raise','lambda','yield','global','nonlocal','pass','break','continue','del',
  'assert','async','await','None','True','False','match','case']);
const _PY_BI = new Set(['print','len','range','dict','list','set','tuple','int',
  'float','str','bool','open','enumerate','zip','map','filter','sum','min','max',
  'abs','sorted','type','isinstance','super','self','cls','np','pd','plt','torch']);

// Compiled once, reused across every line/render (reset lastIndex per call).
const _PY_TOKEN_RE = /(#.*$)|("(?:[^"\\]|\\.)*"?|'(?:[^'\\]|\\.)*'?)|(@[A-Za-z_]\w*)|(\b\d[\w.]*)|([A-Za-z_]\w*)|(\s+)|([^\sA-Za-z0-9_])/g;

// Highlight one line of Python. Input is RAW (unescaped); every emitted token is
// HTML-escaped as it is wrapped, so the result is safe to inject.
function _highlightPy(line) {
  const re = _PY_TOKEN_RE;
  re.lastIndex = 0;
  let out = '', m;
  while ((m = re.exec(line)) !== null) {
    if (m[1]) out += `<span class="tok-com">${escapeHtml(m[1])}</span>`;
    else if (m[2]) out += `<span class="tok-str">${escapeHtml(m[2])}</span>`;
    else if (m[3]) out += `<span class="tok-dec">${escapeHtml(m[3])}</span>`;
    else if (m[4]) out += `<span class="tok-num">${escapeHtml(m[4])}</span>`;
    else if (m[5]) {
      const w = m[5];
      const isCall = /^\s*\(/.test(line.slice(re.lastIndex));
      let cls = _PY_KW.has(w) ? 'tok-kw' : _PY_BI.has(w) ? 'tok-bi'
              : isCall ? 'tok-fn' : '';
      out += cls ? `<span class="${cls}">${escapeHtml(w)}</span>` : escapeHtml(w);
    }
    else if (m[6]) out += m[6];               // whitespace — safe as-is
    else out += escapeHtml(m[7]);
  }
  return out;
}

// ── Stale-print detection ────────────────────────────────────────────────────
// A print() that emits a hardcoded number (e.g. print("accuracy 98")) is often
// a stale value the author meant to interpolate from a variable. Flag the line
// so it's easy to spot. We scrub f-string {…} placeholders first (those numbers
// ARE interpolated and fine) and only count a numeric literal sitting in a
// value position (after whitespace/quote/paren/comma/=) so format specs like
// %.4f and identifier tails like f1_score / utf8 don't trip it.

const STALE_PRINT_TITLE =
  'Possible stale value — this print() has a hardcoded number; did you mean to print a variable?';

function _isStalePrintLine(line) {
  if (!line) return false;
  const m = /\bprint\s*\(/.exec(line);
  if (!m) return false;
  const scrubbed = line.slice(m.index).replace(/\{[^{}]*\}/g, '');
  return /(^|[\s"'(,=])\d+(\.\d+)?(?![A-Za-z0-9_])/.test(scrubbed);
}

function _stalePrintBadge() {
  return '<span class="stale-print-badge" title="' + STALE_PRINT_TITLE + '">⚠ stale?</span>';
}

// ── Word-level diff ──────────────────────────────────────────────────────────
// When a line is edited in place (threshold=0.7 → 0.5), a plain -/+ pair makes
// you hunt for the one token that moved. _wordDiffPair finds the changed run via
// a token LCS and spotlights just that span, while still syntax-highlighting the
// unchanged code around it.

function _wordTokens(s) {
  return s.match(/[A-Za-z0-9_]+|\s+|[^\sA-Za-z0-9_]/g) || [];
}

// LCS membership flags over two token arrays. Lines are short, so a simple
// O(n*m) DP is plenty. Returns {aCommon, bCommon} boolean arrays.
function _tokenLcs(a, b) {
  const n = a.length, m = b.length;
  const dp = Array.from({length: n + 1}, () => new Int32Array(m + 1));
  for (let i = n - 1; i >= 0; i--)
    for (let j = m - 1; j >= 0; j--)
      dp[i][j] = a[i] === b[j] ? dp[i+1][j+1] + 1 : Math.max(dp[i+1][j], dp[i][j+1]);
  const aCommon = new Array(n).fill(false);
  const bCommon = new Array(m).fill(false);
  let i = 0, j = 0;
  while (i < n && j < m) {
    if (a[i] === b[j]) { aCommon[i] = bCommon[j] = true; i++; j++; }
    else if (dp[i+1][j] >= dp[i][j+1]) i++;
    else j++;
  }
  return { aCommon, bCommon };
}

// Build HTML for one side of a word diff. Runs of common tokens are syntax-
// highlighted together (so call/keyword context survives); changed runs get a
// `wordCls` spotlight span.
function _wordSide(tokens, common, wordCls) {
  let out = '', buf = '', changed = '';
  const flushCommon = () => { if (buf) { out += _highlightPy(buf); buf = ''; } };
  const flushChanged = () => {
    if (changed) { out += `<span class="${wordCls}">${escapeHtml(changed)}</span>`; changed = ''; }
  };
  for (let i = 0; i < tokens.length; i++) {
    if (common[i]) { flushChanged(); buf += tokens[i]; }
    else { flushCommon(); changed += tokens[i]; }
  }
  flushCommon(); flushChanged();
  return out;
}

function _wordDiffPair(oldLine, newLine) {
  const a = _wordTokens(oldLine), b = _wordTokens(newLine);
  // Guard against pathological line lengths and degenerate pairs — fall back to
  // plain per-line highlighting.
  if (!a.length || !b.length || a.length * b.length > 40000) {
    return { oldHtml: _highlightPy(oldLine), newHtml: _highlightPy(newLine) };
  }
  const { aCommon, bCommon } = _tokenLcs(a, b);
  // Only spotlight when the two lines are clearly a small in-place edit. If most
  // tokens differ it's a rewrite, not a tweak — word-pills turn to confetti, so
  // fall back to plain add/del lines (still syntax-highlighted) instead.
  let common = 0, aReal = 0, bReal = 0;
  for (let i = 0; i < a.length; i++) if (a[i].trim()) { aReal++; if (aCommon[i]) common++; }
  for (let j = 0; j < b.length; j++) if (b[j].trim()) bReal++;
  const sim = (aReal + bReal) ? (2 * common) / (aReal + bReal) : 0;
  if (sim < 0.5) {
    return { oldHtml: _highlightPy(oldLine), newHtml: _highlightPy(newLine) };
  }
  return {
    oldHtml: _wordSide(a, aCommon, 'dword-del'),
    newHtml: _wordSide(b, bCommon, 'dword-add'),
  };
}

// Line-level diff between two full sources → rows for _renderDiffRows. Unchanged
// lines become `ctx` (so the full source stays visible), changed lines become
// del/add runs that _diffRowsToHtml then word-diffs — so "view source" on an
// edited cell spotlights the changed token, not just the short timeline preview.
// Returns null past a sane size so a huge paste can't lock the UI on the O(n*m) DP.
//
// Long runs of unchanged lines are collapsed here rather than at each call
// site: rendering every line of a 500-line file to spotlight two is a property
// of *this* output, so every consumer should get the collapse without
// remembering to ask (pass `fullContext` to opt out).
function _lineDiffRows(oldText, newText, fullContext) {
  const rows = _lineDiffRowsRaw(oldText, newText);
  return (rows && !fullContext) ? _collapseDiffContext(rows) : rows;
}

function _lineDiffRowsRaw(oldText, newText) {
  const a = String(oldText).split('\n');
  const b = String(newText).split('\n');
  const n = a.length, m = b.length;
  if (n * m > 4000000) return null;
  const dp = Array.from({length: n + 1}, () => new Int32Array(m + 1));
  for (let i = n - 1; i >= 0; i--)
    for (let j = m - 1; j >= 0; j--)
      dp[i][j] = a[i] === b[j] ? dp[i+1][j+1] + 1 : Math.max(dp[i+1][j], dp[i][j+1]);
  const rows = [];
  let i = 0, j = 0;
  while (i < n && j < m) {
    if (a[i] === b[j]) { rows.push({kind:'ctx', text: a[i]}); i++; j++; }
    else if (dp[i+1][j] >= dp[i][j+1]) { rows.push({kind:'del', text: a[i]}); i++; }
    else { rows.push({kind:'add', text: b[j]}); j++; }
  }
  while (i < n) rows.push({kind:'del', text: a[i++]});
  while (j < m) rows.push({kind:'add', text: b[j++]});
  return rows;
}

// Lines of unchanged context kept either side of a change, matching git's
// default. Without this the full-source diff renders every line of the file to
// spotlight two — fine for a 20-line script, unreadable for a 500-line one,
// where the change you opened the panel to see is lost in a wall of context.
const DIFF_CONTEXT_LINES = 3;

// Replace long runs of unchanged lines with a single collapsed marker row.
// Returns a new row list; rows keep their original shape so every downstream
// renderer (word-diff pairing, line-number gutter) is unaffected. A run only
// collapses when it is strictly longer than the context it would leave behind
// plus the marker itself — otherwise collapsing would *add* a row.
function _collapseDiffContext(rows, ctxLines) {
  if (!Array.isArray(rows)) return rows;
  const ctx = ctxLines == null ? DIFF_CONTEXT_LINES : ctxLines;
  const changed = rows.map(r => r.kind === 'add' || r.kind === 'del');
  if (!changed.some(Boolean)) return rows;      // nothing changed: show as-is
  const keep = rows.map((r, i) => {
    if (r.kind !== 'ctx') return true;
    for (let d = 1; d <= ctx; d++)
      if (changed[i - d] || changed[i + d]) return true;
    return false;
  });
  const out = [];
  let run = 0;
  for (let i = 0; i < rows.length; i++) {
    if (keep[i]) {
      if (run) { out.push({kind: 'fold', count: run}); run = 0; }
      out.push(rows[i]);
    } else { run++; }
  }
  if (run) out.push({kind: 'fold', count: run});
  return out;
}

// ── Unified diff renderer ────────────────────────────────────────────────────
// Rows are {kind:'add'|'del'|'ctx'|'hunk', text}. Consecutive del-runs
// immediately followed by add-runs are zipped and word-diffed; everything else
// is line-highlighted with a tint + sign gutter.

function _dl(kind, sign, html, gutter) {
  return `<div class="dl dl-${kind}">${gutter || ''}<span class="dl-sign">${sign}</span><span class="dl-text">${html}</span></div>`;
}

// Gutter cell holding the old- and new-file line numbers (either may be blank
// for a pure add/del). Only emitted when line numbers are requested.
function _gutter(o, n) {
  return `<span class="dl-no"><span class="dl-no-o">${o == null ? '' : o}</span>` +
         `<span class="dl-no-n">${n == null ? '' : n}</span></span>`;
}

// Word-level spotlighting is on by default but the user can turn it off
// (Settings → Display) to get plain line-level add/del — handy when an edit is
// large enough that the in-line pills get busy. Off ⇒ never pair runs.
function _wordDiffEnabled() {
  try { return localStorage.getItem('exptrack-word-diff') !== 'false'; }
  catch (e) { return true; }
}

function _diffRowsToHtml(rows, lineNumbers) {
  const wordDiff = _wordDiffEnabled();
  let oldNo = 1, newNo = 1;
  const gut = lineNumbers ? _gutter : () => '';
  let out = '';
  for (let i = 0; i < rows.length; i++) {
    const r = rows[i];
    if (r.kind === 'hunk') {
      // Seed the counters from the @@ -a,b +c,d @@ header so numbers line up.
      const mm = /@@\s*-(\d+)(?:,\d+)?\s*\+(\d+)(?:,\d+)?\s*@@/.exec(r.text);
      if (mm) { oldNo = +mm[1]; newNo = +mm[2]; }
      out += `<div class="dl dl-hunk">${lineNumbers ? '<span class="dl-no"></span>' : ''}${escapeHtml(r.text)}</div>`;
      continue;
    }
    if (r.kind === 'fold') {
      // Collapsed unchanged context. The counters must still advance by the
      // number of hidden lines or every line number below the fold is wrong.
      const n = r.count || 0;
      oldNo += n; newNo += n;
      out += `<div class="dl dl-fold">${lineNumbers ? '<span class="dl-no"></span>' : ''}` +
             `<span class="dl-sign"></span><span class="dl-text">\u22ef ${n} unchanged line${n === 1 ? '' : 's'}</span></div>`;
      continue;
    }
    if (r.kind === 'ctx')  { out += _dl('ctx', ' ', _highlightPy(r.text), gut(oldNo++, newNo++)); continue; }
    if (r.kind === 'add')  { out += _dl('add', '+', _highlightPy(r.text), gut(null, newNo++)); continue; }
    // del — gather the del-run and the add-run that follows, then zip for word diff.
    const dels = [];
    while (i < rows.length && rows[i].kind === 'del') dels.push(rows[i++]);
    const adds = [];
    while (i < rows.length && rows[i].kind === 'add') adds.push(rows[i++]);
    i--; // outer loop will ++ past the row we stopped on
    const paired = wordDiff ? Math.min(dels.length, adds.length) : 0;
    for (let k = 0; k < dels.length; k++) {
      const html = k < paired ? _wordDiffPair(dels[k].text, adds[k].text).oldHtml : _highlightPy(dels[k].text);
      out += _dl('del', '-', html, gut(oldNo++, null));
    }
    for (let k = 0; k < adds.length; k++) {
      const html = k < paired ? _wordDiffPair(dels[k].text, adds[k].text).newHtml : _highlightPy(adds[k].text);
      out += _dl('add', '+', html, gut(null, newNo++));
    }
  }
  return out;
}

function _renderDiffRows(rows, lineNumbers) {
  if (!rows.length) return '';
  return `<div class="code-diff${lineNumbers ? ' code-diff-numbered' : ''}">${_diffRowsToHtml(rows, lineNumbers)}</div>`;
}

// Parse a raw unified-diff string into rows and render. File headers
// (diff --git / index / +++ / ---) are dropped; @@ hunks kept as separators.
function _renderUnifiedDiff(diffText) {
  const rows = [];
  for (const line of String(diffText).split('\n')) {
    if (line.startsWith('+++') || line.startsWith('---') ||
        line.startsWith('diff --git') || line.startsWith('index ') ||
        line.startsWith('new file') || line.startsWith('deleted file') ||
        line.startsWith('rename ') || line.startsWith('similarity ')) continue;
    if (line.startsWith('@@')) rows.push({kind:'hunk', text: line});
    else if (line.startsWith('+')) rows.push({kind:'add', text: line.slice(1)});
    else if (line.startsWith('-')) rows.push({kind:'del', text: line.slice(1)});
    else rows.push({kind:'ctx', text: line.startsWith(' ') ? line.slice(1) : line});
  }
  return _renderDiffRows(rows, true);
}

// ── Splitting a raw git diff into its files ──────────────────────────────────
// Lifted here from sessions.js so the experiment view and the Sessions view
// share one parser: the run detail now renders the working-tree diff per file
// (see `_splitDiffByScript`), which is exactly what the session split-diff view
// had already needed.

function _parseDiff(diff) {
  const files = [];
  let curFile = null;
  let curHunk = null;
  let totalAdd = 0, totalDel = 0;
  const newFile = (header) => {
    curFile = { header: header || '', hunks: [], plus: 0, minus: 0 };
    files.push(curFile);
    curHunk = null;
  };
  for (const ln of diff.split('\n')) {
    if (ln.startsWith('diff --git')) { newFile(ln); continue; }
    if (ln.startsWith('--- ') || ln.startsWith('+++ ')
        || ln.startsWith('index ') || ln.startsWith('new file')
        || ln.startsWith('deleted file') || ln.startsWith('similarity')
        || ln.startsWith('rename ')) {
      if (!curFile) newFile('');
      curFile.header += (curFile.header ? '\n' : '') + ln;
      continue;
    }
    if (ln.startsWith('@@')) {
      if (!curFile) newFile('');
      curHunk = { header: ln, rows: [] };
      curFile.hunks.push(curHunk);
      continue;
    }
    if (!curHunk) continue;
    let kind = 'ctx';
    if (ln.startsWith('+')) { kind = 'add'; curFile.plus++; totalAdd++; }
    else if (ln.startsWith('-')) { kind = 'del'; curFile.minus++; totalDel++; }
    curHunk.rows.push({ kind, text: ln.length ? ln.slice(1) : '' });
  }
  return { files, plus: totalAdd, minus: totalDel };
}

function _shortFileLabel(header) {
  if (!header) return '(file)';
  const m = header.match(/^diff --git a\/(.+?) b\/(.+)$/m);
  if (m) return m[1] === m[2] ? m[1] : m[1] + ' → ' + m[2];
  const mm = header.match(/^\+\+\+ b\/(.+)$/m);
  if (mm) return mm[1];
  return header.split('\n')[0].slice(0, 80);
}

// Does this diff's file path name the run's own script? Diff paths are
// repo-relative and `script` is absolute, so compare from the right — with a
// separator boundary, or `train.py` would match `retrain.py`.
function _diffFileIsScript(label, script) {
  if (!label || !script) return false;
  const f = String(label).split(' → ').pop().trim();
  const s = String(script).replace(/\\/g, '/');
  return s === f || s.endsWith('/' + f);
}

// Split a raw git diff into the run's own script and everything else, each
// rendered as labelled per-file groups.
//
// Two things drive this. `_renderUnifiedDiff` drops every `diff --git` header,
// so a multi-file working tree rendered as one undifferentiated wall of hunks
// that never said which file any of them came from. And the run detail used to
// carry a *second*, script-scoped panel above this one against the same commit
// — the same edit rendered twice in any single-script project. Returning the
// two halves separately lets one panel answer both questions without repeating
// a line: what changed in the script this run executed, and what else in the
// tree was uncommitted at the time.
//
// Returns {scriptHtml, otherHtml, scriptFiles, otherFiles, headerless}.
//
// Memoized on (diffText, script) against a single previous call, because the
// detail panel is rebuilt on a 5-second poll for the whole length of a live run
// while the working-tree diff is almost never what changed between ticks —
// metrics are. One entry is the right size: the panel renders one run's diff at
// a time, and the body is already bounded by `max_git_diff_kb`.
let _sdbsKey = null, _sdbsVal = null;
function _splitDiffByScript(diffText, script) {
  const key = String(script) + ' ' + String(diffText);
  if (key === _sdbsKey) return _sdbsVal;
  const out = _splitDiffByScriptUncached(diffText, script);
  _sdbsKey = key; _sdbsVal = out;
  return out;
}

function _splitDiffByScriptUncached(diffText, script) {
  const parsed = _parseDiff(String(diffText));
  const files = parsed.files.filter(f => f.hunks.length);
  if (!files.length) {
    // A fragment with no `diff --git` headers — render it whole rather than
    // silently dropping it.
    return { scriptHtml: '', otherHtml: _renderUnifiedDiff(diffText),
             scriptFiles: 0, otherFiles: 0, headerless: true };
  }
  const groups = { script: [], other: [] };
  for (const f of files) {
    const label = _shortFileLabel(f.header);
    const isScript = _diffFileIsScript(label, script);
    groups[isScript ? 'script' : 'other'].push(_diffFileHtml(f, label, isScript));
  }
  return {
    scriptHtml: groups.script.join(''), otherHtml: groups.other.join(''),
    scriptFiles: groups.script.length, otherFiles: groups.other.length,
    headerless: false,
  };
}

function _diffFileHtml(f, label, isScript) {
  const rows = [];
  for (const h of f.hunks) {
    rows.push({ kind: 'hunk', text: h.header });
    for (const r of h.rows) rows.push(r);
  }
  const stats = '<span class="dfile-stat dfile-plus">+' + f.plus + '</span>'
    + '<span class="dfile-stat dfile-minus">−' + f.minus + '</span>';
  const tag = isScript
    ? '<span class="dfile-tag" title="The script this run executed">this run\'s script</span>'
    : '';
  return '<div class="dfile' + (isScript ? ' dfile-primary' : '') + '">'
    + '<div class="dfile-head"><code class="dfile-name">' + esc(label) + '</code>'
    + tag + '<span class="dfile-stats">' + stats + '</span></div>'
    + _renderDiffRows(rows, true) + '</div>';
}

// Normalize a timeline event's `source_diff` to a list of {op, line}.
//
// The two capture paths store different shapes and always have: a notebook cell
// stores a JSON list of {op, line} (from simple_diff), while a script stores the
// flat "; "-joined "+ line"/"- line" summary. The timeline renderer only ever
// handled the list, so for every script run it iterated the *string one
// character at a time* — `d.op` was undefined for each, so no diff rows were
// emitted and the row rendered blank, followed by a "... N more lines" note
// where N was `string.length - 8` (a character count presented as a line count:
// a 57-char summary claimed 49 more lines). Normalizing here fixes every run
// already recorded, which fixing the writer alone would not.
// Numbered, syntax-highlighted source block. One implementation, used by the
// timeline's source fold and by its snapshot fallback — two renderers for
// "show captured Python with line numbers" is how the gutter markup drifts.
function _numberedSourceHtml(src) {
  return (src || '').split('\n').map((ln, i) =>
    '<div class="cl"><span class="cl-no">' + (i + 1) + '</span>' +
    '<span class="cl-src">' + _highlightPy(ln) + '</span></div>').join('');
}

function _normalizeSourceDiff(sd) {
  if (!sd) return [];
  if (Array.isArray(sd)) return sd;
  if (typeof sd !== 'string') return [];
  const out = [];
  for (const part of sd.split('; ')) {
    const t = part.trim();
    if (!t) continue;
    if (t.startsWith('+')) out.push({op: '+', line: t.slice(1).trim()});
    else if (t.startsWith('-')) out.push({op: '-', line: t.slice(1).trim()});
    else out.push({op: 'summary', line: t});
  }
  return out;
}

// Render the per-cell "Code Changes" summary value — the same "; "-joined
// format `_normalizeSourceDiff` reads, so it parses through that one reader
// and only maps op → row kind. Two parsers of one storage format drift, and
// the format is still moving (summarize_changed_lines now appends its own
// "… [truncated — N of M …]" fragment).
const _OP_KIND = {'+': 'add', '-': 'del'};

function _renderCodeChangeParts(value) {
  const rows = _normalizeSourceDiff(String(value)).map(
    p => ({kind: _OP_KIND[p.op] || 'ctx', text: p.line}));
  return _renderDiffRows(rows);
}
