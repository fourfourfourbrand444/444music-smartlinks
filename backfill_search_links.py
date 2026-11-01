"""
One-off backfill: add Boomplay and Amazon Music SEARCH links to OLD
approved releases that don't have them yet.

Run from the same folder as main.py (needs the same Firebase service
account setup as main.py):

    python backfill_search_links.py              # DRY RUN - prints what
                                                 # it WOULD write, changes nothing
    python backfill_search_links.py --apply      # actually writes
    python backfill_search_links.py --apply --limit 10   # first 10 releases only

Safety rules:
  - Only touches releases that are Approved and whose release date has
    passed (same as main.py).
  - For each store, only writes when that store's field is empty. A link
    that already exists (typed by hand or written earlier) is NEVER
    changed.
  - Writes ONLY smartLink.stores.boomplay and/or smartLink.stores.amazonMusic.
    No other store, no slug, no sync counters are touched.
  - Releases with no smartLink data at all are skipped and listed, so
    this never creates a half-empty smartLink on them.
  - Releases with no artist or no title are skipped and listed.
"""
import sys
from urllib.parse import quote

import config
import firestore_sync

# store field -> search page. Same URLs main.py writes.
SEARCH_LINKS = {
    "boomplay": "https://www.boomplay.com/search/default/{query}",
    "amazonMusic": "https://music.amazon.com/search/{query}",
}


def run(apply: bool, limit: int):
    db = firestore_sync.init()
    docs = db.collection(config.FIRESTORE_COLLECTION).where("status", "==", "Approved").get()

    to_write = []          # (doc_id, artist, title, {field: url})
    already_all = 0
    not_released = 0
    no_smartlink = []
    no_name = []
    per_store = {k: 0 for k in SEARCH_LINKS}

    for doc in docs:
        data = doc.to_dict()
        if not firestore_sync._release_date_reached(data):
            not_released += 1
            continue

        smartlink = data.get("smartLink")
        if not isinstance(smartlink, dict) or not smartlink:
            no_smartlink.append(doc.id)
            continue

        stores = smartlink.get("stores") or {}
        needed = [k for k in SEARCH_LINKS if not str(stores.get(k, "")).strip()]
        if not needed:
            already_all += 1
            continue

        artist = (data.get("artistName") or "").strip()
        title = (data.get("releaseTitle") or data.get("songTitle") or data.get("title") or "").strip()
        if not artist or not title:
            no_name.append(doc.id)
            continue

        query = quote(f"{artist} {title}", safe="")
        links = {k: SEARCH_LINKS[k].format(query=query) for k in needed}
        for k in needed:
            per_store[k] += 1
        to_write.append((doc.id, artist, title, links))

    print(f"Approved releases checked   : {len(docs)}")
    print(f"  already have both         : {already_all}  (left untouched)")
    print(f"  not released yet          : {not_released}  (skipped)")
    print(f"  no smartLink data         : {len(no_smartlink)}  (skipped)")
    print(f"  missing artist/title      : {len(no_name)}  (skipped)")
    print(f"  releases that WOULD change: {len(to_write)}")
    for k, n in per_store.items():
        print(f"      would get {k:<12}: {n}")
    print()

    if limit:
        to_write = to_write[:limit]

    for doc_id, artist, title, links in to_write:
        print(f"  {artist} - {title}")
        for k, url in links.items():
            print(f"      {k}: {url}")
        if apply:
            db.collection(config.FIRESTORE_COLLECTION).document(doc_id).update(
                {f"smartLink.stores.{k}": url for k, url in links.items()}
            )

    if apply:
        print(f"\nDone. Updated {len(to_write)} release(s).")
    else:
        print("\nDRY RUN - nothing was written. Run again with --apply to write these.")

    if no_smartlink:
        print("\nSkipped (no smartLink data) - ids:", ", ".join(no_smartlink))
    if no_name:
        print("\nSkipped (no artist/title) - ids:", ", ".join(no_name))


if __name__ == "__main__":
    args = sys.argv[1:]
    limit = 0
    if "--limit" in args:
        try:
            limit = int(args[args.index("--limit") + 1])
        except (IndexError, ValueError):
            print("--limit needs a number, e.g. --limit 10")
            sys.exit(1)
    run(apply="--apply" in args, limit=limit)
