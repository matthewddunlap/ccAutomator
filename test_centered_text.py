"""Tests for rules-text centering: the {center}/{left}/{right} tag, the
per-card override map (text_layout_map.json), the layout resolver, and the
Scryfall 'centered text' offline cache lookup.

Run:  python3 test_centered_text.py
Pure-function + offline-cache tests: no browser, no network.
"""
import sys, os, json, tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from automator_utils import (
    apply_text_tags, load_text_layout_map, resolve_text_layout,
)

passed = failed = 0
def check(name, actual, expected):
    global passed, failed
    if actual == expected:
        passed += 1
        print(f"  PASS {name}")
    else:
        failed += 1
        print(f"  FAIL {name}: got {actual!r}, want {expected!r}")


print("== apply_text_tags: alignment tag ==")
check("center prepended", apply_text_tags("Flight. (x)", align="center"), "{center}Flight. (x)")
check("left prepended", apply_text_tags("Flight. (x)", align="left"), "{left}Flight. (x)")
check("right prepended", apply_text_tags("T", align="right"), "{right}T")
check("replace center->left", apply_text_tags("{center}T", align="left"), "{left}T")
check("idempotent center", apply_text_tags("{center}T", align="center"), "{center}T")
check("with size/pos tags", apply_text_tags("T", down=3, fontsize=7, align="center"), "{center}{down3}{fontsize7}T")
check("positional {left40} preserved", apply_text_tags("{left40}T", align="center"), "{center}{left40}T")
check("positional {up5} preserved", apply_text_tags("{up5}T", align="left"), "{left}{up5}T")
check("coexists with bold", apply_text_tags("{bold}T{/bold}", align="center"), "{center}{bold}T{/bold}")
check("align=None leaves {center} intact", apply_text_tags("{center}T", align=None), "{center}T")
check("align=None is a no-op", apply_text_tags("T", align=None), "T")
check("invalid align ignored", apply_text_tags("T", align="diagonal"), "T")
check("multi-line centered", apply_text_tags("L1\nL2", align="center"), "{center}L1\nL2")
check("swap center->right", apply_text_tags("{center}L1\nL2", align="right"), "{right}L1\nL2")

# Idempotency: re-applying the same align to already-aligned text is a no-op.
once = apply_text_tags("Sacrifice an artifact.", down=3, align="center")
twice = apply_text_tags(once, down=3, align="center")
check("re-apply same align is a no-op", twice, once)

print("== load_text_layout_map ==")
fd, p = tempfile.mkstemp(suffix=".json"); os.close(fd)
with open(p, "w") as f:
    json.dump({"_comment": "x", "Lightning Bolt": "left", "My Card": "CENTER",
               "bad": "diagonal", "Ghazbán Ogre": "right"}, f)
m = load_text_layout_map(p)
os.unlink(p)
check("map keys lower-cased", set(m), {"lightning bolt", "my card", "ghazbán ogre"})
check("map values normalized", m["my card"], "center")
check("invalid value dropped", "bad" in m, False)

fd, p = tempfile.mkstemp(suffix=".json"); os.close(fd)
with open(p, "w") as f:
    f.write("[1, 2, 3]")
check("malformed -> {}", load_text_layout_map(p), {})
os.unlink(p)
check("missing -> {}", load_text_layout_map("/no/such/file.json"), {})

print("== resolve_text_layout: precedence ==")
def centered(name):
    return name.strip().lower() in {"counterspell", "lightning bolt"}

check("override beats auto (left wins)", resolve_text_layout("Lightning Bolt", {"lightning bolt": "left"}, centered), "left")
check("auto-center when untagged-free", resolve_text_layout("Counterspell", {}, centered), "center")
check("override-only center", resolve_text_layout("My Card", {"my card": "center"}, None), "center")
check("default None when nothing", resolve_text_layout("Serra Angel", {}, centered), None)
check("accent-tolerant override", resolve_text_layout("Ghazban Ogre", {"ghazbán ogre": "right"}, None), "right")
check("override-only mode ignores tag", resolve_text_layout("Counterspell", {}, None), None)
check("empty name -> None", resolve_text_layout("", {"x": "center"}, centered), None)
check("resolver swallows a raising predicate",
      resolve_text_layout("X", {}, lambda n: 1/0), None)

print("== centered_text: offline cache lookup (temp data dir) ==")
# Point the module at a throwaway data dir with a known cache, so this test is
# deterministic and needs no network.
tmpdir = tempfile.mkdtemp()
os.environ["CC_AUTOMATOR_DATA_DIR"] = tmpdir
import importlib
import centered_text
importlib.reload(centered_text)
cache = {"counterspell": {"name": "Counterspell", "set": "lec", "collector": "144", "oracle_id": "o1"},
         "ghazbán ogre": {"name": "Ghazbán Ogre", "set": "lea", "collector": "30", "oracle_id": "o2"}}
from datetime import datetime, timezone
payload = {"tag": "centered-text", "updated_at": datetime.now(timezone.utc).isoformat(),
           "unique_cards": len(cache), "cards": cache}
with open(os.path.join(tmpdir, "centered_text_cache.json"), "w") as f:
    json.dump(payload, f)

check("tagged -> True", centered_text.is_centered_text("Counterspell", allow_fetch=False, verbose=False), True)
check("case-insensitive", centered_text.is_centered_text("COUNTERSPELL", allow_fetch=False, verbose=False), True)
check("accent-tolerant", centered_text.is_centered_text("Ghazban Ogre", allow_fetch=False, verbose=False), True)
check("untagged -> False", centered_text.is_centered_text("Serra Angel", allow_fetch=False, verbose=False), False)
check("empty -> False", centered_text.is_centered_text("", allow_fetch=False, verbose=False), False)
check("None -> False", centered_text.is_centered_text(None, allow_fetch=False, verbose=False), False)

# Freshness: a just-written cache is "fresh" so an update must not fetch.
check("fresh cache detected", centered_text._cache_is_fresh(centered_text.CACHE_FILE), True)

# Clean up the temp data dir + restore the env so we don't leak it.
import shutil
shutil.rmtree(tmpdir, ignore_errors=True)
del os.environ["CC_AUTOMATOR_DATA_DIR"]

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
