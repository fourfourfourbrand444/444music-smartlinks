import os

# ── Firebase ──────────────────────────────────────────────────────────
# Download this from Firebase Console → Project Settings → Service
# Accounts → Generate new private key. Keep it OUT of git.
FIREBASE_CREDENTIALS_PATH = os.environ.get(
    "FIREBASE_CREDENTIALS_PATH", "serviceAccountKey.json"
)
FIRESTORE_COLLECTION = "submissions"

# ── YouTube Data API v3 ──────────────────────────────────────────────
# Reuse the same key your broadcast backend already uses for view counts.
YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY", "")

# ── Spotify ───────────────────────────────────────────────────────────
# "scraper" = Spotify's public web search page via the browser (works
#             without Premium; artist + title must both match).
# "api"     = Spotify Web API (UPC lookup + strict name search). Spotify
#             currently refuses these calls with HTTP 403 unless the
#             developer app's owner has an active Premium plan.
SPOTIFY_METHOD = "scraper"

# --- Only used when SPOTIFY_METHOD = "api" ---
# Same Spotify developer app your backend already uses on Render. Set
# both as environment variables / GitHub Actions secrets. Never hardcode.
SPOTIFY_CLIENT_ID = os.environ.get("SPOTIFY_CLIENT_ID", "")
SPOTIFY_CLIENT_SECRET = os.environ.get("SPOTIFY_CLIENT_SECRET", "")

# Spotify-only matching rules (other stores are NOT affected by these).
# 1) (api only) Look the release up by its UPC first (exact match or nothing).
SPOTIFY_USE_UPC = True
# Markets tried in order for the UPC lookup ("" = no market filter).
SPOTIFY_MARKETS = ("", "GH", "US")
# 2) Title similarity must be at least this (0-100). Used by BOTH methods;
#    the release's main artist must also be on the result.
SPOTIFY_TITLE_MIN = 60
# 3) (api only) Name search, new releases only (previouslyReleased "No"):
#    Spotify's release date must be within this many days of ours.
SPOTIFY_DATE_TOLERANCE_DAYS = 14
# Links the job found BY NAME are re-checked on each run for this many
# days after the release date, and replaced if a better match appears.
# Links found by UPC are exact and never re-checked. Links entered by
# hand are never touched.
SPOTIFY_RECHECK_DAYS = 30

# ── Matching ──────────────────────────────────────────────────────────
# 0-100. Below this, the field is left blank and the release is flagged
# in the run report instead of writing a guessed link.
# NOTE: main.py currently overrides this to 55 for its own run, based on
# manual verification of real matches — this value is left at 72 here in
# case anything else in the project reads config.CONFIDENCE_THRESHOLD
# directly and should stay conservative.
# (Spotify no longer uses this threshold — see the SPOTIFY_* settings.)
CONFIDENCE_THRESHOLD = 72

# ── Selenium ──────────────────────────────────────────────────────────
HEADLESS = True
PAGE_LOAD_TIMEOUT = 20          # seconds to wait for a page/element
SEARCH_DELAY_SECONDS = 4        # politeness delay between site searches
RETRIES_PER_PLATFORM = 1        # re-attempt once on timeout/stale element

# ── Which platforms to run ───────────────────────────────────────────
# Turn any of these off if one keeps breaking and you'd rather do it
# manually for now — the rest keep running.
ENABLED_PLATFORMS = {
    "spotify": True,       # see SPOTIFY_METHOD above (scraper by default)
    "appleMusic": True,   # via iTunes Search API — reliable
    "itunes": True,       # same API call as appleMusic, separate field
    "deezer": True,       # via Deezer public API — reliable
    "youtube": True,      # via YouTube Data API — reliable if key is set
    "tidal": True,         # handled as a deterministic search link now, not scraped
    "amazonMusic": False,  # removed — no scraper, hits login/bot-detection walls, manual only
    "boomplay": False,     # removed — no scraper, hits login/bot-detection walls, manual only
    "audiomack": True,     # handled as a deterministic search link now, not scraped
}
