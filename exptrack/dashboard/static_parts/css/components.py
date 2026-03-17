"""CSS for UI components: tabs, help, export, tags, inline editing, owl mascot, and more."""

CSS_COMPONENTS = """
  .help-btn {
    font-family: inherit; font-size: 13px; background: var(--code-bg);
    border: 1px solid var(--border); padding: 6px 12px; cursor: pointer;
    border-radius: 4px; color: var(--muted);
  }
  .help-btn:hover { background: var(--border); color: var(--fg); }
  .theme-btn { font-family: inherit; font-size: 18px; background: var(--code-bg); border: 1px solid var(--border); padding: 5px 12px; cursor: pointer; border-radius: 4px; color: var(--muted); line-height: 1; }
  .theme-btn:hover { background: var(--border); color: var(--fg); }
  .tabs { display: flex; gap: 0; margin-bottom: 20px; border-bottom: 2px solid var(--border); }
  .tab {
    font-family: inherit; font-size: 14px;
    background: none; border: none; padding: 11px 22px;
    cursor: pointer; text-transform: uppercase; letter-spacing: 1px;
    border-bottom: 2px solid transparent; margin-bottom: -2px;
  }
  .tab:hover { background: var(--code-bg); }
  .tab.active { border-bottom-color: var(--fg); font-weight: 600; }
  #view { min-height: 200px; }
  .inline-form { display: inline-flex; gap: 6px; align-items: center; margin-left: 8px; }
  .inline-form input {
    font-family: inherit; font-size: 14px; border: 1px solid var(--border);
    padding: 5px 10px; border-radius: 4px; background: var(--card-bg);
  }
  .inline-form button {
    font-family: inherit; font-size: 13px; padding: 5px 12px;
    border: 1px solid var(--border); background: var(--code-bg);
    cursor: pointer; border-radius: 4px;
  }
  .inline-form button:hover { background: var(--border); }
  .notes-display { white-space: pre-wrap; background: var(--code-bg); padding: 12px; border-radius: 4px; margin: 4px 0; font-size: 14px; position: relative; }
  .notes-edit-btn { position: absolute; top: 6px; right: 6px; font-size: 12px; cursor: pointer; color: var(--muted); background: var(--card-bg); border: 1px solid var(--border); padding: 3px 8px; border-radius: 3px; }
  .notes-edit-btn:hover { color: var(--blue); border-color: var(--blue); }
  .notes-edit-area { width: 100%; font-family: inherit; font-size: 14px; border: 1px solid var(--blue); padding: 10px; border-radius: 4px; background: var(--card-bg); min-height: 90px; resize: vertical; }
  .tag-list { display: flex; gap: 6px; flex-wrap: wrap; align-items: center; }
  .tag-removable { background: var(--code-bg); padding: 5px 12px; font-size: 14px; border-radius: 4px; display: inline-flex; align-items: center; gap: 5px; cursor: default; }
  .tag-removable .tag-delete { cursor: pointer; color: var(--muted); font-size: 16px; margin-left: 4px; line-height: 1; opacity: 0.6; }
  .tag-removable:hover .tag-delete { opacity: 1; color: var(--red, #e55); }
  .tag-removable .tag-delete:hover { opacity: 1; color: var(--red, #e55); }
  .result-del-x { cursor: pointer; color: var(--muted); font-size: 16px; line-height: 1; opacity: 0; padding: 0 4px; }
  tr:hover .result-del-x { opacity: 0.6; }
  .result-del-x:hover { opacity: 1 !important; color: var(--red, #e55); }
  .tag-removable .tag-edit { cursor: pointer; color: var(--muted); font-size: 12px; }
  .tag-removable .tag-edit:hover { color: var(--blue); }
  .manage-tags-link {
    font-family: inherit; font-size: 13px; padding: 7px 16px;
    border: 1px solid var(--border); background: var(--card-bg); cursor: pointer;
    color: var(--fg); white-space: nowrap; border-radius: 0 4px 4px 0;
    transition: background 0.15s, border-color 0.15s; margin-left: -1px;
  }
  .manage-tags-link:hover { background: var(--code-bg); border-color: var(--blue); color: var(--blue); text-decoration: none; }
  .manage-drawer-overlay {
    position: fixed; top: 0; left: 0; right: 0; bottom: 0;
    background: rgba(0,0,0,0.3); z-index: 999;
    opacity: 0; pointer-events: none; transition: opacity 0.2s;
  }
  .manage-drawer-overlay.visible { opacity: 1; pointer-events: auto; }
  .manage-drawer {
    position: fixed; top: 0; right: -360px; bottom: 0; width: 340px;
    background: var(--card-bg); border-left: 1px solid var(--border);
    box-shadow: -4px 0 20px rgba(0,0,0,0.12); z-index: 1000;
    display: flex; flex-direction: column;
    transition: right 0.25s ease;
  }
  .manage-drawer.visible { right: 0; }
  .manage-drawer-header {
    display: flex; justify-content: space-between; align-items: center;
    padding: 16px 20px; border-bottom: 1px solid var(--border); flex-shrink: 0;
  }
  .manage-drawer-header h3 { font-size: 15px; font-weight: 600; margin: 0; }
  .manage-drawer-close {
    background: none; border: none; font-size: 20px; cursor: pointer;
    color: var(--muted); padding: 4px 8px; border-radius: 3px; font-family: inherit;
  }
  .manage-drawer-close:hover { background: var(--code-bg); color: var(--fg); }
  .manage-drawer-body { flex: 1; overflow-y: auto; padding: 16px 20px; }
  .manage-section { margin-bottom: 20px; }
  .manage-section h4 {
    font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 1px;
    color: var(--muted); margin-bottom: 8px; padding-bottom: 6px; border-bottom: 1px solid var(--border);
  }
  .tag-manager-row {
    display: flex; align-items: center; justify-content: space-between;
    padding: 8px 10px; border-radius: 3px; margin-bottom: 2px;
    transition: background 0.1s;
  }
  .tag-manager-row:hover { background: var(--code-bg); }
  .tag-manager-row .tm-name { color: var(--blue); }
  .tag-manager-row .tm-count { color: var(--muted); font-size: 13px; margin-left: 8px; }
  .tag-manager-row .tm-delete {
    cursor: pointer; color: var(--muted); font-size: 14px; padding: 2px 6px;
    border-radius: 3px; opacity: 0; transition: opacity 0.1s;
  }
  .tag-manager-row:hover .tm-delete { opacity: 1; }
  .tag-manager-row .tm-delete:hover { color: var(--red); background: rgba(192,57,43,0.1); }
  .artifact-row { display: flex; align-items: center; gap: 8px; }
  .artifact-type-badge { font-size: 11px; padding: 1px 6px; border-radius: 3px; background: var(--code-bg); color: var(--muted); }
  .artifact-type-badge.img { background: #d4edda; color: #155724; }
  .artifact-type-badge.model { background: #cce5ff; color: #004085; }
  .artifact-type-badge.data { background: #fff3cd; color: #856404; }
  .artifact-type-badge.log { background: #e2e3e5; color: #383d41; }
  .artifact-type-badge.dir { background: #d1ecf1; color: #0c5460; }
  .artifact-add-form { display: flex; gap: 8px; align-items: center; margin-top: 10px; flex-wrap: wrap; }
  .artifact-add-form input { font-family: inherit; font-size: 14px; border: 1px solid var(--border); padding: 6px 10px; border-radius: 4px; background: var(--card-bg); }
  .artifact-add-form button { font-family: inherit; font-size: 13px; padding: 6px 14px; border: 1px solid var(--border); background: var(--code-bg); cursor: pointer; border-radius: 4px; }
  .artifact-actions { display: flex; gap: 4px; }
  .artifact-actions button { font-family: inherit; font-size: 12px; padding: 3px 8px; border: 1px solid var(--border); background: var(--card-bg); cursor: pointer; border-radius: 3px; color: var(--muted); }
  .artifact-actions button:hover { color: var(--fg); border-color: var(--fg); }
  .artifact-actions button.art-del:hover { color: var(--red); border-color: var(--red); }
  .home-btn { font-family: inherit; font-size: 13px; background: var(--code-bg); border: 1px solid var(--border); padding: 6px 14px; cursor: pointer; border-radius: 4px; color: var(--muted); }
  .home-btn:hover { background: var(--border); color: var(--fg); }
  .help-panel { display: none; background: var(--card-bg); border: 1px solid var(--border); padding: 24px; border-radius: 4px; margin-bottom: 20px; }
  .help-panel.visible { display: block; }
  .help-panel h3 { font-size: 15px; margin: 16px 0 8px; }
  .help-panel h3:first-child { margin-top: 0; }
  .help-panel p { color: var(--muted); font-size: 13px; margin-bottom: 8px; line-height: 1.5; }
  .help-panel .help-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin: 12px 0; }
  .help-panel .help-item { background: var(--code-bg); padding: 12px; border-radius: 4px; }
  .help-panel .help-item strong { display: block; margin-bottom: 4px; font-size: 13px; }
  .help-panel .help-item span { font-size: 12px; color: var(--muted); }
  .help-close { float: right; cursor: pointer; font-size: 18px; background: none; border: none; font-family: inherit; color: var(--muted); }
  .help-close:hover { color: var(--fg); }
  .faq-list { margin: 12px 0; }
  .faq-item { border: 1px solid var(--border); border-radius: 4px; margin-bottom: 6px; overflow: hidden; }
  .faq-q {
    font-size: 13px; font-weight: 600; padding: 10px 14px; cursor: pointer;
    background: var(--code-bg); user-select: none; position: relative; padding-right: 30px;
  }
  .faq-q:hover { background: var(--border); }
  .faq-q::after { content: '+'; position: absolute; right: 12px; top: 50%; transform: translateY(-50%); font-size: 16px; color: var(--muted); font-weight: 400; }
  .faq-item.open .faq-q::after { content: '\2212'; }
  .faq-a { display: none; padding: 10px 14px; font-size: 12px; color: var(--muted); line-height: 1.5; border-top: 1px solid var(--border); }
  .faq-item.open .faq-a { display: block; }
  .faq-a code { background: var(--code-bg); padding: 1px 5px; border-radius: 3px; font-size: 11px; }
  .export-panel { background: var(--card-bg); border: 1px solid var(--border); padding: 16px; border-radius: 6px; margin-top: 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.15); position: relative; z-index: 10; }
  .export-panel pre { white-space: pre-wrap; font-size: 12px; max-height: 400px; overflow-y: auto; background: var(--code-bg); padding: 12px; border-radius: 4px; border: 1px solid var(--border); }
  .export-panel .export-actions { display: flex; gap: 8px; margin-bottom: 12px; flex-wrap: wrap; }
  .export-panel .export-actions .action-btn.active-fmt { background: var(--blue); color: #fff; border-color: var(--blue); }
  .export-dropdown-menu { position: absolute; bottom: 100%; left: 0; background: var(--card-bg); border: 1px solid var(--border); border-radius: 6px; padding: 4px; z-index: 100; min-width: 130px; box-shadow: 0 4px 12px rgba(0,0,0,0.15); flex-direction: column; }
  .detail-actions .export-dropdown-menu { bottom: auto; top: 100%; right: 0; left: auto; }
  .export-dropdown-menu button { display: block; width: 100%; text-align: left; margin: 2px 0; }
  .tooltip { position: relative; display: inline-block; }
  .tooltip .tooltip-text {
    visibility: hidden; background: var(--fg); color: var(--bg);
    text-align: center; border-radius: 3px; padding: 5px 10px;
    position: absolute; z-index: 1; bottom: 125%; left: 50%;
    transform: translateX(-50%); font-size: 11px; white-space: nowrap;
  }
  .tooltip:hover .tooltip-text { visibility: visible; }
  .bulk-bar { display: flex; gap: 8px; align-items: center; padding: 8px 16px; background: var(--code-bg); border: 1px solid var(--border); border-radius: 4px; margin-bottom: 12px; }
  .bulk-bar .bulk-count { font-weight: 600; }
  .bulk-bar button { font-family: inherit; font-size: 13px; border: 1px solid var(--border); padding: 6px 14px; cursor: pointer; border-radius: 4px; background: var(--card-bg); }
  .bulk-bar button.danger { color: var(--red); border-color: var(--red); }
  .bulk-bar button.danger:hover { background: var(--red); color: #fff; }
  .section-toggle {
    cursor: pointer; user-select: none; display: flex; align-items: center; gap: 8px;
    padding: 6px 0; border-radius: 3px;
  }
  .section-toggle:hover { color: var(--blue); }
  .section-toggle::before {
    content: '\\25BC'; font-size: 10px; transition: transform 0.15s; display: inline-block; width: 14px; text-align: center;
  }
  .section-toggle.collapsed::before { transform: rotate(-90deg); }
  .section-body { transition: max-height 0.2s ease; }
  .section-toggle.collapsed + .section-body { display: none; }
  .metric-group-header { cursor: pointer; font-size: 13px; font-weight: 600; color: var(--muted); text-transform: uppercase; letter-spacing: 0.5px; margin: 10px 0 4px; user-select: none; }
  .metric-group-header::before { content: '\\25BC'; font-size: 9px; display: inline-block; width: 12px; text-align: center; transition: transform 0.15s; margin-right: 2px; }
  .metric-group.collapsed .metric-group-header::before { transform: rotate(-90deg); }
  .metric-group.collapsed .metrics-table { display: none; }
  .editable-cell { cursor: default; padding: 5px 8px; border-radius: 3px; position: relative; min-height: 32px; }
  .editable-cell:hover { background: rgba(44,90,160,0.08); }
  .edit-icon { display: none; font-size: 11px; color: var(--muted); margin-left: 4px; vertical-align: middle; }
  .editable-cell:hover .edit-icon { display: inline; }
  .col-resizer {
    position: absolute; right: -3px; top: 0; width: 7px; height: 100%;
    cursor: col-resize; z-index: 2;
    border-right: 2px solid var(--border);
  }
  .col-resizer:hover, .col-resizer:active { border-right-color: var(--blue); background: rgba(44,90,160,0.10); }
  .col-settings-bar { display: flex; justify-content: flex-end; margin-bottom: 4px; position: relative; }
  .col-settings-btn {
    font-family: inherit; font-size: 13px; background: var(--code-bg); border: 1px solid var(--border);
    padding: 6px 12px; cursor: pointer; border-radius: 4px; color: var(--muted);
  }
  .col-settings-btn:hover { color: var(--fg); border-color: var(--fg); }
  .col-settings-panel {
    display: none; position: absolute; top: 100%; right: 0; z-index: 50;
    background: var(--card-bg); border: 1px solid var(--border); border-radius: 6px;
    padding: 8px 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.15); min-width: 160px;
  }
  .col-settings-list { display: flex; flex-direction: column; gap: 4px; }
  .col-setting-item { display: flex; align-items: center; gap: 8px; font-size: 13px; cursor: pointer; padding: 4px 0; }
  .col-setting-item:hover { color: var(--blue); }
  .col-setting-item input { cursor: pointer; accent-color: var(--blue); }
  .col-reset-btn {
    font-family: inherit; font-size: 12px; width: 100%; padding: 5px 10px;
    border: 1px solid var(--border); background: var(--code-bg); cursor: pointer;
    border-radius: 3px; color: var(--muted);
  }
  .col-reset-btn:hover { background: var(--border); color: var(--fg); }
  .table-scroll-wrap { overflow-x: auto; overflow-y: visible; max-width: 100%; }
  #exp-table { table-layout: fixed; width: 100%; }
  #exp-table th { position: relative; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  #exp-table td { max-width: 0; }
  #exp-table td.truncate-cell { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  #exp-table td.wrap-cell { overflow: visible; white-space: normal; word-break: break-word; }
  #exp-table td.wrap-cell .tag { display: inline-block; margin-bottom: 2px; }
  .name-edit-input { font-family: inherit; font-size: 14px; border: 1px solid var(--blue); padding: 5px 8px; border-radius: 4px; background: var(--card-bg); width: 100%; max-width: 300px; }
  .notes-cell { max-width: 150px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 12px; color: var(--muted); }
  .tags-cell .tag { font-size: 13px; padding: 3px 8px; }
  .hidden-panel { display: none; margin-bottom: 10px; border: 1px solid var(--border); border-radius: 4px; background: var(--card-bg); font-size: 13px; }
  .hidden-panel-header { display: flex; align-items: center; gap: 8px; padding: 8px 12px; cursor: pointer; color: var(--muted); user-select: none; }
  .hidden-panel-header:hover { background: var(--code-bg); }
  .hidden-panel-toggle { font-size: 10px; }
  .hidden-panel-clear { margin-left: auto; font-family: inherit; font-size: 12px; background: var(--code-bg); border: 1px solid var(--border); padding: 3px 10px; cursor: pointer; border-radius: 3px; color: var(--muted); }
  .hidden-panel-clear:hover { background: var(--border); color: var(--fg); }
  .hidden-panel-list { border-top: 1px solid var(--border); max-height: 200px; overflow-y: auto; }
  .hidden-panel-item { display: flex; align-items: center; gap: 10px; padding: 6px 12px; border-bottom: 1px solid var(--border); }
  .hidden-panel-item:last-child { border-bottom: none; }
  .hidden-panel-name { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .hidden-panel-status { font-size: 12px; color: var(--muted); }
  .hidden-panel-unhide { font-family: inherit; font-size: 12px; background: var(--code-bg); border: 1px solid var(--border); padding: 3px 10px; cursor: pointer; border-radius: 3px; color: var(--blue); }
  .hidden-panel-unhide:hover { background: var(--blue); color: #fff; border-color: var(--blue); }
  .pin-btn { cursor: pointer; font-size: 14px; background: none; border: none; color: var(--muted); padding: 0; width: 100%; text-align: center; }
  .pin-btn:hover { color: var(--yellow); }
  .pin-btn.pinned { color: var(--yellow); }
  .pinned-row { background: rgba(184,134,11,0.05); }
  .pinned-row:hover { background: rgba(184,134,11,0.1); }
  #exp-body tr { cursor: pointer; }
  #exp-body tr:hover { background: var(--code-bg); }
  .tag-filter-bar { display: inline-flex; gap: 4px; flex-wrap: wrap; align-items: center; }
  .tag-filter-bar .tag-chip {
    font-family: inherit; font-size: 13px; background: var(--card-bg); border: 1px solid var(--border);
    padding: 5px 12px; cursor: pointer; border-radius: 3px; color: var(--muted);
    transition: background 0.15s, border-color 0.15s;
  }
  .tag-filter-bar .tag-chip:hover { background: var(--code-bg); border-color: var(--blue); color: var(--blue); }
  .tag-filter-bar .tag-chip.active { background: var(--blue); color: #fff; border-color: var(--blue); }
  .tag-delete-x { position:absolute; right:3px; top:50%; transform:translateY(-50%); font-size:12px; opacity:0; cursor:pointer; color:var(--red,#e55); line-height:1; }
  .tag-chip:hover .tag-delete-x { opacity:0.7; }
  .tag-delete-x:hover { opacity:1 !important; }
  .group-bar { display: flex; gap: 4px; align-items: center; margin-bottom: 10px; font-size: 12px; color: var(--muted); }
  .group-bar button { font-family: inherit; font-size: 12px; background: var(--code-bg); border: 1px solid var(--border); padding: 4px 10px; cursor: pointer; border-radius: 3px; color: var(--muted); }
  .group-bar button:hover { background: var(--border); color: var(--fg); }
  .group-bar button.active { background: var(--fg); color: var(--bg); }
  .group-header td { background: var(--code-bg); font-size: 12px; font-weight: 600; padding: 8px 16px; cursor: pointer; user-select: none; border-bottom: 2px solid var(--border); }
  .group-header td:hover { background: var(--border); }
  .group-header .group-label { color: var(--fg); }
  .group-header .group-meta { color: var(--muted); font-weight: 400; margin-left: 8px; }
  .group-header .group-toggle { float: right; color: var(--muted); font-size: 10px; }
  .code-stat { font-size: 11px; color: var(--muted); }
  .code-stat .lines-added { color: var(--green); }
  .code-stat .lines-removed { color: var(--red); }
  .notes-cell-expanded { max-width: 250px; font-size: 12px; color: var(--muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  #detail-name { cursor: default; padding: 2px 6px; border-radius: 3px; }
  #detail-name:hover { background: rgba(44,90,160,0.08); }
  .tag-autocomplete { position: relative; display: inline-block; }
  .tag-autocomplete-list {
    position: absolute; top: 100%; left: 0; z-index: 50;
    background: var(--card-bg); border: 1px solid var(--border); border-radius: 4px;
    max-height: 180px; overflow-y: auto; min-width: 160px; box-shadow: 0 4px 12px rgba(0,0,0,0.15);
  }
  .tag-autocomplete-item {
    padding: 6px 12px; cursor: pointer; font-size: 13px; display: flex; justify-content: space-between;
  }
  .tag-autocomplete-item:hover, .tag-autocomplete-item.active { background: var(--code-bg); color: var(--blue); }
  .tag-autocomplete-item .tag-count { color: var(--muted); font-size: 11px; }
  .tag-autocomplete-new { color: var(--green); font-style: italic; }
  .editable-hint { border-bottom: 1px dashed transparent; transition: border-color 0.15s; }
  .editable-hint:hover { border-bottom-color: var(--blue); }
  .detail-tags-inline { display: flex; gap: 6px; flex-wrap: wrap; align-items: center; }
  .detail-tags-inline .tag-input-area { display: inline-flex; align-items: center; }
  .detail-notes-inline { cursor: text; min-height: 28px; padding: 6px; border-radius: 4px; }
  .detail-notes-inline:hover { background: rgba(44,90,160,0.05); }
  .owl-mascot { cursor: pointer; transition: transform 0.3s; display: inline-block; }
  .owl-mascot:hover { transform: scale(1.2) rotate(-5deg); }
  .owl-mascot:active { transform: scale(0.95); }
  .owl-mascot.owl-blink svg rect.owl-eye-white { animation: owlBlink 3s infinite; }
  .owl-mascot.owl-bounce { animation: owlBounce 0.5s ease; }
  .owl-mascot.owl-wiggle { animation: owlWiggle 0.4s ease; }
  @keyframes owlBlink { 0%,92%,100% { height: 1; } 94%,98% { height: 0; } }
  @keyframes owlBounce { 0%,100% { transform: translateY(0); } 40% { transform: translateY(-8px); } 60% { transform: translateY(-4px); } }
  @keyframes owlWiggle { 0%,100% { transform: rotate(0deg); } 25% { transform: rotate(-8deg); } 75% { transform: rotate(8deg); } }
  .owl-speech { position: fixed; background: var(--card-bg); border: 1px solid var(--border); border-radius: 8px; padding: 6px 10px; font-size: 11px; color: var(--fg); white-space: normal; max-width: 280px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); z-index: 10000; pointer-events: none; display: none; }
  .owl-speech::before { content: ''; position: absolute; bottom: 100%; left: 50%; margin-left: -5px; border: 5px solid transparent; border-bottom-color: var(--border); }
  .owl-container { position: relative; display: inline-block; }
  .tz-setting { display: inline-flex; align-items: center; gap: 6px; }
  .tz-setting select { font-family: inherit; font-size: 12px; border: 1px solid var(--border); padding: 5px 10px; border-radius: 4px; background: var(--code-bg); color: var(--muted); cursor: pointer; }
  .tz-setting select:hover { background: var(--border); color: var(--fg); }
"""
