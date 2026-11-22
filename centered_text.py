"""
Scryfall 'centered text' print tag -> offline cache + lookup.

WotC prints some cards (mostly classic one-line spells, the five basic lands,
and a handful of short-text lands) with the rules text CENTERED in the text box
instead of left-justified.  Scryfall's community Tagger records exactly those
prints under the PRINTING_TAG "centered text"
(https://tagger.scryfall.com/tags/print/centered-text).

This module fetches that tag from the tagger and caches it OFFLINE so a run can
decide per-card "center this text" without any network access:

  * ``update_centered_text_cache(force)`` -- pull every tagged print from the
    tagger (paginated GraphQL, 429-aware) and write ``centered_text_cache.json``
    atomically.  Honors a 7-day TTL and an flock, mirroring scryfall_cache.
  * ``load_centered_text_cache()`` -- read the cache back ({} when absent).
  * ``is_centered_text(name)`` -- the per-card predicate used at render time:
    ensures the cache is present/fresh (falling back to the last good cache when
    offline) and answers whether `name` was printed centered.

The cache is keyed by the lower-cased card name (the tag is per-PRINT, but the
aesthetic choice is per-CARD: if any print of a card is centered, the card is
centered).  Each entry keeps one representative print for provenance.

Dependency-light on purpose (requests/json/os/time/fcntl only) so a bare lookup
never drags in PIL/selenium.
"""
import fcntl
import json
import os
import re
import sys
import time
import unicodedata
from datetime import datetime, timezone

import requests

# ---------------------------------------------------------------------------
# Data location (same convention as scryfall_cache.py: --data-dir / env var)
# ---------------------------------------------------------------------------
DATA_DIR = os.environ.get("CC_AUTOMATOR_DATA_DIR", "/data/ccAutomator")
CACHE_FILE = os.path.join(DATA_DIR, "centered_text_cache.json")
LOCK_FILE = os.path.join(DATA_DIR, "centered_text_cache.lock")

# The tag we are interested in (tagger slug / PRINTING_TAG).
TAG_TYPE = "PRINTING_TAG"
TAG_SLUG = "centered-text"
TAGGER_BASE = "https://tagger.scryfall.com"
TAGGER_PAGE = f"{TAGGER_BASE}/tags/print/{TAG_SLUG}"

# How long a fetched cache stays "fresh" before we consider re-fetching.
CACHE_TTL_SECONDS = 7 * 24 * 3600          # 1 week
_MAX_RETRIES = 8
_RETRY_AFTER_CAP = 120.0                    # never sleep longer than this per 429

_GRAPHQL_QUERY = """
query FetchCentered($t: TagType!, $s: String!, $page: Int = 1) {
  tagBySlug(type: $t, slug: $s, aliasing: true) {
    name
    slug
    description
    taggings(page: $page, order: NAME) {
      total
      perPage
      results {
        card { name set collectorNumber oracleId }
      }
    }
  }
}
"""


def configure_data_dir(path):
    """Point the cache at `path` (called from ccAutomator's --data-dir)."""
    global DATA_DIR, CACHE_FILE, LOCK_FILE
    DATA_DIR = os.path.abspath(path)
    CACHE_FILE = os.path.join(DATA_DIR, "centered_text_cache.json")
    LOCK_FILE = os.path.join(DATA_DIR, "centered_text_cache.lock")


def _norm_name(name):
    """Lower-cased, accent/whitespace-folded name for robust comparison.

    MUST stay consistent with automator_utils.normalize_card_name (NFKD +
    drop-combining-marks + strip whitespace + lower) -- both sides are
    Scryfall's canonical spelling so this is only a safety net for accents.
    """
    if not name:
        return ""
    folded = unicodedata.normalize('NFKD', str(name))
    folded = ''.join(ch for ch in folded if not unicodedata.combining(ch))
    return re.sub(r'\s+', '', folded).lower()


def _cache_is_fresh(path):
    try:
        age = time.time() - os.path.getmtime(path)
    except OSError:
        return False
    data = _read_json(path)
    return data is not None and bool(data.get("cards")) and age < CACHE_TTL_SECONDS


def _read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Fetch from the Scryfall Tagger (GraphQL).  Session + CSRF token are required
# by the tagger's Rails backend, so we first load the tag page (which mints the
# session cookie and carries the csrf-token meta tag), then POST to /graphql.
# ---------------------------------------------------------------------------
def _establish_session(session):
    """Return the CSRF token, establishing the session cookie in `session`."""
    resp = session.get(TAGGER_PAGE, headers=_UA(), timeout=30)
    resp.raise_for_status()
    m = re.search(r'csrf-token" content="([^"]+)"', resp.text)
    if not m:
        raise RuntimeError(f"no csrf-token meta tag on {TAGGER_PAGE}")
    return m.group(1)


def _UA():
    return {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) ccAutomator/1.0 "
                          "(centered-text cache; contact: local user)"}


def _post_graphql(session, headers, page):
    """POST one page of the tag list, backing off on 429/5xx."""
    payload = {
        "query": _GRAPHQL_QUERY,
        "variables": {"t": TAG_TYPE, "s": TAG_SLUG, "page": page},
    }
    for attempt in range(1, _MAX_RETRIES + 1):
        resp = session.post(f"{TAGGER_BASE}/graphql", headers=headers,
                            data=json.dumps(payload), timeout=60)
        if resp.status_code in (429, 500, 502, 503, 504):
            raw = resp.headers.get("Retry-After")
            try:
                delay = max(1.0, min(float(raw), _RETRY_AFTER_CAP))
            except (TypeError, ValueError):
                delay = min(_RETRY_AFTER_CAP, 2.0 * attempt)
            print(f"   [centered-text] HTTP {resp.status_code} on page {page}; "
                  f"retrying in {delay:.0f}s (attempt {attempt}/{_MAX_RETRIES})",
                  file=sys.stderr)
            time.sleep(delay)
            continue
        resp.raise_for_status()
        return resp.json()
    raise RuntimeError(f"exhausted {_MAX_RETRIES} retries fetching page {page}")


def fetch_centered_cards(verbose=True):
    """Fetch every print tagged 'centered text'.

    Returns a dict keyed by lower-cased card name:
        { "abomination": {"name": "Abomination", "set": "leg",
                          "collector": "87", "oracle_id": "..."}, ... }
    The FIRST (by name order) print seen for a name is kept for provenance.
    Raises on network/protocol failure -- callers decide the fallback.
    """
    session = requests.Session()
    token = _establish_session(session)
    headers = {**_UA(), "X-CSRF-Token": token, "Content-Type": "application/json"}

    cards = {}
    page = 1
    total = None
    while True:
        data = _post_graphql(session, headers, page)
        if data.get("errors"):
            raise RuntimeError(f"tagger GraphQL error: {data['errors']}")
        taggings = data["data"]["tagBySlug"]["taggings"]
        total = taggings["total"]
        results = taggings.get("results") or []
        if verbose:
            print(f"   [centered-text] page {page}: {len(results)} taggings "
                  f"({total} total, {len(cards)} unique cards so far)")
        if not results:
            break  # empty page is the authoritative end of the tag list
        for res in results:
            c = res.get("card") or {}
            name = (c.get("name") or "").strip()
            if not name:
                continue
            key = name.lower()
            if key not in cards:
                cards[key] = {
                    "name": name,
                    "set": c.get("set"),
                    "collector": c.get("collectorNumber"),
                    "oracle_id": c.get("oracleId"),
                }
        page += 1
        time.sleep(0.5)
    if not cards:
        raise RuntimeError("tagger returned no centered-text taggings")
    return cards


# ---------------------------------------------------------------------------
# Cache lifecycle
# ---------------------------------------------------------------------------
def update_centered_text_cache(force=False, verbose=True):
    """Fetch from the tagger and write the JSON cache atomically.

    Returns True only when a usable cache is in place afterwards.  Network
    failures are reported (and False returned) so callers can fall back to the
    last good cache instead of believing the update succeeded.
    """
    lock_dir = os.path.dirname(LOCK_FILE)
    if lock_dir:
        os.makedirs(lock_dir, exist_ok=True)
    lock_path = os.path.abspath(LOCK_FILE)
    if not os.path.exists(lock_path):
        open(lock_path, "a").close()

    with open(lock_path, "r") as lock_f:
        try:
            fcntl.flock(lock_f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("   [centered-text] another process is updating the cache; "
                  "waiting...", file=sys.stderr)
            fcntl.flock(lock_f, fcntl.LOCK_SH)
            if _cache_is_fresh(CACHE_FILE) or (not force and _read_json(CACHE_FILE) is not None):
                print("   [centered-text] cache ready (updated by another process).")
                return True
            print("   [centered-text] WARNING: no usable cache after waiting.",
                  file=sys.stderr)
            return False

        try:
            if not force and _cache_is_fresh(CACHE_FILE):
                if verbose:
                    print("   [centered-text] cache fresh; not re-fetching.")
                return True

            if verbose:
                print("   [centered-text] fetching 'centered text' tag from the Scryfall Tagger...")
            try:
                cards = fetch_centered_cards(verbose=verbose)
            except Exception as e:
                print(f"   [centered-text] ERROR: fetch failed: {e}", file=sys.stderr)
                return False

            payload = {
                "tag": TAG_SLUG,
                "tag_type": TAG_TYPE,
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "unique_cards": len(cards),
                "cards": cards,
            }
            tmp = CACHE_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False, indent=1)
                fh.write("\n")
            os.replace(tmp, CACHE_FILE)
            if verbose:
                print(f"   [centered-text] cache written: {len(cards)} unique cards -> {CACHE_FILE}")
            return True
        finally:
            try:
                fcntl.flock(lock_f, fcntl.LOCK_UN)
            except OSError:
                pass


def load_centered_text_cache():
    """Return the cached {lower_name: info} dict, or {} when absent/corrupt."""
    data = _read_json(CACHE_FILE)
    if not data:
        return {}
    cards = data.get("cards")
    return cards if isinstance(cards, dict) else {}


def is_centered_text(name, allow_fetch=True, verbose=True):
    """True if `name` was printed with centered text.

    Ensures a cache is present (fetching once when missing/stale, if allowed and
    the network works); on any failure it still answers from the LAST GOOD
    cache rather than raising, so an offline run degrades to "no auto-centering"
    instead of an error.
    """
    if not name:
        return False
    cache = load_centered_text_cache()
    if not cache and allow_fetch:
        if update_centered_text_cache(verbose=verbose):
            cache = load_centered_text_cache()
    if not cache:
        return False
    key = str(name).strip().lower()
    if key in cache:
        return True
    norm = _norm_name(name)
    if norm:
        # Accent/whitespace-tolerant fallback (e.g. 'Ghazban Ogre' vs 'Ghazbán
        # Ogre').  The cache is small (~500 names), so a linear scan is fine.
        return any(_norm_name(k) == norm for k in cache)
    return False


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--force", action="store_true", help="re-fetch even if fresh")
    ap.add_argument("--show", metavar="NAME", help="check one card name and exit")
    args = ap.parse_args()
    if args.show:
        print(f"{args.show!r}: {'CENTERED' if is_centered_text(args.show) else 'not centered'}")
    else:
        ok = update_centered_text_cache(force=args.force)
        print("cache ok" if ok else "cache failed")
