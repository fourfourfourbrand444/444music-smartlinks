"""
Confidence scoring for "is this search result actually the release we're
looking for". Every platform search function returns candidates that get
scored here before anything is written back to Firestore.
"""
import re
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
