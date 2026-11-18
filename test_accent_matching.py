"""Tests for accent-insensitive card-name matching (sanitized decklist input).

Repro being fixed: a decklist carries accent-stripped names ('Ghazban Ogre',
'Ifh-Biff Efreet'); Scryfall and the Card Conjurer app both spell the cards
with accents ('Ghazbán Ogre', 'Ifh-Bíff Efreet').  Before the fix:

  * PrintMixin._option_name_matches compared case/whitespace only, so every
    accented dropdown option was rejected and _get_and_filter_prints returned
    [] (the app's search itself is fine -- its Scryfall `name=` query is
    accent-insensitive);
  * _match_scryfall_to_cc_prints pass 2 did `"ghazbán ogre" in "ghazban
    ogre (5ed #298)"` -> False, so even a populated CC pool never matched;
  * ScryfallCache.get_card/get_prints were exact-name SQL lookups, so a
    sanitized name always missed the local cache (wasted API calls).

Run: .venv/bin/python test_accent_matching.py
"""
import json
import os
import sqlite3
import sys
import tempfile

import scryfall_cache as sc
from automator import CardConjurerAutomator
from automator_utils import (
    normalize_card_name,
    parse_card_file,
    write_missing_list,
)
from mixins.print_mixin import PrintMixin


# ---------------------------------------------------------------------------
# normalize_card_name
# ---------------------------------------------------------------------------

def test_normalize_folds_accents_case_whitespace():
    assert normalize_card_name("Ghazban Ogre") == normalize_card_name("Ghazbán Ogre")
    assert normalize_card_name("Ifh-Biff Efreet") == normalize_card_name("Ifh-Bíff Efreet")
    assert normalize_card_name("  GHAZBAN   ogre ") == "ghazbanogre"


def test_normalize_keeps_undecomposable_chars():
    # ł does not decompose under NFKD -- it must be KEPT (dropping it would
    # let different names compare equal), not silently deleted.
    assert normalize_card_name("Łakawisa") == "łakawisa"
    assert normalize_card_name("Łakawisa") != normalize_card_name("Lakawisa")


def test_normalize_none_safe():
    assert normalize_card_name(None) == ""


# ---------------------------------------------------------------------------
# PrintMixin._option_name_matches (dropdown option vs decklist name)
# ---------------------------------------------------------------------------

def _opt(option, name):
    return PrintMixin._option_name_matches(option, name)


def test_option_match_accented_cc_sanitized_input():
    # The exact user case: CC option accented, decklist sanitized.
    assert _opt("Ghazbán Ogre (5ED #298)", "Ghazban Ogre")
    assert _opt("Ifh-Bíff Efreet (ARN #50)", "Ifh-Biff Efreet")


def test_option_match_sanitized_cc_accented_input():
    assert _opt("Ghazban Ogre (5ED #298)", "Ghazbán Ogre")


def test_option_match_does_not_cross_card_boundaries():
    # 'Ghazban Ogre' must not match the Ogress, even accent-folding.
    assert not _opt("Ghazbán Ogress (5ED #299)", "Ghazban Ogre")
    assert not _opt("Ghazban Ogress (5ED #299)", "Ghazbán Ogre")
    # Pre-existing boundary (kept): DarkRitual vs DarkRituals.
    assert not _opt("DarkRituals (XXX #1)", "DarkRitual")


def test_option_match_preserves_legacy_semantics():
    assert _opt("Dark Ritual (SLZ #38)", "DarkRitual")
    assert not _opt("Ghazban Ogre", "Ghazban Ogre")  # no (SET #n) suffix
    assert _opt("GHAZBÁN OGRE (5ED #298)", "ghazban ogre")


# ---------------------------------------------------------------------------
# _match_scryfall_to_cc_prints (Scryfall result vs CC print pool)
# ---------------------------------------------------------------------------

def _stub():
    # No browser: only the pure matching path under test is exercised.
    return CardConjurerAutomator.__new__(CardConjurerAutomator)


def _sr(name, set_code, cn):
    return {"name": name, "set": set_code, "collector_number": cn}


def _cc(text, set_name, cn, index="0"):
    return {"text": text, "set_name": set_name, "collector_number": cn, "index": index}


def test_match_scryfall_to_cc_direct_set_cn():
    """Pass 1 (set + collector number) must still work, accented or not."""
    a = _stub()
    out = a._match_scryfall_to_cc_prints(
        [_sr("Ghazbán Ogre", "5ed", "298")],
        [_cc("Ghazban Ogre (5ED #298)", "5ED", "298")],
    )
    assert len(out) == 1
    assert out[0]["scryfall_data"]["name"] == "Ghazbán Ogre"


def test_match_scryfall_to_cc_name_fallback_accent_crossing():
    """THE regression: set/CN differ (reprint not in the CC pool) so only the
    name-only pass 2 can match -- and it must do so across the accent
    boundary in BOTH directions."""
    a = _stub()
    # Sanitized CC text, accented Scryfall name (user's exact case).
    out = a._match_scryfall_to_cc_prints(
        [_sr("Ghazbán Ogre", "arn", "49")],
        [_cc("Ghazban Ogre (5ED #298)", "5ED", "298")],
    )
    assert len(out) == 1, "accent-folded name must match across the boundary"
    # Accented CC text, sanitized Scryfall name (symmetric direction).
    out = a._match_scryfall_to_cc_prints(
        [_sr("Ghazban Ogre", "zzz", "1")],
        [_cc("Ghazbán Ogre (5ED #298)", "5ED", "298")],
    )
    assert len(out) == 1


def test_match_scryfall_to_cc_name_fallback_rejects_other_cards():
    a = _stub()
    out = a._match_scryfall_to_cc_prints(
        [_sr("Ghazbán Ogress", "arn", "50")],
        [_cc("Ghazban Ogre (5ED #298)", "5ED", "298")],
    )
    assert out == [], "Ogress must not match the Ogre's prints"


# ---------------------------------------------------------------------------
# ScryfallCache: accent-insensitive fallback lookup
# ---------------------------------------------------------------------------

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
    conn.execute("CREATE INDEX idx_name ON cards(name)")
    for r in rows:
        conn.execute("INSERT INTO cards VALUES (?, ?, ?)", r)
    conn.commit()
    conn.close()


def _card(name, s, cn, released):
    return {"name": name, "set": s, "collector_number": cn, "released_at": released}


def _seed_accents_db(path):
    rows = [
        ("ghazbán ogre", "arn", json.dumps(_card("Ghazbán Ogre", "arn", "49", "1993-12-17"))),
        ("ghazbán ogre", "5ed", json.dumps(_card("Ghazbán Ogre", "5ed", "298", "1997-03-24"))),
        ("ghazbán ogress", "5ed", json.dumps(_card("Ghazbán Ogress", "5ed", "299", "1997-03-24"))),
    ]
    _make_db(path, rows)


def test_cache_get_card_sanitized_name_fallback():
    with tempfile.TemporaryDirectory() as d:
        _reset_module_state(d)
        _seed_accents_db(sc.DB_FILE)
        cache = sc.ScryfallCache()
        # Exact (canonical) spelling -- indexed fast path, unchanged.
        assert cache.get_card("Ghazbán Ogre")["name"] == "Ghazbán Ogre"
        # Sanitized decklist spelling -- the accent fallback.
        got = cache.get_card("Ghazban Ogre")
        assert got is not None, "sanitized name must resolve via fallback"
        assert got["name"] == "Ghazbán Ogre"


def test_cache_get_card_fallback_respects_set_scope():
    with tempfile.TemporaryDirectory() as d:
        _reset_module_state(d)
        _seed_accents_db(sc.DB_FILE)
        cache = sc.ScryfallCache()
        assert cache.get_card("Ghazban Ogre", "arn")["set"] == "arn"
        assert cache.get_card("Ghazban Ogre", "5ed")["set"] == "5ed"
        # Set constraint must still exclude: no print in that set.
        assert cache.get_card("Ghazban Ogre", "zzz") is None
        # Fallback must not cross the card boundary.
        assert cache.get_card("Ghazban Ogress", "arn") is None
        assert cache.get_card("Ghazban Ogress", "5ed")["name"] == "Ghazbán Ogress"


def test_cache_get_prints_sanitized_name():
    with tempfile.TemporaryDirectory() as d:
        _reset_module_state(d)
        _seed_accents_db(sc.DB_FILE)
        cache = sc.ScryfallCache()
        prints = cache.get_prints("Ghazban Ogre")
        assert [c["set"] for c in prints] == ["arn", "5ed"], \
            "ALL prints of the card, oldest first"
        # Exact path unchanged.
        assert [c["set"] for c in cache.get_prints("Ghazbán Ogre")] == ["arn", "5ed"]
        # Boundary: the Ogress is a different card.
        assert [c["set"] for c in cache.get_prints("Ghazban Ogress")] == ["5ed"]
        # Unknown card still a clean miss.
        assert cache.get_card("Totally Unknown") is None
        assert cache.get_prints("Totally Unknown") == []


# ---------------------------------------------------------------------------
# parse_card_file counts + write_missing_list
# ---------------------------------------------------------------------------

def test_parse_card_file_keeps_counts():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "deck.txt")
        with open(p, "w") as f:
            f.write("3 Urza's Tower\nOpt\n1 Ponder|TSR\n# Tokens\n1 Wisp Token\n")
        cards = parse_card_file(p)
        assert cards[0] == {"name": "Urza's Tower", "category": "deck",
                            "set": None, "count": 3}
        assert cards[1]["name"] == "Opt" and cards[1]["count"] == 1  # no prefix -> 1
        assert cards[2] == {"name": "Ponder", "category": "deck",
                            "set": "TSR", "count": 1}
        assert cards[3]["name"] == "Wisp Token" and cards[3]["category"] == "tokens"


def test_write_missing_list_format_and_location():
    with tempfile.TemporaryDirectory() as d:
        input_file = os.path.join(d, "deck.txt")
        open(input_file, "w").write("1 Ghazban Ogre\n")
        lines = ["2 Ghazban Ogre", "1 Ifh-Biff Efreet|ARN"]
        out = write_missing_list(input_file, lines)
        assert os.path.abspath(out) == os.path.join(d, "deck.txt.missing")
        with open(out) as f:
            assert f.read() == "2 Ghazban Ogre\n1 Ifh-Biff Efreet|ARN\n"
        # Re-runnable: it parses back as a decklist with the same lines.
        reparsed = parse_card_file(out)
        assert [(c["count"], c["name"], c["set"]) for c in reparsed] == \
               [(2, "Ghazban Ogre", None), (1, "Ifh-Biff Efreet", "ARN")]
        # Overwrite, not append.
        write_missing_list(input_file, ["1 Opt|INV"])
        with open(out) as f:
            assert f.read() == "1 Opt|INV\n"


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
