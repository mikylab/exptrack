"""
exptrack/dashboard/static_parts/html.py — HTML template structure

Split from static.py for maintainability.
"""

# Document head (everything before <style>)
HTML_HEAD = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>exptrack</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<style>
"""

# Everything between </style></head> and <script>
HTML_BODY = r"""</style>
</head>
<body>

<div class="header">
  <h1 onclick="showWelcome()" title="Back to dashboard home"><span class="owl-container" id="header-owl"><span class="owl-speech" id="owl-speech"></span><span class="owl-mascot owl-blink" onclick="event.stopPropagation();owlSpeak('click')"><svg width="28" height="28" viewBox="0 0 16 16" style="vertical-align:middle;margin-right:6px;image-rendering:pixelated"><!-- Pixel owl: ear tufts --><rect x="4" y="1" width="1" height="1" fill="#7c3aed"/><rect x="11" y="1" width="1" height="1" fill="#7c3aed"/><rect x="4" y="2" width="1" height="1" fill="#7c3aed"/><rect x="11" y="2" width="1" height="1" fill="#7c3aed"/><!-- Head --><rect x="5" y="2" width="6" height="1" fill="#2c5aa0"/><rect x="4" y="3" width="8" height="1" fill="#2c5aa0"/><rect x="4" y="4" width="8" height="1" fill="#2c5aa0"/><!-- Eyes (white circles with dark pupils) --><rect class="owl-eye-white" x="5" y="4" width="2" height="1" fill="#fff"/><rect class="owl-eye-white" x="9" y="4" width="2" height="1" fill="#fff"/><rect x="6" y="4" width="1" height="1" fill="#1a1a1a"/><rect x="10" y="4" width="1" height="1" fill="#1a1a1a"/><!-- Beak --><rect x="7" y="5" width="2" height="1" fill="#ffc107"/><!-- Body --><rect x="4" y="5" width="3" height="1" fill="#2c5aa0"/><rect x="9" y="5" width="3" height="1" fill="#2c5aa0"/><rect x="4" y="6" width="8" height="1" fill="#2c5aa0"/><rect x="5" y="7" width="6" height="1" fill="#2c5aa0"/><!-- Belly --><rect x="6" y="7" width="4" height="1" fill="#5c9ce6"/><rect x="5" y="8" width="6" height="1" fill="#2c5aa0"/><rect x="6" y="8" width="4" height="1" fill="#5c9ce6"/><!-- Wings --><rect x="3" y="6" width="1" height="2" fill="#7c3aed"/><rect x="12" y="6" width="1" height="2" fill="#7c3aed"/><!-- Feet --><rect x="6" y="9" width="1" height="1" fill="#ffc107"/><rect x="9" y="9" width="1" height="1" fill="#ffc107"/></svg></span></span>exptrack</h1>
  <div class="header-actions">
    <span class="tz-setting" title="Set timezone for displaying timestamps">
      <select id="tz-select" onchange="setTimezone(this.value)">
        <option value="">TZ: Browser local</option>
        <option value="UTC">UTC</option>
        <option value="America/New_York">US Eastern</option>
        <option value="America/Chicago">US Central</option>
        <option value="America/Denver">US Mountain</option>
        <option value="America/Los_Angeles">US Pacific</option>
        <option value="Europe/London">London</option>
        <option value="Europe/Berlin">Berlin</option>
        <option value="Europe/Paris">Paris</option>
        <option value="Asia/Tokyo">Tokyo</option>
        <option value="Asia/Shanghai">Shanghai</option>
        <option value="Asia/Kolkata">India</option>
        <option value="Australia/Sydney">Sydney</option>
      </select>
    </span>
    <button class="theme-btn" id="theme-toggle" onclick="toggleTheme()" title="Toggle dark mode">&#9790;</button>
    <button class="help-btn" onclick="toggleHelp()">? Docs</button>
  </div>
</div>

<div class="help-panel" id="help-panel">
  <button class="help-close" onclick="toggleHelp()">&times;</button>
  <h3>What is exptrack?</h3>
  <p>A zero-friction experiment tracker for ML workflows. It captures parameters, metrics, variables, code changes, and artifacts automatically — no code changes needed.</p>

  <h3>Key Concepts</h3>
  <div class="help-grid">
    <div class="help-item">
      <strong>Params</strong>
      <span>Hyperparameters and config values captured from argparse, CLI flags, or notebook variables (lr, batch_size, etc). These define WHAT you ran.</span>
    </div>
    <div class="help-item">
      <strong>Metrics</strong>
      <span>Numeric values logged during training (loss, accuracy, etc). Tracked per step with min/max/last. These measure HOW it performed.</span>
    </div>
    <div class="help-item">
      <strong>Variables</strong>
      <span>All notebook variable values captured automatically — scalars, arrays, DataFrames, tensors. Prefixed with _var/ in params. Shows the full state of your experiment.</span>
    </div>
    <div class="help-item">
      <strong>Artifacts</strong>
      <span>Output files (plots, models, CSVs) auto-captured via plt.savefig() or manually via exptrack.notebook.out(). Linked to the experiment timeline.</span>
    </div>
    <div class="help-item">
      <strong>Code Changes</strong>
      <span>Diffs of your code vs. the last git commit (scripts) or previous cell version (notebooks). Only changed lines are stored. Prefixed with _code_change/.</span>
    </div>
    <div class="help-item">
      <strong>Timeline</strong>
      <span>Ordered log of every cell execution, variable change, and artifact save. Each event has a sequence number (seq) so you can reconstruct the full execution history.</span>
    </div>
    <div class="help-item">
      <strong>Tags &amp; Notes</strong>
      <span>Manual labels (tags) and free-text annotations (notes) you add to organize experiments. Use tags like "baseline", "best", "ablation".</span>
    </div>
    <div class="help-item">
      <strong>Compare</strong>
      <span>Side-by-side comparison of two experiments (params, variables, metrics) or two points within the same experiment (variable state at different timeline positions).</span>
    </div>
  </div>

  <h3>Dashboard Views</h3>
  <p><strong>Experiment list:</strong> Collapsible sidebar on the left. Click any experiment to see details. Use checkboxes to select 2 experiments for comparison.</p>
  <p><strong>Detail view:</strong> Shows full experiment info in the main area. Tabs: Overview, Timeline, Compare Within.</p>
  <p><strong>Compare:</strong> Select two experiments via checkboxes in the sidebar, then click Compare.</p>
  <p><strong>Export:</strong> Use the Export button on any experiment to get JSON, Markdown, or Plain Text.</p>
</div>

<div id="app-layout">
  <!-- Left: Collapsible experiment list -->
  <div id="exp-sidebar">
    <div class="sidebar-content">
      <div class="sidebar-header">
        <input type="text" id="search-input" placeholder="Search..." oninput="searchQuery=this.value;renderExpList()">
        <button class="collapse-btn" onclick="toggleSidebar()" title="Collapse sidebar">&#8249;</button>
      </div>
      <div class="status-chips" id="status-chips"></div>
      <div id="exp-list"></div>
      <div id="sidebar-actions-bar"></div>
    </div>
    <div class="collapse-strip" onclick="toggleSidebar()">
      <span style="font-size:18px;color:var(--muted)">&#8250;</span>
      <span id="sidebar-count" style="font-size:11px;color:var(--muted);margin-top:8px;writing-mode:vertical-rl"></span>
    </div>
  </div>

  <!-- Center: Main content -->
  <div id="main-content">
    <!-- Welcome state: shown when no experiment selected -->
    <div id="welcome-state">
      <div class="stats" id="stats"></div>
      <div class="table-toolbar">
        <input type="text" id="main-search" class="main-search-input" placeholder="Search experiments..." oninput="searchQuery=this.value;renderExperiments();renderExpList()">
        <div class="toolbar-btn-group">
          <button class="toolbar-btn compare-main-btn" onclick="showCompareView()" title="Compare two experiments">&#x2194; Compare</button>
          <button class="toolbar-btn" onclick="toggleManageDrawer()" title="Manage tags &amp; studies">&#x2699; Manage</button>
        </div>
        <div class="tag-filter-bar" id="filter-bar"></div>
      </div>
      <div class="group-bar" id="group-bar">
        <span>Group by:</span>
        <button data-group="git_commit" onclick="setGroup('git_commit')" class="active">Git Commit</button>
        <button data-group="git_branch" onclick="setGroup('git_branch')">Branch</button>
        <button data-group="status" onclick="setGroup('status')">Status</button>
        <button data-group="" onclick="setGroup('')">None</button>
        <span style="margin-left:12px;border-left:1px solid var(--border);padding-left:12px" class="highlight-toggle">
          <label><input type="checkbox" id="highlight-toggle" onchange="toggleHighlightMode(this.checked)"> Highlight by study</label>
        </span>
        <span class="highlight-legend" id="highlight-legend"></span>
      </div>
      <div id="table-actions-bar" class="table-actions-bar" style="display:none"></div>
      <table id="exp-table"><thead><tr>
        <th style="width:28px"></th><th class="cb-col"><input type="checkbox" onclick="selectAllVisible()" title="Select all"></th><th class="sortable" onclick="toggleSort('id')">ID<span class="sort-arrow"></span></th><th class="sortable" onclick="toggleSort('name')">Name<span class="sort-arrow"></span></th><th class="sortable" onclick="toggleSort('status')">Status<span class="sort-arrow"></span></th><th class="sortable" onclick="toggleSort('tags')">Tags<span class="sort-arrow"></span></th><th class="sortable" onclick="toggleSort('studies')">Studies<span class="sort-arrow"></span></th><th>Notes</th><th>Key Metrics</th><th>Changes</th><th class="sortable" onclick="toggleSort('created_at')">Started<span class="sort-arrow"></span></th>
      </tr></thead><tbody id="exp-body"></tbody></table>
    </div>

    <!-- Detail state: shown when an experiment is selected -->
    <div id="detail-view" style="display:none">
      <div id="detail-panel"></div>
    </div>

    <!-- Compare state -->
    <div id="compare-view" style="display:none">
      <div class="compare-header">
        <button class="back-link" onclick="showWelcome()">&larr; Back to experiments</button>
        <h3 style="margin:8px 0 4px">Compare Experiments</h3>
      </div>
      <div class="compare-input">
        <div class="compare-selector">
          <label class="compare-label">base</label>
          <select id="cmp-id1"><option value="">-- Select base experiment --</option></select>
        </div>
        <span class="vs-label">&larr;&rarr;</span>
        <div class="compare-selector">
          <label class="compare-label">compare</label>
          <select id="cmp-id2"><option value="">-- Select compare experiment --</option></select>
        </div>
        <button class="primary" onclick="doCompare()">Compare</button>
      </div>
      <div id="compare-result"></div>
    </div>
  </div>
</div>

<div class="manage-drawer-overlay" id="manage-overlay" onclick="closeManageDrawer()"></div>
<div class="manage-drawer" id="manage-drawer">
  <div class="manage-drawer-header">
    <h3>Manage Tags &amp; Studies</h3>
    <button class="manage-drawer-close" onclick="closeManageDrawer()">&times;</button>
  </div>
  <div class="manage-drawer-body" id="manage-drawer-body"></div>
</div>

<script>
"""

# Document footer (after </script>)
HTML_FOOTER = r"""</script>
</body>
</html>
"""
