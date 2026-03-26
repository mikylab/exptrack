"""CSS for image gallery, image modal, new experiment modal, filters, and image comparison."""

CSS_IMAGES = """
  .img-gallery-toolbar { display: flex; align-items: center; gap: 12px; margin-bottom: 12px; flex-wrap: wrap; }
  .img-filter-select { font-family: inherit; font-size: 12px; padding: 3px 8px; border: 1px solid var(--border); border-radius: 3px; background: var(--card-bg); color: var(--fg); }
  .img-gallery { display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 12px; }
  .img-card { border: 1px solid var(--border); border-radius: 6px; overflow: hidden; cursor: pointer; background: var(--card-bg); transition: box-shadow 0.15s, transform 0.15s; }
  .img-card:hover { box-shadow: 0 2px 8px rgba(0,0,0,0.15); transform: translateY(-1px); }
  .img-thumb { width: 100%; aspect-ratio: 1; overflow: hidden; background: var(--code-bg); display: flex; align-items: center; justify-content: center; }
  .img-thumb img { width: 100%; height: 100%; object-fit: cover; }
  .img-info { padding: 6px 8px; }
  .img-name { font-size: 11px; font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .img-dir { font-size: 10px; color: var(--blue); margin-top: 1px; }
  .img-meta { font-size: 10px; color: var(--muted); margin-top: 1px; }
  .img-modal-overlay { position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.85); z-index: 10000; display: flex; align-items: center; justify-content: center; }
  .img-modal-content { max-width: 95vw; max-height: 95vh; display: flex; flex-direction: column; align-items: center; }
  .img-modal-header { display: flex; justify-content: space-between; align-items: center; width: 100%; padding: 8px 12px; color: #fff; }
  .img-modal-name { font-size: 13px; }
  .img-modal-close { background: none; border: none; color: #fff; font-size: 24px; cursor: pointer; padding: 0 8px; }
  .img-paths-section { margin-bottom: 16px; }
  .img-path-row { display: flex; align-items: center; gap: 8px; padding: 4px 8px; border: 1px solid var(--border); border-radius: 3px; margin-bottom: 4px; background: var(--card-bg); }
  .img-path-val { flex: 1; font-size: 13px; cursor: pointer; }
  .img-path-val:hover { color: var(--blue); }
  .img-path-del { background: none; border: none; color: var(--red); font-size: 16px; cursor: pointer; padding: 0 4px; font-weight: bold; }
  .img-path-add { display: flex; gap: 8px; margin-top: 6px; }
  .img-path-add input { font-family: inherit; font-size: 13px; border: 1px solid var(--border); padding: 4px 8px; border-radius: 3px; background: var(--card-bg); color: var(--fg); flex: 1; }
  .img-path-add button { font-family: inherit; font-size: 12px; padding: 4px 12px; border: none; background: var(--blue); color: #fff; cursor: pointer; border-radius: 3px; }
  .study-chip { background: rgba(44,90,160,0.1); color: var(--blue); }
  .filter-dropdown-wrap { display: inline-block; position: relative; }
  .filter-search-input {
    font-family: inherit; font-size: 13px; border: 1px solid var(--border);
    padding: 6px 12px; border-radius: 4px; background: var(--card-bg); color: var(--fg);
    width: 220px; transition: border-color 0.15s;
  }
  .filter-search-input:focus { outline: none; border-color: var(--blue); }
  .filter-dropdown-list {
    position: absolute; top: 100%; left: 0; z-index: 50;
    background: var(--card-bg); border: 1px solid var(--border); border-radius: 4px;
    max-height: 240px; overflow-y: auto; min-width: 220px; box-shadow: 0 4px 12px rgba(0,0,0,0.15);
  }
  .filter-dropdown-item {
    padding: 6px 12px; cursor: pointer; font-size: 13px; display: flex; justify-content: space-between; align-items: center;
  }
  .filter-dropdown-item:hover, .filter-dropdown-item.active { background: var(--code-bg); color: var(--blue); }
  .manage-section { margin-bottom: 12px; }
  .manage-section h4 { font-size: 13px; margin-bottom: 6px; }
  .tm-name-edit { cursor: pointer; }
  .tm-name-edit:hover { color: var(--blue); }

  /* New experiment modal */
  .new-exp-overlay { position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.5); z-index: 10000; display: flex; align-items: center; justify-content: center; }
  .new-exp-dialog { background: var(--card-bg); border: 1px solid var(--border); border-radius: 6px; width: 520px; max-width: 95vw; max-height: 85vh; display: flex; flex-direction: column; }
  .new-exp-header { display: flex; justify-content: space-between; align-items: center; padding: 12px 16px; border-bottom: 1px solid var(--border); }
  .new-exp-header h3 { margin: 0; font-size: 15px; font-weight: 600; }
  .new-exp-body { padding: 16px; overflow-y: auto; flex: 1; }
  .new-exp-footer { padding: 12px 16px; border-top: 1px solid var(--border); display: flex; justify-content: flex-end; gap: 8px; }
  .new-exp-field { margin-bottom: 10px; }
  .new-exp-field label { display: block; font-size: 12px; font-weight: 500; color: var(--muted); margin-bottom: 3px; }
  .new-exp-field input, .new-exp-field textarea, .new-exp-field select {
    font-family: inherit; font-size: 13px; padding: 6px 8px;
    border: 1px solid var(--border); border-radius: 4px;
    background: var(--card-bg); color: var(--fg); width: 100%;
  }
  .new-exp-field input:focus, .new-exp-field textarea:focus, .new-exp-field select:focus { outline: none; border-color: var(--blue); }
  .new-exp-field textarea { resize: vertical; }
  .new-exp-row { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
  .new-exp-kv { display: flex; gap: 4px; margin-bottom: 4px; align-items: center; }
  .new-exp-kv input {
    flex: 1; font-family: inherit; font-size: 12px; padding: 4px 6px;
    border: 1px solid var(--border); border-radius: 3px;
    background: var(--card-bg); color: var(--fg);
  }
  .new-exp-kv input:focus { outline: none; border-color: var(--blue); }
  .new-exp-kv-del { background: none; border: none; color: var(--muted); font-size: 14px; cursor: pointer; padding: 0 4px; line-height: 1; }
  .new-exp-kv-del:hover { color: var(--red); }
  .new-exp-kv-add { font-family: inherit; font-size: 12px; color: var(--blue); cursor: pointer; background: none; border: none; padding: 2px 0; }
  .new-exp-kv-add:hover { text-decoration: underline; }
"""


CSS_IMAGE_COMPARE = """
  .img-cmp-overlay {
    position: fixed; top: 0; left: 0; right: 0; bottom: 0;
    background: rgba(0,0,0,0.92); z-index: 10000;
    display: flex; flex-direction: column;
  }
  .img-cmp-header {
    display: flex; justify-content: space-between; align-items: center;
    padding: 10px 20px; color: #fff; flex-shrink: 0;
  }
  .img-cmp-names { display: flex; gap: 24px; font-size: 13px; flex: 1; }
  .img-cmp-names span { opacity: 0.8; }
  .img-cmp-modes { display: flex; gap: 4px; }
  .img-cmp-modes button {
    font-family: inherit; font-size: 12px; padding: 5px 14px;
    border: 1px solid rgba(255,255,255,0.3); background: transparent;
    color: #fff; cursor: pointer; border-radius: 3px;
  }
  .img-cmp-modes button:hover { background: rgba(255,255,255,0.1); }
  .img-cmp-modes button.active { background: var(--blue); border-color: var(--blue); }
  .img-cmp-close {
    background: none; border: none; color: #fff; font-size: 28px;
    cursor: pointer; padding: 0 8px; margin-left: 16px;
  }
  .img-cmp-body { flex: 1; display: flex; align-items: center; justify-content: center; overflow: hidden; padding: 10px; }
  .img-cmp-side { display: flex; gap: 16px; width: 100%; height: 100%; align-items: center; justify-content: center; }
  .img-cmp-side .img-cmp-panel { flex: 1; display: flex; flex-direction: column; align-items: center; max-height: 100%; }
  .img-cmp-side .img-cmp-panel img { max-width: 100%; max-height: calc(100vh - 120px); object-fit: contain; }
  .img-cmp-side .img-cmp-label { color: rgba(255,255,255,0.6); font-size: 11px; margin-top: 6px; }
  .img-cmp-stack { position: relative; display: flex; align-items: center; justify-content: center; width: 100%; height: 100%; }
  .img-cmp-stack img { position: absolute; max-width: 90vw; max-height: calc(100vh - 140px); object-fit: contain; }
  .img-cmp-stack img:first-child { z-index: 1; }
  .img-cmp-stack img:last-child { z-index: 2; }
  .img-cmp-slider-wrap {
    position: absolute; bottom: 20px; left: 50%; transform: translateX(-50%);
    z-index: 10; display: flex; align-items: center; gap: 10px; color: #fff; font-size: 12px;
  }
  .img-cmp-slider-wrap input[type=range] { width: 200px; accent-color: var(--blue); }
  .img-cmp-swipe { position: relative; display: flex; align-items: center; justify-content: center; width: 100%; height: 100%; cursor: ew-resize; overflow: hidden; }
  .img-cmp-swipe img { position: absolute; max-width: 90vw; max-height: calc(100vh - 140px); object-fit: contain; }
  .img-cmp-swipe .img-cmp-swipe-clip { z-index: 2; }
  .img-cmp-swipe .img-cmp-swipe-base { z-index: 1; }
  .img-cmp-divider {
    position: absolute; top: 0; bottom: 0; width: 3px; background: #fff;
    z-index: 3; cursor: ew-resize; box-shadow: 0 0 6px rgba(0,0,0,0.5);
  }
  .img-cmp-divider::after {
    content: ''; position: absolute; top: 50%; left: 50%; transform: translate(-50%,-50%);
    width: 24px; height: 24px; border-radius: 50%; background: #fff;
    box-shadow: 0 0 4px rgba(0,0,0,0.4);
  }
  .compare-images-section { margin-top: 16px; }
  .compare-images-cols { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
  .compare-images-col h4 { font-size: 13px; margin-bottom: 8px; color: var(--muted); }
  .compare-images-col .cmp-img-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(100px, 1fr)); gap: 8px; max-height: 360px; overflow-y: auto; padding: 4px; }
  .cmp-img-thumb {
    border: 2px solid var(--border); border-radius: 4px; overflow: hidden;
    cursor: pointer; aspect-ratio: 1; position: relative;
    transition: border-color 0.15s, box-shadow 0.15s;
  }
  .cmp-img-thumb:hover { border-color: var(--blue); box-shadow: 0 0 0 1px var(--blue); }
  .cmp-img-thumb.selected { border-color: var(--blue); box-shadow: 0 0 0 2px var(--blue); }
  .cmp-img-thumb img { width: 100%; height: 100%; object-fit: cover; }
  .cmp-img-thumb .cmp-badge {
    position: absolute; top: 4px; left: 4px; background: var(--blue); color: #fff;
    font-size: 10px; font-weight: 700; width: 18px; height: 18px;
    border-radius: 50%; display: flex; align-items: center; justify-content: center;
  }
  .cmp-img-thumb .cmp-thumb-name {
    position: absolute; bottom: 0; left: 0; right: 0; background: rgba(0,0,0,0.6);
    color: #fff; font-size: 9px; padding: 2px 4px; overflow: hidden;
    text-overflow: ellipsis; white-space: nowrap;
  }
  .compare-select-bar {
    display: flex; align-items: center; gap: 12px; padding: 10px 14px;
    background: var(--code-bg); border: 1px solid var(--border); border-radius: 4px;
    margin-top: 12px; font-size: 13px;
  }
  .compare-select-bar button {
    font-family: inherit; font-size: 13px; padding: 6px 16px;
    border: none; cursor: pointer; border-radius: 4px;
  }
  .compare-select-bar .cmp-compare-btn { background: var(--blue); color: #fff; }
  .compare-select-bar .cmp-compare-btn:disabled { opacity: 0.4; cursor: default; }
  .compare-select-bar .cmp-clear-btn { background: var(--code-bg); border: 1px solid var(--border); color: var(--muted); }
  .img-compare-toggle {
    font-family: inherit; font-size: 12px; padding: 3px 10px;
    border: 1px solid var(--border); border-radius: 3px;
    background: var(--card-bg); color: var(--fg); cursor: pointer;
  }
  .img-compare-toggle:hover { border-color: var(--blue); color: var(--blue); }
  .img-compare-toggle.active { background: var(--blue); color: #fff; border-color: var(--blue); }
  .img-card.compare-sel { outline: 3px solid var(--blue); outline-offset: -3px; }
  .img-card .img-cmp-badge {
    position: absolute; top: 6px; left: 6px; background: var(--blue); color: #fff;
    font-size: 11px; font-weight: 700; width: 22px; height: 22px;
    border-radius: 50%; display: flex; align-items: center; justify-content: center;
    z-index: 2;
  }
  .img-cmp-floating-bar {
    display: flex; align-items: center; gap: 10px; padding: 10px 14px;
    background: var(--code-bg); border: 1px solid var(--blue); border-radius: 4px;
    margin-bottom: 12px; font-size: 13px;
  }
  .img-cmp-floating-bar button {
    font-family: inherit; font-size: 12px; padding: 5px 14px;
    border: none; cursor: pointer; border-radius: 3px;
  }
  .img-cmp-floating-bar .cmp-go { background: var(--blue); color: #fff; }
  .img-cmp-floating-bar .cmp-go:disabled { opacity: 0.4; cursor: default; }
  .img-cmp-floating-bar .cmp-clr { background: var(--card-bg); border: 1px solid var(--border); color: var(--muted); }
"""
