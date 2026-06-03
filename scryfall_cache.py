import json
import os
import requests
import time
import sqlite3
from pathlib import Path
import fcntl
import random

DB_FILE = "/data/ccAutomator/scryfall_cache.db"
JSON_FILE = "/data/ccAutomator/scryfall_default_cache.json"
LOCK_FILE = "/data/ccAutomator/scryfall_cache.lock"
BULK_DATA_INFO_URL = "https://api.scryfall.com/bulk-data"

def update_scryfall_cache(force=False):
    """
    Downloads and converts Scryfall data to SQLite. 
    Uses a lock file to ensure only one process handles the update.
    """
    lock_path = Path(LOCK_FILE)
    if not lock_path.exists():
        lock_path.touch()

    with open(LOCK_FILE, 'r') as lock_f:
        try:
            # Try to acquire an exclusive lock (non-blocking)
            fcntl.flock(lock_f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            
            db_path = Path(DB_FILE)
            if not force and db_path.exists():
                file_age = time.time() - db_path.stat().st_mtime
                if file_age < 604800: # 1 week
                    return True

            # Standard random delay to spread out potential simultaneous starts
            # though flock handles the race, it's polite to the OS.
            time.sleep(random.uniform(0.1, 1.0))

            print("   --- Updating Scryfall Cache (Exclusive Lock Acquired) ---")
            
            # 1. Get Download URI
            resp = requests.get(BULK_DATA_INFO_URL, timeout=20)
            resp.raise_for_status()
            download_uri = next((item['download_uri'] for item in resp.json()['data'] if item['type'] == 'default_cards'), None)
            
            if not download_uri:
                print("   Error: Could not find default_cards download URI.")
                return False

            # 2. Download JSON
            print(f"   Downloading Scryfall data (~500MB)...")
            r = requests.get(download_uri, stream=True)
            r.raise_for_status()
            with open(JSON_FILE, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)

            # 3. Convert to SQLite
            print("   Converting JSON to SQLite DB (this saves massive RAM)...")
            temp_db = DB_FILE + ".tmp"
            if os.path.exists(temp_db):
                os.remove(temp_db)

            conn = sqlite3.connect(temp_db)
            curr = conn.cursor()
            curr.execute("CREATE TABLE cards (name TEXT, set_code TEXT, data TEXT)")
            curr.execute("CREATE INDEX idx_name ON cards(name)")
            curr.execute("CREATE INDEX idx_name_set ON cards(name, set_code)")

            with open(JSON_FILE, 'r', encoding='utf-8') as f:
                cards = json.load(f)
                
            to_insert = []
            for card in cards:
                to_insert.append((card.get('name', '').lower(), card.get('set', '').lower(), json.dumps(card)))
            
            curr.executemany("INSERT INTO cards VALUES (?, ?, ?)", to_insert)
            conn.commit()
            conn.close()

            # Atomic swap
            os.rename(temp_db, DB_FILE)

            # 4. Cleanup
            if os.path.exists(JSON_FILE):
                os.remove(JSON_FILE)
            print(f"   Cache updated and indexed. Loaded {len(cards)} prints.")
            return True

        except (BlockingIOError, IOError):
            print("   Another instance is currently updating the cache. Waiting for it to finish...")
            # Wait for the lock to be released (shared lock)
            fcntl.flock(lock_f, fcntl.LOCK_SH)
            print("   Cache update finished by another instance.")
            return True
        finally:
            try:
                fcntl.flock(lock_f, fcntl.LOCK_UN)
            except:
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
            if not Path(DB_FILE).exists():
                update_scryfall_cache()
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
        except Exception as e:
            # If the database is locked or table doesn't exist yet, return None to allow API fallback
            return None

if __name__ == "__main__":
    cache = ScryfallCache()
    card = cache.get_card("Tundra", "3ED")
    if card:
        print(f"Found: {card.get('name')} from {card.get('set_name')}")
    else:
        print("Not found.")
