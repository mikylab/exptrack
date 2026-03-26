"""Image diff viewer with slider overlay and comparison modes."""

JS_IMAGE_COMPARE = r"""

// ── Image Comparison Modal ───────────────────────────────────────────────────

let _imgCmpMode = 'side';
let _imgCmpData = null;
let _swipePct = 50;
let _swipeDragging = false;

function openCompareModal(src1, name1, src2, name2) {
  _imgCmpData = {src1, name1, src2, name2};
  _imgCmpMode = 'side';
  const overlay = document.createElement('div');
  overlay.className = 'img-cmp-overlay';
  overlay.id = 'img-cmp-overlay';

  let html = '<div class="img-cmp-header">';
  html += '<div class="img-cmp-names"><span>A: ' + esc(name1) + '</span><span>B: ' + esc(name2) + '</span></div>';
  html += '<div class="img-cmp-modes">';
  html += '<button class="active" onclick="setCompareMode(\'side\',this)">Side by Side</button>';
  html += '<button onclick="setCompareMode(\'overlay\',this)">Overlay</button>';
  html += '<button onclick="setCompareMode(\'swipe\',this)">Swipe</button>';
  html += '</div>';
  html += '<button class="img-cmp-close" onclick="closeCompareModal()">&times;</button>';
  html += '</div>';
  html += '<div class="img-cmp-body" id="img-cmp-body"></div>';
  overlay.innerHTML = html;

  overlay.addEventListener('click', function(ev) { if (ev.target === overlay) closeCompareModal(); });
  document.body.appendChild(overlay);

  const escHandler = function(ev) { if (ev.key === 'Escape') { closeCompareModal(); document.removeEventListener('keydown', escHandler); } };
  document.addEventListener('keydown', escHandler);
  overlay.__escHandler = escHandler;

  renderCompareBody();
}

function closeCompareModal() {
  const el = document.getElementById('img-cmp-overlay');
  if (el) {
    if (el.__escHandler) document.removeEventListener('keydown', el.__escHandler);
    el.remove();
  }
  _imgCmpData = null;
  _swipeDragging = false;
}

function setCompareMode(mode, btn) {
  _imgCmpMode = mode;
  if (btn) {
    btn.parentElement.querySelectorAll('button').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
  }
  renderCompareBody();
}

function renderCompareBody() {
  const body = document.getElementById('img-cmp-body');
  if (!body || !_imgCmpData) return;
  const d = _imgCmpData;

  if (_imgCmpMode === 'side') {
    body.innerHTML = '<div class="img-cmp-side">' +
      '<div class="img-cmp-panel"><img src="' + d.src1 + '" alt="A"><div class="img-cmp-label">' + esc(d.name1) + '</div></div>' +
      '<div class="img-cmp-panel"><img src="' + d.src2 + '" alt="B"><div class="img-cmp-label">' + esc(d.name2) + '</div></div>' +
      '</div>';
  } else if (_imgCmpMode === 'overlay') {
    body.innerHTML = '<div class="img-cmp-stack">' +
      '<img src="' + d.src1 + '" alt="A">' +
      '<img src="' + d.src2 + '" alt="B" id="img-cmp-top" style="opacity:0.5">' +
      '</div>' +
      '<div class="img-cmp-slider-wrap">' +
      '<span>A</span>' +
      '<input type="range" min="0" max="100" value="50" oninput="document.getElementById(\'img-cmp-top\').style.opacity=this.value/100;document.getElementById(\'img-cmp-opacity-val\').textContent=this.value+\'%\'">' +
      '<span>B</span> <span id="img-cmp-opacity-val" style="min-width:36px">50%</span>' +
      '</div>';
  } else if (_imgCmpMode === 'swipe') {
    _swipePct = 50;
    body.innerHTML = '<div class="img-cmp-swipe" id="img-cmp-swipe">' +
      '<img class="img-cmp-swipe-base" src="' + d.src1 + '" alt="A">' +
      '<img class="img-cmp-swipe-clip" src="' + d.src2 + '" alt="B" id="img-cmp-swipe-img" style="clip-path:inset(0 0 0 50%)">' +
      '<div class="img-cmp-divider" id="img-cmp-divider" style="left:50%"></div>' +
      '</div>' +
      '<div class="img-cmp-slider-wrap"><span>A</span><span style="flex:1;text-align:center;font-size:11px;opacity:0.5">drag the handle or click to move</span><span>B</span></div>';

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
}

// ── Cross-run image comparison (in Compare view) ─────────────────────────────

let crossCmpA = null, crossCmpB = null;

function selectCrossImg(src, name, side) {
  if (side === 1) crossCmpA = {src, name};
  else crossCmpB = {src, name};
  // Update UI highlights
  document.querySelectorAll('.cmp-img-thumb[data-side="' + side + '"]').forEach(el => {
    el.classList.toggle('selected', el.dataset.src === src);
  });
  // Update bar
  const bar = document.getElementById('cross-cmp-bar');
  if (bar) {
    const aName = crossCmpA ? crossCmpA.name : '(none)';
    const bName = crossCmpB ? crossCmpB.name : '(none)';
    bar.querySelector('.cmp-sel-a').textContent = 'A: ' + aName;
    bar.querySelector('.cmp-sel-b').textContent = 'B: ' + bName;
    bar.querySelector('.cmp-compare-btn').disabled = !(crossCmpA && crossCmpB);
  }
}

function doCrossCompare() {
  if (crossCmpA && crossCmpB) openCompareModal(crossCmpA.src, crossCmpA.name, crossCmpB.src, crossCmpB.name);
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

function toggleImgCompare(expId) {
  imgCmpMode = !imgCmpMode;
  imgCmpA = null; imgCmpB = null;
  loadImages(expId);
}

function selectImgCompare(src, name, expId) {
  if (imgCmpA === null || (imgCmpA !== null && imgCmpB !== null)) {
    imgCmpA = {src, name};
    imgCmpB = null;
  } else {
    imgCmpB = {src, name};
  }
  loadImages(expId);
}

function doIntraCompare() {
  if (imgCmpA && imgCmpB) openCompareModal(imgCmpA.src, imgCmpA.name, imgCmpB.src, imgCmpB.name);
}

function clearIntraCompare(expId) {
  imgCmpA = null; imgCmpB = null;
  loadImages(expId);
}
"""
