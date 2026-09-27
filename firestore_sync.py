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


def _release_date_reached(data: dict) -> bool:
    release_date = data.get("releaseDate")
    if not release_date:
        return True  # same conservative default as the admin panel's JS
    try:
        rd = datetime.fromisoformat(str(release_date).replace("Z", "+00:00"))
    except ValueError:
        return True
    if rd.tzinfo is None:
        rd = rd.replace(tzinfo=timezone.utc)
    return rd <= datetime.now(timezone.utc)


def get_releases_needing_smartlinks():
    db = init()
    docs = db.collection(config.FIRESTORE_COLLECTION).where("status", "==", "Approved").get()

    releases = []
    for doc in docs:
        data = doc.to_dict()
        if not _release_date_reached(data):
            continue
        if _filled_count(data) >= 4:
            continue  # already has 4+ links (manual or automatic) — skip entirely
        if _sync_attempts(data) >= STALL_THRESHOLD_RUNS:
            continue  # gave up on this one after repeated failed runs
        missing = _missing_platforms(data)
        if missing:
            releases.append({
                "id": doc.id,
                "artist": data.get("artistName", ""),
                "title": data.get("releaseTitle") or data.get("songTitle") or data.get("title") or "",
                "missing": missing,
                "attempts": _sync_attempts(data),
            })
    return releases


def write_store_links(submission_id: str, store_links: dict):
    """store_links: e.g. {"spotify": "...", "deezer": "..."} — only
    fields that were actually confirmed get passed in, so this never
    overwrites an existing link with a blank."""
    if not store_links:
        return
    db = init()
    update_data = {f"smartLink.stores.{k}": v for k, v in store_links.items()}
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
