"""Tests for CardConjurerAutomator._resolve_prints_cache_first (the local
Scryfall-cache print resolver, #5).

The resolver must apply the plain column filters of the API query
(not:token, -layout:art-series, game:paper, set include/exclude) to cached
bulk data, keep the release-oldest-first order, and return None -- meaning
"fall back to the Scryfall API" -- for anything it cannot handle locally.

Regression covered: the paper filter read the `game` field, but current
Scryfall JSON stores a `games` LIST (["paper", "mtgo"]); with the old code
every print was dropped and the cache path was dead (silent API fallback).
Legacy rows with a `game` STRING ("paper+arena") must still match.

The automator is built with __new__ (no browser) -- only scryfall_filter is
set, which is all the resolver reads off self.

Run: .venv/bin/python test_cache_first_resolve.py
"""
import json
import os
import sqlite3
import sys
import tempfile

import requests

import scryfall_cache as sc
from automator import CardConjurerAutomator


def _reset_module_state(tmpdir):
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


def _card(name, s, **kw):
    base = {"name": name, "set": s, "layout": "normal",
            "collector_number": kw.pop("cn", "1")}
    base.update(kw)
    return base


def _stub_automator(scryfall_filter=None):
    a = CardConjurerAutomator.__new__(CardConjurerAutomator)
    a.scryfall_filter = scryfall_filter
    return a


def _sets(resolved):
    return [c["set"] for c in resolved]


# ---------------------------------------------------------------------------
# basic filtering (the games regression)
# ---------------------------------------------------------------------------

def test_games_list_paper_kept_nonpaper_dropped():
    """CURRENT SCHEMA: `games` is a list. The old c.get('game') code dropped
    EVERYTHING (the silent-never-works bug this test guards)."""
    with tempfile.TemporaryDirectory() as d:
        _reset_module_state(d)
        rows = [
            ("testslime", "aaa", json.dumps(_card("Testslime", "AAA", games=["paper"], released_at="2020-01-01"))),
            ("testslime", "bbb", json.dumps(_card("Testslime", "BBB", games=["paper", "mtgo"], released_at="2021-01-01"))),
            ("testslime", "ccc", json.dumps(_card("Testslime", "CCC", games=["mtgo"], released_at="2022-01-01"))),
            ("testslime", "ddd", json.dumps(_card("Testslime", "DDD", games=["arena"], released_at="2023-01-01"))),
        ]
        _make_db(sc.DB_FILE, rows)
        a = _stub_automator()
        resolved = a._resolve_prints_cache_first("Testslime", False, None, set(), set())
        assert resolved is not None, "paper prints must resolve locally"
        assert _sets(resolved) == ["AAA", "BBB"], _sets(resolved)  # oldest-first, non-paper dropped


def test_legacy_game_string_still_matches():
    """Pre-rename bulk data stored a `game` STRING like 'paper+arena'."""
    with tempfile.TemporaryDirectory() as d:
        _reset_module_state(d)
        rows = [
            ("testslime", "eee", json.dumps(_card("Testslime", "EEE", game="paper+arena", released_at="2019-01-01"))),
            ("testslime", "fff", json.dumps(_card("Testslime", "FFF", game="mtgo", released_at="2020-01-01"))),
            ("testslime", "ggg", json.dumps(_card("Testslime", "GGG", released_at="2021-01-01"))),  # no field at all
        ]
        _make_db(sc.DB_FILE, rows)
        a = _stub_automator()
        resolved = a._resolve_prints_cache_first("Testslime", False, None, set(), set())
        assert _sets(resolved) == ["EEE"], _sets(resolved)


def test_token_and_art_series_layouts():
    with tempfile.TemporaryDirectory() as d:
        _reset_module_state(d)
        rows = [
            ("testslime", "aaa", json.dumps(_card("Testslime", "AAA", games=["paper"], released_at="2020-01-01"))),
            ("testslime", "taaa", json.dumps(_card("Testslime Token", "tAAA", layout="token", games=["paper"], released_at="2020-06-01"))),
            ("testslime", "ass", json.dumps(_card("Testslime", "ASS", layout="art_series", games=["paper"], released_at="2021-01-01"))),
        ]
        _make_db(sc.DB_FILE, rows)
        a = _stub_automator()
        # Non-token search: token and art-series prints excluded (not:token, -layout:art-series).
        assert _sets(a._resolve_prints_cache_first("Testslime", False, None, set(), set())) == ["AAA"]
        # Token search: ONLY the token layout matches (is:token) -- no paper requirement.
        tok = a._resolve_prints_cache_first("Testslime", True, None, set(), set())
        assert tok is not None and _sets(tok) == ["tAAA"]


def test_set_include_exclude_and_target():
    with tempfile.TemporaryDirectory() as d:
        _reset_module_state(d)
        rows = [
            ("testslime", "aaa", json.dumps(_card("Testslime", "AAA", games=["paper"], released_at="2020-01-01"))),
            ("testslime", "bbb", json.dumps(_card("Testslime", "BBB", games=["paper"], released_at="2021-01-01"))),
            ("testslime", "30a", json.dumps(_card("Testslime", "30A", games=["paper"], released_at="2022-01-01"))),
        ]
        _make_db(sc.DB_FILE, rows)
        a = _stub_automator()
        # exclude-set (like custom.conf's --exclude-set 30a,sld,pblb)
        assert _sets(a._resolve_prints_cache_first("Testslime", False, None, set(), {"30a", "sld", "pblb"})) == ["AAA", "BBB"]
        # include-set restricts
        assert _sets(a._resolve_prints_cache_first("Testslime", False, None, {"bbb", "ccc"}, set())) == ["BBB"]
        # explicit --set target
        assert _sets(a._resolve_prints_cache_first("Testslime", False, "30A", set(), set())) == ["30A"]
        # target that no local print satisfies -> None (API path, its fallback widening applies)
        assert a._resolve_prints_cache_first("Testslime", False, "zzz", set(), set()) is None


def test_custom_scryfall_filter_forces_api_path():
    with tempfile.TemporaryDirectory() as d:
        _reset_module_state(d)
        _make_db(sc.DB_FILE, [
            ("testslime", "aaa", json.dumps(_card("Testslime", "AAA", games=["paper"], released_at="2020-01-01"))),
        ])
        a = _stub_automator(scryfall_filter="lang:en")
        # An arbitrary Scryfall query cannot be applied to local data.
        assert a._resolve_prints_cache_first("Testslime", False, None, set(), set()) is None


def test_unknown_card_returns_none():
    with tempfile.TemporaryDirectory() as d:
        _reset_module_state(d)
        _make_db(sc.DB_FILE, [
            ("testslime", "aaa", json.dumps(_card("Testslime", "AAA", games=["paper"], released_at="2020-01-01"))),
        ])
        a = _stub_automator()
        assert a._resolve_prints_cache_first("Not A Card", False, None, set(), set()) is None


def test_no_cache_returns_none_without_network():
    """DEFAULT dir absent on this machine (dev box): the resolver must fall
    back to the API path (None) with NO download attempt (dev-box guard)."""
    with tempfile.TemporaryDirectory() as d:
        _reset_module_state(d)
        missing = os.path.join(d, "does-not-exist-yet")
        sc.DB_FILE = os.path.join(missing, "scryfall_cache.db")
        sc.JSON_FILE = os.path.join(missing, "scryfall_default_cache.json")
        sc.LOCK_FILE = os.path.join(missing, "scryfall_cache.lock")
        calls = {"n": 0}

        def boom(*a, **k):
            calls["n"] += 1
            raise requests.exceptions.ConnectionError("no network expected")

        orig_get = requests.get
        requests.get = boom
        try:
            a = _stub_automator()
            assert a._resolve_prints_cache_first("Testslime", False, None, set(), set()) is None
        finally:
            requests.get = orig_get
        assert calls["n"] == 0, "no network traffic expected for a dev-box cache miss"
        assert not os.path.exists(missing), "must not create the default data dir"


def test_result_order_is_oldest_first():
    """Selection 'earliest' takes result[0] assuming oldest-first order --
    get_prints must keep the released_at ordering the API path gives (order_by
    released asc)."""
    with tempfile.TemporaryDirectory() as d:
        _reset_module_state(d)
        rows = [  # deliberately inserted newest-first
            ("testslime", "ccc", json.dumps(_card("Testslime", "CCC", games=["paper"], released_at="2023-01-01"))),
            ("testslime", "aaa", json.dumps(_card("Testslime", "AAA", games=["paper"], released_at="2020-01-01"))),
            ("testslime", "bbb", json.dumps(_card("Testslime", "BBB", games=["paper"], released_at="2021-01-01"))),
        ]
        _make_db(sc.DB_FILE, rows)
        a = _stub_automator()
        assert _sets(a._resolve_prints_cache_first("Testslime", False, None, set(), set())) == ["AAA", "BBB", "CCC"]


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
