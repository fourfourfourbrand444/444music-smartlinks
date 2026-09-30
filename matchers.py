"""
Confidence scoring for "is this search result actually the release we're
looking for". Every platform search function returns candidates that get
scored here before anything is written back to Firestore.
"""
import re
from datetime import date, datetime
from rapidfuzz import fuzz

def _normalize(text: str) -> str:
    """Strip things that legitimately differ between platforms without
    meaning a different song: feat./ft. tags, (Remastered) etc., extra
    whitespace, punctuation noise."""
    if not text:
        return ""
    text = text.lower()
    text = re.sub(r"\(feat\.?[^)]*\)|\[feat\.?[^\]]*\]", "", text)
    text = re.sub(r"\bfeat\.?\s+.*$", "", text)
    text = re.sub(r"\bft\.?\s+.*$", "", text)
    text = re.sub(r"\((remaster(ed)?|radio edit|explicit|clean|deluxe)[^)]*\)", "", text)
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text

def match_confidence(target_artist: str, target_title: str,
                      candidate_artist: str, candidate_title: str) -> float:
    """Returns 0-100. Weighted toward title match since artist names
    are more often abbreviated/reordered by platforms than titles are."""
    a1, a2 = _normalize(target_artist), _normalize(candidate_artist)
    t1, t2 = _normalize(target_title), _normalize(candidate_title)

    artist_score = fuzz.token_sort_ratio(a1, a2)
    title_score = fuzz.token_sort_ratio(t1, t2)

    return round((artist_score * 0.35) + (title_score * 0.65), 1)

def best_match(target_artist: str, target_title: str, candidates: list):
    """candidates: list of dicts with 'artist', 'title', 'url' (plus
    whatever else the caller wants to carry through). Returns
    (best_candidate_or_None, confidence)."""
    if not candidates:
        return None, 0.0

    scored = [
        (c, match_confidence(target_artist, target_title, c.get("artist", ""), c.get("title", "")))
        for c in candidates
    ]
    scored.sort(key=lambda pair: pair[1], reverse=True)
    return scored[0]

def match_confidence_noisy(target_artist: str, target_title: str,
                            candidate_artist: str, candidate_title: str) -> float:
    """Like match_confidence, but for candidates whose label text is
    known to be noisy — e.g. pulled from a whole parent element because
    no clean per-link text was available (play counts, button labels,
    timestamps, etc. riding along with the real title/artist).

    token_sort_ratio penalizes extra unrelated words on either side
    fairly harshly, which is exactly wrong for "clean short target vs.
    noisy long candidate." token_set_ratio instead checks whether the
    target's words are present in the candidate, and is far less hurt
    by extra clutter around them."""
    a1, a2 = _normalize(target_artist), _normalize(candidate_artist)
    t1, t2 = _normalize(target_title), _normalize(candidate_title)

    artist_score = fuzz.token_set_ratio(a1, a2)
    title_score = fuzz.token_set_ratio(t1, t2)

    return round((artist_score * 0.35) + (title_score * 0.65), 1)

def best_match_noisy(target_artist: str, target_title: str, candidates: list):
    """Same contract as best_match, but scores with match_confidence_noisy.
    Use this for scrapers whose candidate labels come from a fallback
    parent-element text grab rather than a clean per-link title."""
    if not candidates:
        return None, 0.0

    scored = [
        (c, match_confidence_noisy(target_artist, target_title, c.get("artist", ""), c.get("title", "")))
        for c in candidates
    ]
    scored.sort(key=lambda pair: pair[1], reverse=True)
    return scored[0]


# ── Strict checks used ONLY for Spotify ──────────────────────────────

def title_similarity(target_title: str, candidate_title: str) -> float:
    """Title-only similarity, 0-100. Unlike match_confidence this does
    not blend in the artist score, so a good artist can't rescue a bad
    title (or the other way round)."""
    return float(fuzz.token_sort_ratio(_normalize(target_title), _normalize(candidate_title)))

def artist_matches(target_artist: str, candidate_artists: list, min_score: int = 85) -> bool:
    """True only if the release's main artist is one of the artists on
    the candidate. A wrong song by a different artist can't pass this,
    whatever its title score."""
    t = _normalize(target_artist)
    if not t:
        return False
    return any(
        fuzz.token_sort_ratio(t, _normalize(a)) >= min_score
        for a in (candidate_artists or [])
    )

_DATE_RE = re.compile(r"^(\d{4})(?:-(\d{2}))?(?:-(\d{2}))?$")

def parse_date(value):
    """Accepts '2026-09-30T00:00:00.000Z', '2026-09-30', '2026-09' or
    '2026' (Spotify sometimes only gives month/year). Returns a date,
    or None if it can't be read."""
    if not value:
        return None
    s = str(value).strip()
    m = _DATE_RE.match(s)
    try:
        if m:
            y = int(m.group(1))
            mo = int(m.group(2) or 1)
            d = int(m.group(3) or 1)
            return date(y, mo, d)
        return datetime.fromisoformat(s.replace("Z", "+00:00")).date()
    except ValueError:
        return None

def dates_close(release_date, candidate_date, tolerance_days: int) -> bool:
    """True if both dates are readable and within tolerance_days of each
    other. If either can't be read this returns False — the caller is
    checking a new release, so 'can't verify' means 'don't trust it'."""
    a, b = parse_date(release_date), parse_date(candidate_date)
    if not a or not b:
        return False
    return abs((a - b).days) <= tolerance_days
