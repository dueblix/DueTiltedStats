# DueTiltedStats — Overlay Customisation Guide

This guide explains how to build a custom overlay for DueTiltedStats. The overlay
is a plain HTML file that polls a local JSON endpoint for live game data.

---

## How the drop-in system works

Drop a file named `overlay_custom.html` in the same folder as the `.exe`. The app
serves it automatically at `http://127.0.0.1:5000/overlay` instead of the built-in
template. Delete the file to revert to the built-in overlay.

**Starting point:** Copy `overlay.html` from the app's `templates/` folder (or from
the GitHub repo) and rename it `overlay_custom.html`. Edit it to taste, then place
it next to the `.exe`.

The latest version of this guide is always available on GitHub alongside the source.

---

## `/api/state` — the data endpoint

Your overlay polls `http://127.0.0.1:5000/api/state` (default port 5000).
The response is JSON. The shape depends on `status`.

### Fields present in every response

| Field | Type | Description |
|---|---|---|
| `status` | `"waiting"` \| `"idle"` \| `"active"` | Current game state |

### `status: "waiting"`

No session has ever been recorded. Only `status` is present.

```json
{ "status": "waiting" }
```

### `status: "idle"` and `status: "active"`

Both states return the same shape. `"active"` means a run is currently in progress;
`"idle"` means the most recently completed session is being displayed.

| Field | Type | Notes |
|---|---|---|
| `status` | string | `"idle"` or `"active"` |
| `last_level` | object \| `null` | Last completed level. `null` if no levels played yet this run. |
| `run_leaderboard` | array | Players sorted by exp earned (highest first). |
| `run_history` | array | Up to 50 recent levels, most recent first. |
| `run_totals` | object \| `null` | Run-wide aggregate. `null` if no run exists. |
| `server_time` | string | UTC ISO 8601 timestamp. Use with `run_totals.run_started_at` to compute elapsed run time on the client. |

#### `last_level` object

| Field | Type | Description |
|---|---|---|
| `level_number` | integer | 1-based level index within the run |
| `elapsed_time` | float \| `null` | Level duration in seconds. `null` if not recorded. |
| `level_exp` | integer | Exp awarded for this level |
| `level_passed` | boolean | `true` = players survived; `false` = everyone died |
| `survivors` | integer | Number of players who survived |
| `total_players` | integer | Total players in the level |
| `top_tiltee_username` | string \| `null` | Twitch username of the player who caused the most eliminations |

#### `run_leaderboard` entry

| Field | Type | Description |
|---|---|---|
| `username` | string | Twitch login name (lowercase) |
| `display_name` | string | Display name (use this for rendering) |
| `levels_played` | integer | Levels entered this run |
| `levels_survived` | integer | Levels survived this run |
| `exp_earned` | integer | Total exp earned this run |

#### `run_history` entry

Same as `last_level` **except** `top_tiltee_username` is not included.

| Field | Type |
|---|---|
| `level_number` | integer |
| `elapsed_time` | float \| `null` |
| `level_exp` | integer |
| `level_passed` | boolean |
| `survivors` | integer |
| `total_players` | integer |

#### `run_totals` object

| Field | Type | Notes |
|---|---|---|
| `level_count` | integer | Total levels played in this run |
| `total_survivors` | integer | Sum of survivors across all levels |
| `total_players` | integer | Sum of total_players across all levels |
| `total_exp` | integer | Total exp awarded across all levels |
| `run_started_at` | string | ISO 8601 UTC timestamp |
| `run_ended_at` | string \| `null` | ISO 8601 UTC timestamp. `null` while the run is active. |

---

## Dummy payloads

Paste these into your browser console or a `fetch` mock while building your overlay
without needing the game running.

### Waiting

```json
{
  "status": "waiting"
}
```

### Idle (session just ended, 3-level run)

```json
{
  "status": "idle",
  "last_level": {
    "level_number": 3,
    "elapsed_time": 22.841,
    "level_exp": 1200,
    "level_passed": false,
    "survivors": 0,
    "total_players": 6,
    "top_tiltee_username": "some_player"
  },
  "run_leaderboard": [
    { "username": "alice",   "display_name": "Alice",   "levels_played": 3, "levels_survived": 2, "exp_earned": 3800 },
    { "username": "bob",     "display_name": "Bob",     "levels_played": 3, "levels_survived": 1, "exp_earned": 2200 },
    { "username": "charlie", "display_name": "Charlie", "levels_played": 2, "levels_survived": 1, "exp_earned": 1800 },
    { "username": "dave",    "display_name": "Dave",    "levels_played": 3, "levels_survived": 0, "exp_earned": 1200 }
  ],
  "run_history": [
    { "level_number": 3, "elapsed_time": 22.841, "level_exp": 1200, "level_passed": false, "survivors": 0, "total_players": 6 },
    { "level_number": 2, "elapsed_time": 58.312, "level_exp": 2400, "level_passed": true,  "survivors": 4, "total_players": 6 },
    { "level_number": 1, "elapsed_time": 41.005, "level_exp": 1800, "level_passed": true,  "survivors": 5, "total_players": 6 }
  ],
  "run_totals": {
    "level_count": 3,
    "total_survivors": 9,
    "total_players": 18,
    "total_exp": 5400,
    "run_started_at": "2024-03-15T14:00:00+00:00",
    "run_ended_at":   "2024-03-15T14:22:00+00:00"
  },
  "server_time": "2024-03-15T14:35:10.123456+00:00"
}
```

### Active (run in progress, 2 levels done)

Same shape as idle, with two differences:
- `status` is `"active"`
- `run_totals.run_ended_at` is `null`

```json
{
  "status": "active",
  "last_level": {
    "level_number": 2,
    "elapsed_time": 58.312,
    "level_exp": 2400,
    "level_passed": true,
    "survivors": 4,
    "total_players": 6,
    "top_tiltee_username": null
  },
  "run_leaderboard": [
    { "username": "alice",   "display_name": "Alice",   "levels_played": 2, "levels_survived": 2, "exp_earned": 4200 },
    { "username": "bob",     "display_name": "Bob",     "levels_played": 2, "levels_survived": 1, "exp_earned": 2400 },
    { "username": "charlie", "display_name": "Charlie", "levels_played": 1, "levels_survived": 1, "exp_earned": 2400 },
    { "username": "dave",    "display_name": "Dave",    "levels_played": 2, "levels_survived": 0, "exp_earned": 1800 }
  ],
  "run_history": [
    { "level_number": 2, "elapsed_time": 58.312, "level_exp": 2400, "level_passed": true,  "survivors": 4, "total_players": 6 },
    { "level_number": 1, "elapsed_time": 41.005, "level_exp": 1800, "level_passed": true,  "survivors": 5, "total_players": 6 }
  ],
  "run_totals": {
    "level_count": 2,
    "total_survivors": 9,
    "total_players": 12,
    "total_exp": 4200,
    "run_started_at": "2024-03-15T14:00:00+00:00",
    "run_ended_at":   null
  },
  "server_time": "2024-03-15T14:08:45.678901+00:00"
}
```

---

## Reference templates

### Template 1 — Minimal leaderboard only

The simplest possible overlay: a single leaderboard panel, no level history.

```html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<style>
  :root {
    --font:           'Courier New', monospace;
    --row-font-size:  36px;
    --row-height:     48px;
    --row-bg:         rgba(0, 0, 0, 0.65);
    --row-bg-alt:     rgba(20, 20, 20, 0.65);
    --font-colour:    #ffffff;
    --pad-v:          4px;
    --pad-h:          8px;
  }

  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    background: transparent;
    font-family: var(--font);
    width: 100vw; height: 100vh;
    overflow: hidden;
    display: flex; align-items: flex-start; justify-content: flex-end;
  }

  #panel { width: 280px; }

  table { width: 100%; border-collapse: collapse; }
  thead th {
    background: rgba(0,0,0,0.65);
    color: #aaaaaa; font-size: 11px; text-transform: uppercase;
    letter-spacing: 0.1em; padding: 4px 8px; text-align: center;
  }
  thead th.name { text-align: left; }
  tbody tr { background: var(--row-bg); height: var(--row-height); }
  tbody tr:nth-child(even) { background: var(--row-bg-alt); }
  tbody td {
    padding: var(--pad-v) var(--pad-h);
    font-size: var(--row-font-size); color: var(--font-colour);
    text-align: center; white-space: nowrap; vertical-align: middle;
  }
  td.name {
    text-align: left; font-weight: bold;
    width: 100%; max-width: 0; overflow: hidden; text-overflow: clip;
  }
</style>
</head>
<body>
  <div id="panel">
    <table>
      <thead><tr><th>#</th><th class="name">Player</th><th>P</th><th>S</th></tr></thead>
      <tbody id="lb-body"></tbody>
    </table>
  </div>

<script>
  const ROWS = 8;  // fixed number of rows to show

  async function refresh() {
    let data;
    try { const r = await fetch('/api/state'); data = await r.json(); }
    catch (_) { return; }

    const tbody = document.getElementById('lb-body');
    tbody.innerHTML = '';
    const players = data.run_leaderboard || [];
    for (let i = 0; i < ROWS; i++) {
      const p  = players[i];
      const tr = document.createElement('tr');
      if (p) {
        tr.innerHTML =
          `<td>${i+1}</td>` +
          `<td class="name">${esc(p.display_name)}</td>` +
          `<td>${p.exp_earned}</td>` +
          `<td>${p.levels_survived}</td>`;
      } else {
        tr.innerHTML = '<td></td><td class="name"></td><td></td><td></td>';
      }
      tbody.appendChild(tr);
    }
  }

  function esc(s) {
    return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  }

  async function tick() { await refresh(); setTimeout(tick, 2000); }
  tick();
</script>
</body>
</html>
```

### Template 2 — Built-in layout (starting point for full customisation)

The full two-panel layout is in `overlay.html` in the `templates/` folder of the
source repo. Copy it and rename it `overlay_custom.html` to use it as a starting
point. The CSS `:root` block at the top lists every value you can change:

```css
:root {
  --font:             'Courier New', monospace;
  --lb-width:         310px;
  --lb-font-size:     40px;
  --lb-font-colour:   #ffffff;
  --lb-row-bg:        rgba(26, 26, 26, 0.60);
  --lb-row-bg-alt:    rgba(26, 26, 26, 0.60);
  --lb-header-bg:     rgba(26, 26, 26, 0.60);
  --lb-row-height:    54px;
  --lb-pad-v:         4px;
  --lb-pad-h:         6px;
  --lb-radius:        0px;
  --lh-font-size:     20px;
  --lh-font-colour:   #ffffff;
  --lh-bg:            rgba(0, 0, 0, 0.75);
}
```

To move the leaderboard to the left side, change `grid-area: right` to
`grid-area: left` on `#leaderboard-pane` and adjust `grid-template-columns`
from `0 1fr 310px` to `310px 1fr 0`.

### Template 3 — Floating leaderboard (absolute positioning)

Use `position: absolute` if you want pixel-precise placement rather than a
grid zone layout:

```html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { background: transparent; width: 100vw; height: 100vh; overflow: hidden; }

  #leaderboard-pane {
    position: absolute;
    top: 20px; right: 20px;   /* change these to reposition */
    width: 300px;
    font-family: 'Courier New', monospace;
  }

  table { width: 100%; border-collapse: collapse; }
  tbody tr { background: rgba(0,0,0,0.70); height: 46px; }
  tbody tr:nth-child(odd) { background: rgba(20,20,20,0.70); }
  tbody td {
    padding: 3px 6px; font-size: 34px; color: #ffffff;
    text-align: center; vertical-align: middle; white-space: nowrap;
  }
  td.name {
    text-align: left; font-weight: bold;
    width: 100%; max-width: 0; overflow: hidden; text-overflow: clip;
  }
</style>
</head>
<body>
  <div id="leaderboard-pane">
    <table>
      <tbody id="lb-body"></tbody>
    </table>
  </div>

<script>
  const ROWS = 6;

  async function refresh() {
    let data;
    try { const r = await fetch('/api/state'); data = await r.json(); }
    catch (_) { return; }

    const tbody = document.getElementById('lb-body');
    tbody.innerHTML = '';
    const players = data.run_leaderboard || [];
    for (let i = 0; i < ROWS; i++) {
      const p  = players[i];
      const tr = document.createElement('tr');
      if (p) {
        tr.innerHTML =
          `<td>${i+1}</td>` +
          `<td class="name">${esc(p.display_name)}</td>` +
          `<td>${p.exp_earned}</td>`;
      } else {
        tr.innerHTML = '<td></td><td class="name"></td><td></td>';
      }
      tbody.appendChild(tr);
    }
  }

  function esc(s) {
    return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  }

  async function tick() { await refresh(); setTimeout(tick, 2000); }
  tick();
</script>
</body>
</html>
```

---

## Using AI to build and iterate on your overlay

This guide is designed to be pasted into an AI chat (Claude, ChatGPT, etc.) as
context when asking for help building or modifying your overlay.

**Recommended workflow:**

1. Copy the built-in `overlay.html` or one of the templates above as your starting
   point and rename it `overlay_custom.html`.
2. Open a new AI chat. Paste in this entire guide (or at least the
   `/api/state` reference section and the dummy payloads).
3. Describe what you want: *"Make the leaderboard wider", "Add a panel showing
   the current level number", "Change the font to Oswald from Google Fonts".*
4. Paste the current state of your `overlay_custom.html` into the chat.
5. Apply the AI's suggestions, drop the file next to the `.exe`, and reload the
   OBS browser source.
6. Iterate.

**Useful prompts to get started:**

- *"Using the /api/state schema above, add a banner that shows the last level's
  survivors/total_players ratio."*
- *"Redesign the leaderboard to show only the top 5 players with larger text and
  no level history panel."*
- *"Add a Google Font (Bebas Neue) to the overlay and apply it to the headers."*

---

## Maintenance note

The dummy payloads in this file must be kept in sync with the `/api/state` response
shape in `flask_overlay.py`. A maintenance comment is present in that file near the
`/api/state` route as a reminder. If you add or remove fields from the response,
update the field tables, dummy payloads, and any reference templates that reference
those fields.
