import json
import os
import random
import sqlite3
import sys
import time
import fcntl
from pathlib import Path
import requests

# Data location is runtime-configurable: --data-dir (ccAutomator.py) or the
# CC_AUTOMATOR_DATA_DIR env var; the production default is unchanged.
DATA_DIR = os.environ.get("CC_AUTOMATOR_DATA_DIR", "/data/ccAutomator")
DB_FILE = os.path.join(DATA_DIR, "scryfall_cache.db")
JSON_FILE = os.path.join(DATA_DIR, "scryfall_default_cache.json")
LOCK_FILE = os.path.join(DATA_DIR, "scryfall_cache.lock")
BULK_DATA_INFO_URL = "https://api.scryfall.com/bulk-data"

# Set when the user EXPLICITLY chose the data dir (--data-dir or the env
# var) -- as opposed to inheriting the /data default.  Explicit choice is
# an opt-in to bootstrapping that location (creating it, downloading the
# bulk data into it) even on a machine where it does not exist yet.
_data_dir_explicit = os.environ.get("CC_AUTOMATOR_DATA_DIR") is not None


def configure_data_dir(path):
    """Point the cache at `path` (called from ccAutomator's --data-dir).

    Must be called before the first cache lookup (all lookups import this
    module lazily, so this is safe from main()).  Resets the singleton's
    connection so a previously opened DB for another location is never
    served from the wrong directory.
    """
    global DATA_DIR, DB_FILE, JSON_FILE, LOCK_FILE, _data_dir_explicit
    DATA_DIR = os.path.abspath(path)
    DB_FILE = os.path.join(DATA_DIR, "scryfall_cache.db")
    JSON_FILE = os.path.join(DATA_DIR, "scryfall_default_cache.json")
    LOCK_FILE = os.path.join(DATA_DIR, "scryfall_cache.lock")
    _data_dir_explicit = True
    ScryfallCache._instance = None
    ScryfallCache._conn = None

# After a failed update, don't re-attempt the bulk download for every card
# lookup (each attempt would pay the connect timeout again).  60s is long
# enough that a transient blip clears, short enough that a run started while
# offline recovers without a restart.
_UPDATE_RETRY_COOLDOWN = 60.0
_update_failed_at = None


def _db_is_usable(db_path):
    """True if the SQLite cache exists and has a non-empty `cards` table.

    The old staleness check accepted ANY existing file as fresh -- including
    a zero-byte DB that `sqlite3.connect()` creates on a failed update --
    for a full week.  A usable cache is one we can actually query.
    """
    if not Path(db_path).exists():
        return False
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            n = conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0]
        finally:
            conn.close()
        return n > 0
    except sqlite3.Error:
        return False


def _iter_json_array_elements(path, chunk_size=1 << 20):
    """Lazily yield the elements of a top-level JSON array in `path`.

    The Scryfall bulk download is one ~500MB JSON array; `json.load()` holds
    every card in memory at once (and the old conversion then held a SECOND
    copy -- a list of json.dumps'd cards -- while inserting).  This streams
    the file in chunks and parses one element at a time, so the extra memory
    is ~one chunk plus one card.
    """
    decoder = json.JSONDecoder()
    buf = ''
    pos = 0
    eof = False

    with open(path, 'r', encoding='utf-8') as f:
        def fill():
            """Read the next chunk, keeping the unconsumed tail of `buf`."""
            nonlocal buf, pos, eof
            if eof:
                return False
            chunk = f.read(chunk_size)
            if not chunk:
                eof = True
                return False
            buf = buf[pos:] + chunk
            pos = 0
            return True

        # Advance past whitespace to the opening '[' of the array.
        while True:
            c = buf[pos:pos + 1]
            if c:
                if c.isspace():
                    pos += 1
                    continue
                if c == '[':
                    pos += 1
                    break
                raise ValueError(f"{path}: invalid JSON (expected a top-level array)")
            if not fill():
                raise ValueError(f"{path}: empty or invalid JSON (expected a top-level array)")

        while True:
            # Skip whitespace / commas to the next element (or the ']').
            while True:
                c = buf[pos:pos + 1]
                if c:
                    if c == ']':
                        return  # end of array
                    if c.isspace() or c == ',':
                        pos += 1
                        continue
                    break  # first char of an element
                if not fill():
                    raise ValueError(f"{path}: truncated JSON array")
            try:
                obj, end = decoder.raw_decode(buf, pos)
            except json.JSONDecodeError:
                # Element spans a chunk boundary (or the data is corrupt).
                if not fill():
                    raise ValueError(f"{path}: invalid JSON in card array")
                continue
            pos = end
            yield obj


def _cache_dir_ready():
    """Should this machine use/try to build the cache in its data dir?

    True when the data directory already exists (the production layout), or
    when the user explicitly chose a location (--data-dir or
    CC_AUTOMATOR_DATA_DIR: opt-in bootstrap).  False for the DEFAULT
    location on a machine where it does not exist (a dev box): creating
    /data and downloading ~500MB is a production decision, not a
    dev-machine side effect -- the caller simply falls back to the
    Scryfall API.
    """
    if Path(os.path.dirname(DB_FILE)).exists():
        return True
    return _data_dir_explicit


def update_scryfall_cache(force=False):
    """
    Downloads and converts Scryfall data to SQLite.
    Uses a lock file to ensure only one process handles the update.

    Returns True ONLY if a usable cache DB is in place afterwards.
    A real failure (network error, bad download, ...) is reported as False --
    the old `except (BlockingIOError, IOError)` swallowed EVERY error in the
    whole update, including request failures, as "another instance is
    updating the cache" and returned True although nothing had been updated.
    """
    global _update_failed_at

    if not _cache_dir_ready():
        # Default cache location absent on this machine: do NOT create it or
        # start a ~500MB download as a side effect of a card lookup.
        _update_failed_at = time.time()
        return False

    # Throttle retries after a failure so a dead network does not make every
    # card lookup pay the full connect timeout (see _get_conn/get_card: the
    # update is attempted on each cache miss).
    if not force and _update_failed_at is not None and \
            time.time() - _update_failed_at < _UPDATE_RETRY_COOLDOWN:
        return False

    def failed():
        global _update_failed_at
        _update_failed_at = time.time()
        return False

    lock_path = Path(LOCK_FILE)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    if not lock_path.exists():
        lock_path.touch()

    with open(LOCK_FILE, 'r') as lock_f:
        try:
            # Try to acquire an exclusive lock (non-blocking)
            fcntl.flock(lock_f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            # Another instance GENUINELY holds the lock (the only error that
            # means that).  Wait for it to finish, then report based on
            # whether a usable -- and, when forced, fresh -- cache actually
            # exists, not on the assumption it succeeded.
            print("   Another instance is currently updating the cache. Waiting for it to finish...")
            fcntl.flock(lock_f, fcntl.LOCK_SH)
            if _db_is_usable(DB_FILE):
                file_age = time.time() - Path(DB_FILE).stat().st_mtime
                if not force or file_age < 604800:
                    _update_failed_at = None
                    print("   Cache is current (updated by another instance).")
                    return True
            print("   Warning: another instance held the cache lock but left no "
                  "usable/fresh cache; falling back to the Scryfall API for "
                  "this run.", file=sys.stderr)
            return failed()

        try:
            db_path = Path(DB_FILE)
            if not force and _db_is_usable(db_path):
                file_age = time.time() - db_path.stat().st_mtime
                if file_age < 604800:  # 1 week
                    _update_failed_at = None
                    return True

            # Standard random delay to spread out potential simultaneous starts
            # (flock handles the race; this just keeps us polite to the OS).
            time.sleep(random.uniform(0.1, 1.0))

            print("   --- Updating Scryfall Cache (Exclusive Lock Acquired) ---")

            # 1. Get Download URI
            resp = requests.get(BULK_DATA_INFO_URL, timeout=20)
            resp.raise_for_status()
            download_uri = next((item['download_uri'] for item in resp.json()['data']
                                 if item['type'] == 'default_cards'), None)

            if not download_uri:
                print("   Error: Could not find default_cards download URI.", file=sys.stderr)
                return failed()

            # 2. Download JSON (timeout: 20s to connect, 300s between chunks,
            # so a dead peer cannot hang the update forever -- the old call
            # had no timeout at all).
            print("   Downloading Scryfall data (~500MB)...")
            r = requests.get(download_uri, stream=True, timeout=(20, 300))
            r.raise_for_status()
            with open(JSON_FILE, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)

            # 3. Convert to SQLite -- streamed, so neither the whole 500MB
            # JSON nor a second copy of it is ever in memory at once.
            print("   Converting JSON to SQLite DB (this saves massive RAM)...")
            temp_db = DB_FILE + ".tmp"
            if os.path.exists(temp_db):
                os.remove(temp_db)

            conn = sqlite3.connect(temp_db)
            curr = conn.cursor()
            curr.execute("CREATE TABLE cards (name TEXT, set_code TEXT, data TEXT)")
            curr.execute("CREATE INDEX idx_name ON cards(name)")
            curr.execute("CREATE INDEX idx_name_set ON cards(name, set_code)")

            batch = []
            count = 0
            for card in _iter_json_array_elements(JSON_FILE):
                batch.append((card.get('name', '').lower(), card.get('set', '').lower(),
                              json.dumps(card)))
                if len(batch) >= 1000:
                    curr.executemany("INSERT INTO cards VALUES (?, ?, ?)", batch)
                    batch.clear()
                count += 1
            if batch:
                curr.executemany("INSERT INTO cards VALUES (?, ?, ?)", batch)

            if count == 0:
                # A zero-row "cache" would be accepted as fresh for a week by
                # the staleness check -- refuse to install one.
                conn.close()
                os.remove(temp_db)
                print("   Error: downloaded Scryfall JSON contained no cards; "
                      "cache left untouched.", file=sys.stderr)
                return failed()

            conn.commit()
            conn.close()

            # Atomic swap
            os.rename(temp_db, DB_FILE)

            # 4. Cleanup
            if os.path.exists(JSON_FILE):
                os.remove(JSON_FILE)
            _update_failed_at = None
            print(f"   Cache updated and indexed. Loaded {count} prints.")
            return True

        except (requests.RequestException, sqlite3.Error, ValueError, OSError) as e:
            # An expected failure class (network, disk, corrupt/zero-row
            # payload, ...): report the REAL error -- not "another instance"
            # -- and leave the existing cache, if any, untouched.  Callers
            # (get_card) then fall back to the Scryfall API, so a run still
            # completes; but nobody mistakes this for a successful update.
            print(f"   Error: Scryfall cache update failed: {e}", file=sys.stderr)
            return failed()
        finally:
            try:
                fcntl.flock(lock_f, fcntl.LOCK_UN)
            except OSError:
                pass


class ScryfallCache:
    _instance = None
    _conn = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(ScryfallCache, cls).__new__(cls)
        return cls._instance

    def _get_conn(self):
        if self._conn is None:
            if not _db_is_usable(DB_FILE):
                # Honest failure contract: update_scryfall_cache() returns
                # True only when the cache is usable.  Raising -- rather than
                # connecting and creating an empty 0-byte DB that would be
                # treated as "fresh" for a week -- lets get_card() fall back
                # to the API and keeps the cache dir clean.
                if not update_scryfall_cache():
                    raise RuntimeError(
                        f"Scryfall cache unavailable at {DB_FILE} and the "
                        "update failed; using the Scryfall API instead")
            self._conn = sqlite3.connect(DB_FILE)
        return self._conn

    def get_card(self, name, set_code=None):
        try:
            conn = self._get_conn()
            curr = conn.cursor()

            if set_code:
                curr.execute("SELECT data FROM cards WHERE name = ? AND set_code = ? LIMIT 1",
                           (name.lower(), set_code.lower()))
            else:
                curr.execute("SELECT data FROM cards WHERE name = ? LIMIT 1", (name.lower(),))

            row = curr.fetchone()
            if row:
                return json.loads(row[0])
            return None
        except Exception:
            # If the database is locked or table doesn't exist yet, return None to allow API fallback
            return None

    def get_prints(self, name):
        """Return EVERY print of `name` as a list of full card dicts, oldest
        first (by `released_at`).  Unlike get_card (one row), this hands the
        caller all sets so it can apply its own set-selection policy locally
        instead of round-tripping to the Scryfall search API.

        Same no-side-effect contract as get_card: never raises, returns [] on
        a cache miss or when no usable cache exists -- callers fall back to
        the API.  (On a machine without a data dir the dev-box guard keeps
        this a fast empty return, not a ~500MB download.)
        """
        try:
            conn = self._get_conn()
            curr = conn.cursor()
            curr.execute("SELECT data FROM cards WHERE name = ?", (name.lower(),))
            cards = [json.loads(row[0]) for row in curr.fetchall()]
            # released_at is a stored field ("YYYY-MM-DD"); missing ones (very
            # old prints) sort first, matching an 'earliest' preference.
            cards.sort(key=lambda c: c.get("released_at") or "")
            return cards
        except Exception:
            return []

if __name__ == "__main__":
    cache = ScryfallCache()
    card = cache.get_card("Tundra", "3ED")
    if card:
        print(f"Found: {card.get('name')} from {card.get('set_name')}")
    else:
        print("Not found.")
