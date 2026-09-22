"""Tests for scryfall_cache (H9 residual fix).

Covers:
  * _iter_json_array_elements -- streaming JSON array parsing (chunk
    boundaries, unicode, error cases),
  * _db_is_usable -- zero-byte / empty / valid / non-DB files,
  * update_scryfall_cache -- the H9 false-success regression (a network
    failure must NOT be reported as "another instance" + True), failure
    cooldown, lock contention with/without a usable DB, a full fake-download
    success path (incl. batched inserts), the zero-row guard, and the
    fresh-cache short-circuit,
  * ScryfallCache.get_card -- API-fallback contract: None on a failed
    update, and NO empty 0-byte DB left behind.

Run: .venv/bin/python test_scryfall_cache.py
"""
import json
import os
import sqlite3
import sys
import tempfile
import time

import fcntl
import requests

import scryfall_cache as sc


def _reset_module_state(tmpdir):
    """Point the module's file globals at tmpdir and clear shared state."""
    sc.DATA_DIR = tmpdir
    sc.DB_FILE = os.path.join(tmpdir, "scryfall_cache.db")
    sc.JSON_FILE = os.path.join(tmpdir, "scryfall_default_cache.json")
    sc.LOCK_FILE = os.path.join(tmpdir, "scryfall_cache.lock")
    sc._data_dir_explicit = False
    sc._update_failed_at = None
    sc.ScryfallCache._instance = None
    sc.ScryfallCache._conn = None


def _make_db(path, rows):
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE cards (name TEXT, set_code TEXT, data TEXT)")
    for r in rows:
        conn.execute("INSERT INTO cards VALUES (?, ?, ?)", r)
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# _iter_json_array_elements
# ---------------------------------------------------------------------------

def test_iter_basic():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "cards.json")
        cards = [{"name": "Tundra", "set": "3ED"}, {"name": "Island", "set": "C15"},
                 {"name": "Swamp", "set": "MA"}]
        with open(p, "w") as f:
            json.dump(cards, f)
        assert list(sc._iter_json_array_elements(p)) == cards


def test_iter_whitespace_unicode_nested():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "cards.json")
        text = '  [ \n {"name": "Ääropah", "oracle_text": "Il est en or ★",\n' \
               '"layout": {"a": [1, 2], "b": {"c": null}}}, 7, "plain", true ]  \n'
        with open(p, "w", encoding="utf-8") as f:
            f.write(text)
        expected = json.loads(text)
        assert list(sc._iter_json_array_elements(p)) == expected


def test_iter_chunk_boundaries():
    # Elements LARGER than the chunk size force the fill/retry path many
    # times (mid-object chunk boundaries, including inside strings).
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "cards.json")
        cards = [{"name": f"Card {i:04d}", "oracle_text": "x" * 300} for i in range(50)]
        with open(p, "w") as f:
            json.dump(cards, f)
        assert list(sc._iter_json_array_elements(p, chunk_size=16)) == cards


def test_iter_empty_array():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "cards.json")
        with open(p, "w") as f:
            f.write("[]")
        assert list(sc._iter_json_array_elements(p)) == []


def test_iter_error_cases():
    with tempfile.TemporaryDirectory() as d:
        cases = {
            "truncated.json": '[{"name": "Tundra", "set": "3E',      # cut mid-object
            "notarray.json": '{"name": "Tundra"}',                    # no top-level array
            "empty.json": "",                                         # empty file
        }
        for name, text in cases.items():
            p = os.path.join(d, name)
            with open(p, "w") as f:
                f.write(text)
            try:
                list(sc._iter_json_array_elements(p))
            except ValueError:
                pass
            else:
                raise AssertionError(f"{name}: expected ValueError, got none")


# ---------------------------------------------------------------------------
# _db_is_usable
# ---------------------------------------------------------------------------

def test_db_is_usable():
    with tempfile.TemporaryDirectory() as d:
        # missing
        assert not sc._db_is_usable(os.path.join(d, "nope.db"))
        # zero-byte file (what sqlite3.connect() creates)
        zero = os.path.join(d, "zero.db")
        open(zero, "wb").close()
        assert not sc._db_is_usable(zero)
        # non-DB binary
        garbage = os.path.join(d, "garbage.db")
        with open(garbage, "wb") as f:
            f.write(b"not a sqlite database" * 10)
        assert not sc._db_is_usable(garbage)
        # valid, non-empty
        good = os.path.join(d, "good.db")
        _make_db(good, [("tundra", "3ed", json.dumps({"name": "Tundra"}))])
        assert sc._db_is_usable(good)
        # valid but empty table
        empty = os.path.join(d, "empty.db")
        _make_db(empty, [])
        assert not sc._db_is_usable(empty)


# ---------------------------------------------------------------------------
# update_scryfall_cache -- failure honesty (the H9 regression)
# ---------------------------------------------------------------------------

def _raise_connection_error(*args, **kwargs):
    raise requests.exceptions.ConnectionError("simulated network down")


def test_update_network_failure_returns_false():
    """THE H9 BUG: a request failure must not be reported as
    'another instance updated the cache' + True."""
    with tempfile.TemporaryDirectory() as d:
        _reset_module_state(d)
        orig_get = requests.get
        requests.get = _raise_connection_error
        try:
            result = sc.update_scryfall_cache()
        finally:
            requests.get = orig_get
        assert result is False, f"network failure reported as {result!r} (old bug: True)"
        assert not os.path.exists(sc.DB_FILE), "no DB should exist after a failed update"


def test_update_failure_cooldown_throttles_retries():
    with tempfile.TemporaryDirectory() as d:
        _reset_module_state(d)
        calls = {"n": 0}

        def counting_raise(*args, **kwargs):
            calls["n"] += 1
            raise requests.exceptions.ConnectionError("simulated network down")

        orig_get = requests.get
        requests.get = counting_raise
        try:
            assert sc.update_scryfall_cache() is False      # attempt 1
            assert sc.update_scryfall_cache() is False      # throttled (no call)
            assert calls["n"] == 1, f"cooldown did not throttle: {calls['n']} calls"
            sc._update_failed_at = time.time() - sc._UPDATE_RETRY_COOLDOWN - 1
            assert sc.update_scryfall_cache() is False      # cooldown expired -> retry
            assert calls["n"] == 2
        finally:
            requests.get = orig_get


def test_contention_with_usable_db_returns_true():
    with tempfile.TemporaryDirectory() as d:
        _reset_module_state(d)
        _make_db(sc.DB_FILE, [("tundra", "3ed", json.dumps({"name": "Tundra"}))])
        flock_calls = []

        def fake_flock(fd, op):
            if op & fcntl.LOCK_EX and op & fcntl.LOCK_NB:
                raise BlockingIOError("simulated contention")
            flock_calls.append(op)

        orig_flock = fcntl.flock
        fcntl.flock = fake_flock
        try:
            assert sc.update_scryfall_cache() is True
        finally:
            fcntl.flock = orig_flock
        assert fcntl.LOCK_SH in flock_calls, "should have waited on a shared lock"


def test_contention_without_db_returns_false():
    with tempfile.TemporaryDirectory() as d:
        _reset_module_state(d)

        def fake_flock(fd, op):
            if op & fcntl.LOCK_EX and op & fcntl.LOCK_NB:
                raise BlockingIOError("simulated contention")

        orig_flock = fcntl.flock
        fcntl.flock = fake_flock
        try:
            # Old code returned True here unconditionally.
            assert sc.update_scryfall_cache() is False
        finally:
            fcntl.flock = orig_flock


def test_contention_force_stale_db_returns_false():
    with tempfile.TemporaryDirectory() as d:
        _reset_module_state(d)
        _make_db(sc.DB_FILE, [("tundra", "3ed", json.dumps({"name": "Tundra"}))])
        old = time.time() - 8 * 86400  # 8 days old -> a forced update wants FRESH
        os.utime(sc.DB_FILE, (old, old))

        def fake_flock(fd, op):
            if op & fcntl.LOCK_EX and op & fcntl.LOCK_NB:
                raise BlockingIOError("simulated contention")

        orig_flock = fcntl.flock
        fcntl.flock = fake_flock
        try:
            assert sc.update_scryfall_cache(force=True) is False
        finally:
            fcntl.flock = orig_flock


# ---------------------------------------------------------------------------
# update_scryfall_cache -- success path (fake download)
# ---------------------------------------------------------------------------

class _FakeResp:
    def __init__(self, json_obj=None, chunks=None):
        self._json = json_obj
        self._chunks = chunks or []

    def raise_for_status(self):
        pass

    def json(self):
        assert self._json is not None
        return self._json

    def iter_content(self, chunk_size):
        for c in self._chunks:
            yield c


def _fake_scryfall_get(payload_cards, call_counter):
    def fake_get(url, **kwargs):
        call_counter["n"] += 1
        if url == sc.BULK_DATA_INFO_URL:
            return _FakeResp(json_obj={"data": [
                {"type": "other_thing", "download_uri": "https://fake/nope.json"},
                {"type": "default_cards", "download_uri": "https://fake/cards.json"},
            ]})
        assert url == "https://fake/cards.json"
        assert kwargs.get("stream") is True
        assert kwargs.get("timeout") is not None, "download must have a timeout"
        return _FakeResp(chunks=[json.dumps(payload_cards).encode("utf-8")])
    return fake_get


def test_update_success_full_path():
    with tempfile.TemporaryDirectory() as d:
        _reset_module_state(d)
        cards = [{"name": "Tundra", "set": "3ED", "oracle_text": "Add {U} or {C}."},
                 {"name": "Island", "set": "C15", "oracle_text": "Add {U}."}]
        counter = {"n": 0}
        orig_get = requests.get
        requests.get = _fake_scryfall_get(cards, counter)
        try:
            assert sc.update_scryfall_cache() is True
        finally:
            requests.get = orig_get
        assert sc._db_is_usable(sc.DB_FILE)
        assert not os.path.exists(sc.JSON_FILE), "downloaded JSON should be cleaned up"
        assert not os.path.exists(sc.DB_FILE + ".tmp"), "temp DB should be gone after swap"
        got = sc.ScryfallCache().get_card("Tundra", "3ED")
        assert got == cards[0], f"get_card round-trip mismatch: {got!r}"
        assert sc._update_failed_at is None


def test_update_success_batches_many_cards():
    # 1503 cards crosses the 1000-row batch boundary.
    with tempfile.TemporaryDirectory() as d:
        _reset_module_state(d)
        cards = [{"name": f"Card {i:04d}", "set": "TST", "oracle_text": "x" * 200}
                 for i in range(1503)]
        counter = {"n": 0}
        orig_get = requests.get
        requests.get = _fake_scryfall_get(cards, counter)
        try:
            assert sc.update_scryfall_cache() is True
        finally:
            requests.get = orig_get
        conn = sqlite3.connect(f"file:{sc.DB_FILE}?mode=ro", uri=True)
        n = conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0]
        conn.close()
        assert n == 1503, f"expected 1503 rows, got {n}"


def test_update_zero_rows_refuses_to_install():
    with tempfile.TemporaryDirectory() as d:
        _reset_module_state(d)
        counter = {"n": 0}
        orig_get = requests.get
        requests.get = _fake_scryfall_get([], counter)
        try:
            assert sc.update_scryfall_cache() is False
        finally:
            requests.get = orig_get
        assert not sc._db_is_usable(sc.DB_FILE), "zero-row cache must not be installed"
        assert not os.path.exists(sc.DB_FILE), "no DB file at all should remain"


def test_fresh_cache_short_circuits_update():
    with tempfile.TemporaryDirectory() as d:
        _reset_module_state(d)
        _make_db(sc.DB_FILE, [("tundra", "3ed", json.dumps({"name": "Tundra"}))])

        def boom(*a, **k):
            raise AssertionError("requests.get must not be called for a fresh cache")

        orig_get = requests.get
        requests.get = boom
        try:
            assert sc.update_scryfall_cache() is True
        finally:
            requests.get = orig_get


# ---------------------------------------------------------------------------
# update_scryfall_cache -- dev-box guard
# ---------------------------------------------------------------------------

def test_missing_default_dir_no_download_attempt():
    """When the default data dir does not exist on this machine (dev box),
    a card lookup must NOT create it or start a ~500MB download -- it simply
    falls back to the API."""
    saved_env = os.environ.pop("CC_AUTOMATOR_DATA_DIR", None)
    try:
        with tempfile.TemporaryDirectory() as d:
            _reset_module_state(d)
            missing = os.path.join(d, "does-not-exist-yet")
            sc.DB_FILE = os.path.join(missing, "scryfall_cache.db")
            sc.JSON_FILE = os.path.join(missing, "scryfall_default_cache.json")
            sc.LOCK_FILE = os.path.join(missing, "scryfall_cache.lock")

            def boom(*a, **k):
                raise AssertionError("no network traffic expected")

            orig_get = requests.get
            requests.get = boom
            try:
                assert sc.update_scryfall_cache() is False
            finally:
                requests.get = orig_get
            assert not os.path.exists(missing), "must not create the data dir"
    finally:
        if saved_env is not None:
            os.environ["CC_AUTOMATOR_DATA_DIR"] = saved_env


# ---------------------------------------------------------------------------
# get_card fallback contract
# ---------------------------------------------------------------------------

def test_get_card_falls_back_to_none_without_leaving_empty_db():
    with tempfile.TemporaryDirectory() as d:
        _reset_module_state(d)
        orig_get = requests.get
        requests.get = _raise_connection_error
        try:
            cache = sc.ScryfallCache()
            assert cache.get_card("Tundra", "3ED") is None
            assert cache.get_card("Tundra") is None
        finally:
            requests.get = orig_get
        assert not os.path.exists(sc.DB_FILE), \
            "a failed update must not leave an empty 0-byte DB 'fresh' for a week"


def test_configure_data_dir_repoints_and_resets_singleton():
    """--data-dir wiring: configure() repoints the file globals, opts in to
    bootstrapping the explicit dir, and drops any stale singleton connection
    (a DB opened for a previous location must not be served from the new one)."""
    with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2:
        # Singleton bound to d1's DB first...
        _reset_module_state(d1)
        _make_db(sc.DB_FILE, [("island", "c15", json.dumps({"name": "Island"}))])
        cache = sc.ScryfallCache()
        assert cache.get_card("Island", "C15") is not None
        # ...then --data-dir d2 must not answer from d1's rows.
        sc.configure_data_dir(d2)
        assert sc.DATA_DIR == os.path.abspath(d2)
        assert sc.DB_FILE == os.path.join(os.path.abspath(d2), "scryfall_cache.db")
        assert sc._data_dir_explicit is True
        assert sc.ScryfallCache._instance is None and sc.ScryfallCache._conn is None
        assert sc._db_is_usable(sc.DB_FILE) is False, "d2 has no DB yet"
        # An explicit (even not-yet-existing) dir is an opt-in: the dev-box
        # guard must NOT block a bootstrap attempt.
        missing = os.path.join(d2, "subdir")
        sc.configure_data_dir(missing)
        assert sc._cache_dir_ready() is True, \
            "an explicit --data-dir must be allowed to bootstrap its directory"
        # And lookups stay honest: no DB there -> get_card -> None (offline),
        # with NO empty DB installed in the fresh location.
        orig_get = requests.get
        requests.get = _raise_connection_error
        try:
            assert sc.ScryfallCache().get_card("Island", "C15") is None
        finally:
            requests.get = orig_get
        assert not os.path.exists(os.path.join(missing, "scryfall_cache.db"))


# ---------------------------------------------------------------------------
# runner
# ---------------------------------------------------------------------------

def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS {t.__name__}")
        except Exception as e:
            failed += 1
            import traceback
            print(f"  FAIL {t.__name__}: {e}")
            traceback.print_exc()
    print(f"{len(tests) - failed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
