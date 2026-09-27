# 444Music SmartLink Automation

Finds Spotify/Apple Music/YouTube/Deezer/Tidal/Amazon Music/Boomplay/
Audiomack links for approved releases and writes them straight into
Firestore's `smartLink.stores.*` — the same fields your admin panel's
manual "Edit Store Links" dialog writes to. Skips anything already
Pending/Review/Rejected, and anything that already has at least one
store link, exactly like the "Needs SmartLink" filter in the admin page.

## Setup

1. **Install dependencies**
   ```
   pip install -r requirements.txt
   ```
   You'll also need Chrome installed on the machine running this
   (webdriver-manager downloads a matching ChromeDriver automatically).

2. **Firebase service account**
   Firebase Console → Project Settings (⚙️) → Service Accounts →
   Generate new private key. Save the JSON file somewhere on this
   machine — **not** in a public repo — and either:
   - rename it to `serviceAccountKey.json` in this folder, or
   - set an environment variable: `export FIREBASE_CREDENTIALS_PATH=/path/to/key.json`

3. **YouTube API key (optional but recommended)**
   Reuse the key your broadcast backend already has (Google Cloud
   project "444Music YouTube Stats"):
   ```
   export YOUTUBE_API_KEY=your_key_here
   ```
   Without it, YouTube search is skipped — everything else still runs.

4. **Run it**
   ```
   python main.py
   ```

## What to expect on a first run

- **Deezer, Apple Music, YouTube** — these use free public APIs, no
  scraping. If these three don't work, it's a config/key problem, not
  a "the site changed" problem.
- **Spotify** — scrapes the public search page. Generally stable but
  can occasionally get a CAPTCHA/bot page under heavy volume — that's
  what `SEARCH_DELAY_SECONDS` in `config.py` is there to reduce. Raise
  it if you see failures.
- **Tidal** — scrapes public search results. Should work for grabbing
  the link even though full playback needs login.
- **Amazon Music, Boomplay** — most likely to need attention. These
  sites are more defensive about automated traffic and their markup
  isn't documented anywhere public, so selectors in `scrapers.py` are
  best-effort. If a platform keeps failing, turn it off in
  `config.py`'s `ENABLED_PLATFORMS` and keep entering that one
  manually until the selector gets fixed.
- **Audiomack** — scraped here for consistency with the others, but
  Audiomack also has a free developer API
  (developer.audiomack.com) that would be more reliable long-term if
  the scraper gives you trouble.

## How matching works

Every result gets fuzzy-matched against the release's artist + title
(`matchers.py`) before anything is trusted. Below `CONFIDENCE_THRESHOLD`
(72 by default, in `config.py`), the field is left blank and printed
in the end-of-run report instead of writing a guess. Nothing is ever
overwritten if a link already exists for that field.

## Tuning selectors

If a scraper stops finding results, the site's markup likely changed.
`scrapers.py` has two layers per platform: a direct CSS selector where
one's known (Spotify), and a fallback that scans every link on the
page for one matching that platform's track-URL shape
(`link_scanner.py`) — which survives most markup changes since it
doesn't depend on class names. If both fail, open the page manually
and check whether the track URL's shape (the regex in `scrapers.py`)
still matches what's actually in the address bar.
