"""
Reads releases that need store links and writes results back.

Instead of a binary "has any link / has no link" check, this tracks which
specific platforms are still missing per release, and only that release's
missing platforms get searched on the next run. Firestore itself is the
record of what's done — the missing fields are the always-accurate list of
what still needs work. Once a platform's link is confirmed, it's never
re-touched.

Releases that already have 4 or more store links filled in — manual or
automatic, doesn't matter which — are skipped entirely and never
considered, even if a couple of platforms are still technically missing.
Only releases with 3 or fewer filled links get processed at all.

Releases are also given up on after repeated failure: if a release gets
processed and nothing new gets confirmed for it STALL_THRESHOLD_RUNS
times in a row, it stops being selected entirely — same idea as the
missing-platform tracking, Firestore itself remembers the streak via
smartLink.syncAttempts, so a permanently-stuck release (bad metadata,
genuinely not on any platform, whatever the cause) doesn't get
re-searched forever and crowd out newer releases. Any run that DOES
confirm at least one new link resets the streak to 0.

Spotify exception (the only one): a Spotify link this job wrote BY NAME
is tagged in smartLink.spotifyAuto and is re-checked on every run for
config.SPOTIFY_RECHECK_DAYS after the release date, so a better match
(e.g. the exact UPC match once the real song is live) can replace it.
Spotify links entered by hand, or found by UPC, are never overwritten.
Such re-check-only releases never count toward the give-up streak and
never trigger searches on any other platform.

Second Spotify exception: a recent release (within
config.SPOTIFY_RECHECK_DAYS of its release date) that is skipped by the
'4+ links' or give-up rules but still has NO Spotify link gets a
Spotify-only pass, so it can pick up its Spotify link once the song is
live. No other platform is searched for it.
"""
from datetime import datetime, timezone
import firebase_admin
from firebase_admin import credentials, firestore
import config

_app = None
_db = None

STALL_THRESHOLD_RUNS = 4


def init():
    global _app, _db
    if _app is None:
        cred = credentials.Certificate(config.FIREBASE_CREDENTIALS_PATH)
        _app = firebase_admin.initialize_app(cred)
        _db = firestore.client()
    return _db


def _missing_platforms(data: dict) -> list:
    """Every enabled platform this specific release doesn't already
    have a confirmed link for. This — not a separate backup file — is
    the single source of truth for 'what still needs work': whatever
    Firestore doesn't have filled in yet, gets tried again next run.
    Whatever it already has, never gets touched again."""
    stores = (data.get("smartLink") or {}).get("stores") or {}
    return [
        platform for platform, enabled in config.ENABLED_PLATFORMS.items()
        if enabled and not str(stores.get(platform, "")).strip()
    ]


def _filled_count(data: dict) -> int:
    """How many store links this release already has, period — manual
    entries and automatically-confirmed ones both count the same, and
    this counts every store field present regardless of whether that
    platform is currently enabled. Used to skip releases that already
    have 'enough' links (4+) without even considering what's missing,
    rather than the previous behavior of always processing anything
    with at least one gap."""
    stores = (data.get("smartLink") or {}).get("stores") or {}
    return sum(1 for v in stores.values() if str(v).strip())


def _sync_attempts(data: dict) -> int:
    return (data.get("smartLink") or {}).get("syncAttempts", 0)


def _parse_release_date(data: dict):
    release_date = data.get("releaseDate")
    if not release_date:
        return None
    try:
        rd = datetime.fromisoformat(str(release_date).replace("Z", "+00:00"))
    except ValueError:
        return None
    if rd.tzinfo is None:
        rd = rd.replace(tzinfo=timezone.utc)
    return rd


def _release_date_reached(data: dict) -> bool:
    rd = _parse_release_date(data)
    if rd is None:
        return True  # same conservative default as the admin panel's JS
    return rd <= datetime.now(timezone.utc)


def _spotify_url(data: dict) -> str:
    stores = (data.get("smartLink") or {}).get("stores") or {}
    return str(stores.get("spotify", "")).strip()


def _spotify_recheck_due(data: dict) -> bool:
    """True only for a Spotify link this job itself wrote by NAME, still
    inside the re-check window. Hand-entered links (no spotifyAuto tag)
    and UPC-exact links are never re-checked."""
    if not config.ENABLED_PLATFORMS.get("spotify"):
        return False
    auto = (data.get("smartLink") or {}).get("spotifyAuto") or {}
    if auto.get("method") != "name" or not _spotify_url(data):
        return False
    rd = _parse_release_date(data)
    if rd is None:
        return False
    days_since = (datetime.now(timezone.utc) - rd).days
    return days_since <= config.SPOTIFY_RECHECK_DAYS


def _spotify_fill_due(data: dict) -> bool:
    """True when Spotify is still empty on a recent release. Used only
    for releases the '4+ links' / give-up rules would otherwise skip
    entirely: without this, a release that already has Apple, YouTube,
    Tidal and Audiomack links would never get a Spotify search, even
    after the real song goes live. Limited to the same window as the
    re-check (config.SPOTIFY_RECHECK_DAYS after release)."""
    if not config.ENABLED_PLATFORMS.get("spotify") or _spotify_url(data):
        return False
    rd = _parse_release_date(data)
    if rd is None:
        return False
    days_since = (datetime.now(timezone.utc) - rd).days
    return 0 <= days_since <= config.SPOTIFY_RECHECK_DAYS


def get_releases_needing_smartlinks():
    db = init()
    docs = db.collection(config.FIRESTORE_COLLECTION).where("status", "==", "Approved").get()

    releases = []
    for doc in docs:
        data = doc.to_dict()
        if not _release_date_reached(data):
            continue

        recheck = _spotify_recheck_due(data)
        skipped = (
            _filled_count(data) >= 4                      # already has 4+ links
            or _sync_attempts(data) >= STALL_THRESHOLD_RUNS  # gave up after repeated failed runs
        )

        if skipped:
            if not (recheck or _spotify_fill_due(data)):
                continue
            missing = ["spotify"]  # Spotify only; no other platform is searched
        else:
            missing = _missing_platforms(data)
            if recheck and "spotify" not in missing:
                missing.append("spotify")

        if missing:
            releases.append({
                "id": doc.id,
                "artist": data.get("artistName", ""),
                "title": data.get("releaseTitle") or data.get("songTitle") or data.get("title") or "",
                "missing": missing,
                "attempts": _sync_attempts(data),
                "upc": str(data.get("upc", "") or "").strip(),
                "releaseDate": data.get("releaseDate", ""),
                "previouslyReleased": data.get("previouslyReleased", ""),
                "spotifyUrl": _spotify_url(data),
                "recheck": recheck,
                "recheck_only": skipped,
            })
    return releases


def write_store_links(submission_id: str, store_links: dict, spotify_meta: dict = None):
    """store_links: e.g. {"spotify": "...", "deezer": "..."} — only
    fields that were actually confirmed get passed in, so this never
    overwrites an existing link with a blank.

    spotify_meta (only when store_links contains "spotify"): how that
    link was found, e.g. {"method": "upc", "score": 100.0, "at": "..."},
    saved to smartLink.spotifyAuto so future runs know the link is
    job-written (and whether it's still worth re-checking)."""
    if not store_links:
        return
    db = init()
    update_data = {f"smartLink.stores.{k}": v for k, v in store_links.items()}
    if spotify_meta and "spotify" in store_links:
        update_data["smartLink.spotifyAuto"] = spotify_meta
    db.collection(config.FIRESTORE_COLLECTION).document(submission_id).update(update_data)


def record_attempt(submission_id: str, made_progress: bool):
    """Called once per release after each run, regardless of outcome.
    made_progress=True (this run confirmed at least one new link) resets
    the stall counter to 0 — clearly still worth retrying. False
    increments it; once it hits STALL_THRESHOLD_RUNS,
    get_releases_needing_smartlinks stops selecting this release at all."""
    db = init()
    doc_ref = db.collection(config.FIRESTORE_COLLECTION).document(submission_id)
    if made_progress:
        doc_ref.update({"smartLink.syncAttempts": 0})
    else:
        doc_ref.update({"smartLink.syncAttempts": firestore.Increment(1)})
