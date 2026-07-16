# Yankees Dashboard — setup guide

A free, always-on web dashboard for your Yankees stats — no Excel, no Mac
required to keep it running. A scheduled job on GitHub's own servers
refreshes the data every day; the page itself is just a webpage anyone with
the link can open (no login needed, but the link isn't listed anywhere
public).

## What this is

- `generate_data.py` + `mlb_data.py` — fetch current stats from MLB's Stats
  API and write them to `data.json`
- `index.html` — the dashboard page itself (reads `data.json`, draws
  interactive charts with Chart.js)
- `.github/workflows/update-data.yml` — tells GitHub to run
  `generate_data.py` automatically every day and save the result

## One-time setup

### 1. Create a GitHub account (if you don't have one)
Go to github.com and sign up — free.

### 2. Create a new repository
- Click the **+** in the top right → **New repository**
- Name it something like `yankees-dashboard`
- Set it to **Public** (required for free GitHub Pages hosting — see the
  note on privacy below)
- Don't check any of the "initialize with" boxes
- Click **Create repository**

### 3. Upload these files
On the new repo's page, click **uploading an existing file**, then drag in:
- `generate_data.py`
- `mlb_data.py`
- `index.html`
- `data.json` (a starter version so the page isn't broken before the first
  automated run completes)
- The whole `.github` folder (drag the folder itself — GitHub will keep
  the `workflows/update-data.yml` path inside it)

Commit the upload.

### 4. Enable GitHub Pages
- Go to the repo's **Settings** tab → **Pages** (left sidebar)
- Under "Build and deployment", set **Source** to **Deploy from a branch**
- Branch: **main**, folder: **/ (root)** → **Save**
- After a minute or two, GitHub will show you the live URL — something like
  `https://yourusername.github.io/yankees-dashboard/`

### 5. Trigger the first data update manually
Don't wait for tomorrow's scheduled run — trigger it now:
- Go to the **Actions** tab → click **Update dashboard data** (left side)
- Click **Run workflow** → **Run workflow** (green button)
- Wait ~1-2 minutes, refresh the page, and you should see a green checkmark
- Refresh your dashboard URL — it should now show real, current data

## After that

It just runs itself — every day at noon Eastern (17:00 UTC), GitHub fetches
fresh stats and updates the page automatically. Nothing on your computer
needs to be running for this to work.

## On privacy

The repo needs to be public for free GitHub Pages, which means the page is
technically reachable by anyone who has (or guesses) the exact URL — but
it's not listed anywhere, doesn't appear in search results, and there's no
personal or sensitive information on it (just public baseball stats). If you
want real password protection later, that requires either a paid GitHub
plan (private repos support Pages on paid tiers) or moving to a different
host like Netlify/Vercel, which support simple password gates on their free
tiers too — happy to help set that up if you want it.

## Adjusting the schedule

The workflow runs at `0 17 * * *` (17:00 UTC = noon Eastern during Daylight
Saving Time). If you want a different time, or need to adjust for Standard
Time (add an hour: `0 18 * * *`), edit that line in
`.github/workflows/update-data.yml` directly on GitHub (click the file →
pencil icon to edit → commit).

## What I verified vs. couldn't

**Verified:** the data-fetching logic (reusing exactly what's already proven
correct in your other two projects this season), the JSON structure, and
the dashboard's JavaScript logic against a realistic sample dataset.

**Couldn't verify:** how this actually looks and behaves once truly live on
GitHub Pages — please open the real URL after setup and let me know if
anything looks off, the same way we've debugged the other two projects.
