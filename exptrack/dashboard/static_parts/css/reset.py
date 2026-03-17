"""CSS variables, theme definitions, and base reset styles."""

CSS_RESET = """
  @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&display=swap');
  * { margin: 0; padding: 0; box-sizing: border-box; }
  :root {
    --bg: #faf9f7; --fg: #1a1a1a; --muted: #777; --border: #d0d0d0;
    --green: #2d7d46; --red: #c0392b; --yellow: #b8860b; --blue: #2c5aa0;
    --purple: #7c3aed; --card-bg: #fff; --code-bg: #f5f3f0;
    --tl-cell: #2c5aa0; --tl-var: #7c3aed; --tl-artifact: #2d7d46;
    --tl-metric: #d4820f; --tl-obs: #999;
  }
  body.dark {
    --bg: #1a1a1a; --fg: #e0e0e0; --muted: #999; --border: #444;
    --green: #4caf50; --red: #ef5350; --yellow: #ffc107; --blue: #5c9ce6;
    --purple: #b388ff; --card-bg: #252525; --code-bg: #2d2d2d;
    --tl-cell: #5c9ce6; --tl-var: #b388ff; --tl-artifact: #4caf50;
    --tl-metric: #ffc107; --tl-obs: #777;
  }
  body {
    font-family: 'IBM Plex Mono', monospace;
    background: var(--bg); color: var(--fg);
    margin: 0; padding: 0;
    font-size: 15px; line-height: 1.5;
    overflow: hidden; height: 100vh;
  }
"""
