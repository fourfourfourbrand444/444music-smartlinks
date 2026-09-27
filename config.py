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

# ── Matching ──────────────────────────────────────────────────────────
# 0-100. Below this, the field is left blank and the release is flagged
# in the run report instead of writing a guessed link.
# NOTE: main.py currently overrides this to 55 for its own run, based on
# manual verification of real matches — this value is left at 72 here in
# case anything else in the project reads config.CONFIDENCE_THRESHOLD
# directly and should stay conservative.
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
    "spotify": True,
    "appleMusic": True,   # via iTunes Search API — reliable
    "itunes": True,       # same API call as appleMusic, separate field
    "deezer": True,       # via Deezer public API — reliable
    "youtube": True,      # via YouTube Data API — reliable if key is set
    "tidal": True,         # handled as a deterministic search link now, not scraped
    "amazonMusic": False,  # removed — no scraper, hits login/bot-detection walls, manual only
    "boomplay": False,     # removed — no scraper, hits login/bot-detection walls, manual only
    "audiomack": True,     # handled as a deterministic search link now, not scraped
}
