"""Shared code rendering: Python syntax highlighting + word-level diff.

Single source of truth used by both the Sessions tab (cell source) and the
experiment detail view (Code Changes, git diff, timeline source viewer). Kept
dependency-free — a tiny tokenizer, an O(n*m) token LCS for word diffs, and a
unified-diff renderer that pairs in-place edits so a one-character change is
spotlighted instead of buried in two near-identical -/+ lines.
"""

JS_HIGHLIGHT = r"""
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
function _lineDiffRows(oldText, newText) {
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

// Render the per-cell "Code Changes" summary value. Capture stores it as
// "+added; -removed; ..." fragments joined by "; "; classify by the leading
// +/- and reuse the same word-diff renderer.
function _renderCodeChangeParts(value) {
  const rows = [];
  for (const part of String(value).split('; ')) {
    const t = part.trim();
    if (!t) continue;
    if (t.startsWith('+')) rows.push({kind:'add', text: t.slice(1).trim()});
    else if (t.startsWith('-')) rows.push({kind:'del', text: t.slice(1).trim()});
    else rows.push({kind:'ctx', text: t});
  }
  return _renderDiffRows(rows);
}
"""
