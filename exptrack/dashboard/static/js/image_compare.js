

// ── Image Comparison Modal ───────────────────────────────────────────────────

let _imgCmpMode = 'side';
let _imgCmpData = null;
// The candidate list behind each side, so the modal can step through it.
// Picking two images out of 900 by closing the modal, scrolling, and picking
// again is the whole cost this removes.
let _imgCmpLists = {a: [], b: []};
// Overlay tints. Fading between two images with the slider answers "are these
// different?" only when the difference is large — a shifted boundary or a few
// wrong pixels is invisible mid-fade, because both images are half-drawn at
// once. Colouring each side and adding them makes agreement neutral and
// disagreement coloured, which is the same trick as a red/cyan anaglyph.
const IMG_CMP_TINTS = [
  {id: 'none', label: 'None',
   help: 'Fade between the two images with the slider'},
  {id: 'yellowblue', label: 'Yellow / Blue',
   help: 'A is yellow, B is blue \u2014 grey where they agree, yellow or blue where only one has ink'},
  {id: 'redcyan', label: 'Red / Cyan',
   help: 'A is red, B is cyan \u2014 grey where they agree, red or cyan where only one has ink'},
  {id: 'difference', label: 'Difference',
   help: 'Black where the two are identical, bright where they are not'},
];

let _imgCmpTint = 'none';
try {
  const savedTint = localStorage.getItem('exptrack-overlay-tint');
  if (savedTint && IMG_CMP_TINTS.some(t => t.id === savedTint)) _imgCmpTint = savedTint;
} catch (e) { /* storage can throw outright; the default stands */ }

function setOverlayTint(id) {
  if (!IMG_CMP_TINTS.some(t => t.id === id)) return;
  _imgCmpTint = id;
  try { localStorage.setItem('exptrack-overlay-tint', id); } catch (e) {}
  renderCompareBody();
}

// Each tint is a projection of the image's luminance onto one or two
// channels, so complementary pairs sum back to exactly neutral grey where the
// two images agree. This has to be a colour matrix: the CSS `grayscale sepia
// saturate hue-rotate` chain only lands *near* a hue, and near-yellow plus
// near-blue sums to pink — an identical pair then looks like a difference,
// which is the one thing this view must never say.
const _TINT_LUM = '0.299 0.587 0.114 0 0';
const _TINT_ZERO = '0 0 0 0 0';
const _TINT_ALPHA = '0 0 0 1 0';

function _tintFilter(id, rows) {
  return '<filter id="' + id + '" color-interpolation-filters="sRGB">'
    + '<feColorMatrix type="matrix" values="' + rows.join(' ') + '"/></filter>';
}

// Rendered inside the modal, so it is removed with it and cannot collide with
// anything on the page behind.
function _tintSvgDefs() {
  const L = _TINT_LUM, Z = _TINT_ZERO, A = _TINT_ALPHA;
  return '<svg class="img-cmp-tint-defs" aria-hidden="true" focusable="false"><defs>'
    + _tintFilter('imgCmpTintYellow', [L, L, Z, A])
    + _tintFilter('imgCmpTintBlue', [Z, Z, L, A])
    + _tintFilter('imgCmpTintRed', [L, Z, Z, A])
    + _tintFilter('imgCmpTintCyan', [Z, L, L, A])
    + '</defs></svg>';
}

// The tint picker, and under it the sentence saying how to read the result —
// a colour scheme nobody has explained is just a strangely coloured image.
function _tintBarHtml() {
  const active = IMG_CMP_TINTS.find(t => t.id === _imgCmpTint) || IMG_CMP_TINTS[0];
  let h = '<div class="img-cmp-tint-bar"><span class="img-cmp-tint-label">Tint</span>';
  for (const t of IMG_CMP_TINTS) {
    h += '<button type="button" class="img-cmp-tint-btn'
      + (t.id === _imgCmpTint ? ' active' : '') + '"'
      + ' title="' + esc(t.help) + '"'
      + ' onclick="setOverlayTint(\'' + escJsAttr(t.id) + '\')">'
      + esc(t.label) + '</button>';
  }
  h += '<span class="img-cmp-tint-help">' + esc(active.help) + '</span></div>';
  return h;
}

let _swipePct = 50;
let _swipeDragging = false;

// `run1`/`run2` name the experiment each image came from. They are optional —
// an intra-run comparison has one run and nothing to disambiguate — but for a
// cross-run overlay they are the point: both runs usually write the same file
// name, so the file name alone said nothing about which side was which.
function openCompareModal(src1, name1, src2, name2, run1, run2, opts) {
  // See _holdMainScroll: the thumbnails this was opened from are in the page
  // scroller, and a collapse there clamps the reader to the top.
  const restore = _holdMainScroll();
  _imgCmpData = {src1, name1, src2, name2, run1: run1 || '', run2: run2 || '',
                 path1: _imgCmpPath(src1), path2: _imgCmpPath(src2)};
  _imgCmpLists = {a: (opts && opts.listA) || [], b: (opts && opts.listB) || []};
  _imgCmpMode = 'side';
  const overlay = document.createElement('div');
  overlay.className = 'img-cmp-overlay';
  overlay.id = 'img-cmp-overlay';

  let html = '<div class="img-cmp-header">';
  html += '<div class="img-cmp-names">'
       + '<span title="' + esc(_imgCmpTitle(run1, _imgCmpPath(src1))) + '">'
       + esc(_imgCmpSide('A', run1, name1)) + '</span>'
       + '<span title="' + esc(_imgCmpTitle(run2, _imgCmpPath(src2))) + '">'
       + esc(_imgCmpSide('B', run2, name2)) + '</span></div>';
  html += '<div class="img-cmp-modes">';
  html += '<button class="active" data-mode="side" onclick="setCompareMode(\'side\',this)">Side by Side</button>';
  html += '<button data-mode="overlay" onclick="setCompareMode(\'overlay\',this)">Overlay</button>';
  html += '<button data-mode="swipe" onclick="setCompareMode(\'swipe\',this)">Swipe</button>';
  html += '</div>';
  html += modalBackdropPickerHtml();
  html += '<button class="img-cmp-close" onclick="closeCompareModal()">&times;</button>';
  html += '</div>';
  html += '<div class="img-cmp-nav" id="img-cmp-nav"></div>';
  html += '<div class="img-cmp-body" id="img-cmp-body"></div>';
  overlay.innerHTML = html;

  overlay.addEventListener('click', function(ev) { if (ev.target === overlay) closeCompareModal(); });
  document.body.appendChild(overlay);
  applyModalBackdrop();

  const escHandler = function(ev) {
    if (ev.key === 'Escape') {
      closeCompareModal();
      document.removeEventListener('keydown', escHandler);
      return;
    }
    // Left/right steps A, shift+left/right steps B — the pair a reader flips
    // through is usually one side at a time.
    if (ev.key === 'ArrowLeft' || ev.key === 'ArrowRight') {
      const side = ev.shiftKey ? 'b' : 'a';
      if (!_imgCmpLists[side].length) return;
      ev.preventDefault();
      stepCompareImage(side, ev.key === 'ArrowLeft' ? -1 : 1);
    }
  };
  document.addEventListener('keydown', escHandler);
  overlay.__escHandler = escHandler;
  overlay.__restoreScroll = restore;

  renderCompareBody();
  _renderCmpNav();
  restore();
  requestAnimationFrame(restore);
}

function closeCompareModal() {
  const el = document.getElementById('img-cmp-overlay');
  let restore = null;
  if (el) {
    if (el.__escHandler) document.removeEventListener('keydown', el.__escHandler);
    restore = el.__restoreScroll;
    el.remove();
  }
  _imgCmpData = null;
  _imgCmpLists = {a: [], b: []};
  _swipeDragging = false;
  if (restore) { restore(); requestAnimationFrame(restore); }
}

function setCompareMode(mode, btn) {
  _imgCmpMode = mode;
  // Mark by mode rather than by the element clicked: the tint bar and the
  // nav rows can change the mode without a button of their own, and a header
  // that still highlights Side by Side while showing an overlay is lying.
  const bar = (btn && btn.parentElement)
    || document.querySelector('#img-cmp-overlay .img-cmp-modes');
  if (bar) {
    bar.querySelectorAll('button').forEach(b => b.classList.toggle(
      'active', b === btn || (!btn && b.getAttribute('data-mode') === mode)));
  }
  renderCompareBody();
}

// The path a file URL was built from (fileUrl encodes it and may append a
// token), so every label can show where the image actually came from.
function _imgCmpPath(src) {
  try {
    const raw = String(src || '').split('?')[0].replace(/^\/api\/file\//, '');
    return decodeURIComponent(raw);
  } catch (e) {
    return String(src || '');
  }
}

// "run — file", or just the file when the caller knows of no run.
function _imgCmpWho(run, name) {
  return run ? run + ' — ' + name : name;
}

// The run is what identifies a side; A/B is only the tiebreak when two images
// come from the same run (the Images tab compares a run against itself).
function _imgCmpSide(side, run, name) {
  return run ? run + ' — ' + name : side + ': ' + name;
}

// A slider end: the run it belongs to, falling back to the A/B marker when
// both images come from one run.
function _imgCmpEnd(side, run) {
  return run ? midEllipsis(run, 22) : side;
}

// Hover text: the run, then the path the file was read from.
function _imgCmpTitle(run, path) {
  return (run ? run + String.fromCharCode(10) : '') + path;
}

// One side-by-side panel: the image, then an A/B badge, the run it came from
// and the file name under it.
function _imgCmpPanel(side, src, name, run) {
  const path = _imgCmpPath(src);
  const title = _imgCmpTitle(run, path);
  let label = '<span class="img-cmp-badge-ab">' + side + '</span>';
  if (run) label += '<span class="img-cmp-run">' + esc(run) + '</span>';
  label += esc(name);
  return '<div class="img-cmp-panel"><img src="' + src + '" alt="' + side
    + '" title="' + esc(title) + '">'
    + '<div class="img-cmp-label" title="' + esc(title) + '">' + label
    + '</div></div>';
}

// Where the currently shown image sits in its side's candidate list.
function _cmpIndexOf(side) {
  const list = _imgCmpLists[side] || [];
  const src = side === 'a' ? (_imgCmpData || {}).src1 : (_imgCmpData || {}).src2;
  return list.findIndex(i => i.src === src);
}

// One row per side: where you are in that run's images, and how to move.
function _renderCmpNav() {
  const el = document.getElementById('img-cmp-nav');
  if (!el || !_imgCmpData) return;
  let h = '';
  for (const side of ['a', 'b']) {
    const list = _imgCmpLists[side] || [];
    if (list.length < 2) continue;
    const idx = _cmpIndexOf(side);
    const run = side === 'a' ? _imgCmpData.run1 : _imgCmpData.run2;
    const name = side === 'a' ? _imgCmpData.name1 : _imgCmpData.name2;
    h += '<div class="img-cmp-nav-row">'
      + '<span class="img-cmp-nav-who">' + esc(run || side.toUpperCase()) + '</span>'
      + '<button onclick="stepCompareImage(\'' + side + '\',-1)" title="Previous image'
      + (side === 'b' ? ' (shift+left)' : ' (left arrow)') + '">&#9664;</button>'
      + '<span class="img-cmp-nav-pos">' + (idx < 0 ? '?' : idx + 1) + ' / '
      + list.length + '</span>'
      + '<button onclick="stepCompareImage(\'' + side + '\',1)" title="Next image'
      + (side === 'b' ? ' (shift+right)' : ' (right arrow)') + '">&#9654;</button>'
      + '<input type="text" class="img-cmp-nav-find" placeholder="jump to name..."'
      + ' oninput="jumpCompareImage(\'' + side + '\',this.value)">'
      + '<span class="img-cmp-nav-name" title="' + esc(name) + '">' + esc(name) + '</span>'
      + '</div>';
  }
  el.innerHTML = h;
}

// Move one side to another image in its list, wrapping at the ends.
function stepCompareImage(side, delta) {
  const list = _imgCmpLists[side] || [];
  if (!list.length || !_imgCmpData) return;
  const at = _cmpIndexOf(side);
  const next = list[((at < 0 ? 0 : at + delta) + list.length) % list.length];
  if (!next) return;
  _setCompareSide(side, next);
}

// First image in this side's list whose name contains the query. Typing is
// the only way to reach image 700 of 900 without 60 clicks on the arrow.
function jumpCompareImage(side, query) {
  const q = String(query || '').trim().toLowerCase();
  if (!q) return;
  const hit = (_imgCmpLists[side] || []).find(
    i => (i.name || '').toLowerCase().includes(q));
  if (hit) _setCompareSide(side, hit);
}

function _setCompareSide(side, img) {
  if (side === 'a') {
    _imgCmpData.src1 = img.src;
    _imgCmpData.name1 = img.name;
    _imgCmpData.path1 = _imgCmpPath(img.src);
    if (img.run) _imgCmpData.run1 = img.run;
  } else {
    _imgCmpData.src2 = img.src;
    _imgCmpData.name2 = img.name;
    _imgCmpData.path2 = _imgCmpPath(img.src);
    if (img.run) _imgCmpData.run2 = img.run;
  }
  _refreshCompareHeader();
  renderCompareBody();
  _renderCmpNav();
}

// The header names both sides, so stepping has to rewrite it.
function _refreshCompareHeader() {
  const names = document.querySelector('#img-cmp-overlay .img-cmp-names');
  if (!names || !_imgCmpData) return;
  const d = _imgCmpData;
  names.innerHTML =
    '<span title="' + esc(_imgCmpTitle(d.run1, d.path1)) + '">'
    + esc(_imgCmpSide('A', d.run1, d.name1)) + '</span>'
    + '<span title="' + esc(_imgCmpTitle(d.run2, d.path2)) + '">'
    + esc(_imgCmpSide('B', d.run2, d.name2)) + '</span>';
}

// The space one image gets in the current mode. Side-by-side splits the
// window between two panels; overlay and swipe stack them, so each gets the
// whole width. The vertical allowance matches the CSS max-heights, which
// leave room for the header and the nav rows.
function _imgCmpAvail() {
  const w = _imgCmpMode === 'side'
    ? Math.max(120, (window.innerWidth - 40) / 2)
    : window.innerWidth * 0.9;
  const h = window.innerHeight - (_imgCmpMode === 'side' ? 120 : 140);
  return [w, Math.max(120, h)];
}

// Small images must fill the overlay they were opened into, and both sides
// must take the SAME scale or an overlay/swipe comparison stops aligning.
function _fitCompareBody(body) {
  const [w, h] = _imgCmpAvail();
  fitModalImages(body.querySelectorAll('img'), w, h);
}

function renderCompareBody() {
  const body = document.getElementById('img-cmp-body');
  if (!body || !_imgCmpData) return;
  const d = _imgCmpData;

  if (_imgCmpMode === 'side') {
    body.innerHTML = '<div class="img-cmp-side">' +
      _imgCmpPanel('A', d.src1, d.name1, d.run1) +
      _imgCmpPanel('B', d.src2, d.name2, d.run2) +
      '</div>';
  } else if (_imgCmpMode === 'overlay') {
    // A tint adds the two images together, so the top one is drawn at full
    // strength: at 50% opacity the sum is half of each and every colour is
    // muddy. The slider belongs to the untinted fade and is replaced by the
    // legend when a tint is on.
    const tinted = _imgCmpTint !== 'none';
    body.innerHTML = _tintSvgDefs() + '<div class="img-cmp-stack'
      + (tinted ? ' is-tinted tint-' + _imgCmpTint : '') + '">' +
      '<img class="img-cmp-tint-a" src="' + d.src1 + '" alt="A">' +
      '<img class="img-cmp-tint-b" src="' + d.src2 + '" alt="B" id="img-cmp-top"'
      + ' style="opacity:' + (tinted ? '1' : '0.5') + '">' +
      '</div>' +
      '<div class="img-cmp-slider-wrap">' +
      '<span class="img-cmp-end" title="' + esc(_imgCmpTitle(d.run1, d.path1)) + '">'
      + esc(_imgCmpEnd('A', d.run1)) + '</span>' +
      (tinted ? ''
        : '<input type="range" min="0" max="100" value="50" oninput="document.getElementById(\'img-cmp-top\').style.opacity=this.value/100;document.getElementById(\'img-cmp-opacity-val\').textContent=this.value+\'%\'">') +
      '<span class="img-cmp-end" title="' + esc(_imgCmpTitle(d.run2, d.path2)) + '">'
      + esc(_imgCmpEnd('B', d.run2)) + '</span>'
      + (tinted ? '' : ' <span id="img-cmp-opacity-val" style="min-width:36px">50%</span>') +
      '</div>' + _tintBarHtml();
  } else if (_imgCmpMode === 'swipe') {
    _swipePct = 50;
    body.innerHTML = '<div class="img-cmp-swipe" id="img-cmp-swipe">' +
      '<img class="img-cmp-swipe-base" src="' + d.src1 + '" alt="A">' +
      '<img class="img-cmp-swipe-clip" src="' + d.src2 + '" alt="B" id="img-cmp-swipe-img" style="clip-path:inset(0 0 0 50%)">' +
      '<div class="img-cmp-divider" id="img-cmp-divider" style="left:50%"></div>' +
      '</div>' +
      '<div class="img-cmp-slider-wrap">'
      + '<span class="img-cmp-end" title="' + esc(_imgCmpTitle(d.run1, d.path1)) + '">'
      + esc(_imgCmpEnd('A', d.run1)) + '</span>'
      + '<span style="flex:1;text-align:center;font-size:11px;opacity:0.5">drag the handle or click to move</span>'
      + '<span class="img-cmp-end" title="' + esc(_imgCmpTitle(d.run2, d.path2)) + '">'
      + esc(_imgCmpEnd('B', d.run2)) + '</span></div>';

    requestAnimationFrame(function() {
      const swipe = document.getElementById('img-cmp-swipe');
      const divider = document.getElementById('img-cmp-divider');
      if (!swipe || !divider) return;

      function updateSwipe(clientX) {
        const rect = swipe.getBoundingClientRect();
        let pct = ((clientX - rect.left) / rect.width) * 100;
        pct = Math.max(0, Math.min(100, pct));
        _swipePct = pct;
        const img = document.getElementById('img-cmp-swipe-img');
        if (img) img.style.clipPath = 'inset(0 0 0 ' + pct + '%)';
        divider.style.left = pct + '%';
      }

      swipe.addEventListener('pointerdown', function(ev) {
        _swipeDragging = true;
        swipe.setPointerCapture(ev.pointerId);
        updateSwipe(ev.clientX);
      });
      swipe.addEventListener('pointermove', function(ev) {
        if (_swipeDragging) updateSwipe(ev.clientX);
      });
      swipe.addEventListener('pointerup', function() { _swipeDragging = false; });
      swipe.addEventListener('pointercancel', function() { _swipeDragging = false; });
    });
  }
  _fitCompareBody(body);
}

// ── Cross-run image comparison (in Compare view) ─────────────────────────────

let crossCmpA = null, crossCmpB = null;
// Each Compare column's images, in the order shown, so the modal can step.
let _crossImgLists = {1: [], 2: []};

function selectCrossImg(src, name, side, run) {
  if (side === 1) crossCmpA = {src, name, run: run || ''};
  else crossCmpB = {src, name, run: run || ''};
  // Update UI highlights
  document.querySelectorAll('.cmp-img-thumb[data-side="' + side + '"]').forEach(el => {
    el.classList.toggle('selected', el.dataset.src === src);
  });
  // Update bar
  const bar = document.getElementById('cross-cmp-bar');
  if (bar) {
    const aName = crossCmpA ? _imgCmpWho(crossCmpA.run, crossCmpA.name) : '(none)';
    const bName = crossCmpB ? _imgCmpWho(crossCmpB.run, crossCmpB.name) : '(none)';
    bar.querySelector('.cmp-sel-a').textContent = 'A: ' + aName;
    bar.querySelector('.cmp-sel-b').textContent = 'B: ' + bName;
    bar.querySelector('.cmp-compare-btn').disabled = !(crossCmpA && crossCmpB);
  }
}

function doCrossCompare() {
  if (crossCmpA && crossCmpB) {
    openCompareModal(crossCmpA.src, crossCmpA.name, crossCmpB.src, crossCmpB.name,
                     crossCmpA.run, crossCmpB.run,
                     {listA: _crossImgLists[1] || [], listB: _crossImgLists[2] || []});
  }
}

function clearCrossCompare() {
  crossCmpA = null; crossCmpB = null;
  document.querySelectorAll('.cmp-img-thumb.selected').forEach(el => el.classList.remove('selected'));
  const bar = document.getElementById('cross-cmp-bar');
  if (bar) {
    bar.querySelector('.cmp-sel-a').textContent = 'A: (none)';
    bar.querySelector('.cmp-sel-b').textContent = 'B: (none)';
    bar.querySelector('.cmp-compare-btn').disabled = true;
  }
}

// ── Intra-run image comparison (in Images tab) ───────────────────────────────

let imgCmpMode = false, imgCmpA = null, imgCmpB = null;
// The gallery behind the Images tab's own compare, and whose run it is.
let _intraImgList = [], _intraRunName = '';

function toggleImgCompare(expId) {
  imgCmpMode = !imgCmpMode;
  imgCmpA = null; imgCmpB = null;
  // Entering compare mode changes how the gallery is drawn, not what is in it.
  repaintImages(expId);
}

// `expId` is kept in the signature: the inline handlers in the gallery markup
// pass it, and it is what a future reload would need. Nothing here reloads.
function selectImgCompare(src, name, expId) {
  if (imgCmpA === null || (imgCmpA !== null && imgCmpB !== null)) {
    imgCmpA = {src, name};
    imgCmpB = null;
  } else {
    imgCmpB = {src, name};
  }
  _imgCmpRepaint();
}

function doIntraCompare() {
  if (!imgCmpA || !imgCmpB) return;
  // Both sides step through the same run's gallery — which is how you compare
  // sample 41 against sample 42 without leaving the modal.
  const list = _intraImgList;
  openCompareModal(imgCmpA.src, imgCmpA.name, imgCmpB.src, imgCmpB.name,
                   _intraRunName, _intraRunName, {listA: list, listB: list});
}

function clearIntraCompare(expId) {
  imgCmpA = null; imgCmpB = null;
  _imgCmpRepaint();
}
