"""Tests for the rules-text BODY font size: the {fontsize#} tag scoped before
{flavor} (preserving the --flavor-font step-down), the per-card override map
(rules_font_map.json), and the resolver.

Run:  python3 test_rules_font_size.py
Pure-function tests: no browser, no network.
"""
import sys, os, json, tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from automator_utils import (
    apply_text_tags, apply_rules_body_font_size,
    load_rules_font_map, resolve_rules_font_size,
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


print("== apply_rules_body_font_size ==")
check("prepends to plain body", apply_rules_body_font_size("Add {B}{B}{B}.", 35), "{fontsize35}Add {B}{B}{B}.")
check("None is a no-op", apply_rules_body_font_size("T", None), "T")
check("replace 35 -> 40", apply_rules_body_font_size("{fontsize35}T", 40), "{fontsize40}T")
check("re-run same value is a no-op", apply_rules_body_font_size("{fontsize35}T", 35), "{fontsize35}T")
check("multi-line body", apply_rules_body_font_size("L1\nL2", 8), "{fontsize8}L1\nL2")
check("negative offset (shrink below frame base)", apply_rules_body_font_size("T", -15), "{fontsize-15}T")
check("decimal offset", apply_rules_body_font_size("T", 7.5), "{fontsize7.5}T")

# The critical one: the flavor step-down tag must survive a body-size write.
flav = "body{flavor}{fontsize-15}flavor text"
out = apply_rules_body_font_size(flav, 35)
check("flavor tag preserved", out, "{fontsize35}body{flavor}{fontsize-15}flavor text")
check("re-run with flavor is a no-op", apply_rules_body_font_size(out, 35), out)
check("re-run changed value keeps flavor tag",
      apply_rules_body_font_size(out, 45), "{fontsize45}body{flavor}{fontsize-15}flavor text")
# Contrast: the raw shared helper converges ALL fontsize tags to one (it lands
# where the first one stood) -- exactly what the scoping above exists to avoid:
# the -15 flavor step-down is gone and the body never gets the +35.
check("raw apply_text_tags would eat the flavor tag (contrast)",
      apply_text_tags("body{flavor}{fontsize-15}fl", fontsize=35), "body{flavor}{fontsize35}fl")
# Composes with the alignment tag the live path adds afterward.
check("coexists with {center}",
      apply_text_tags(apply_rules_body_font_size("T", 35), align="center"), "{center}{fontsize35}T")
check("coexists with {down} nudge",
      apply_text_tags(apply_rules_body_font_size("T", 35), down=13), "{down13}{fontsize35}T")

print("== load_rules_font_map ==")
fd, p = tempfile.mkstemp(suffix=".json"); os.close(fd)
with open(p, "w") as f:
    json.dump({"_comment": "x", "Dark Ritual": 45, "My Card": -10,
               "bad": "big", "bool": True, "dec": 7.5, "  Padded  ": 12}, f)
m = load_rules_font_map(p)
os.unlink(p)
check("keys lower-cased / stripped", set(m), {"dark ritual", "my card", "dec", "padded"})
check("int kept", m["dark ritual"], 45)
check("negative ok", m["my card"], -10)
check("float kept", m["dec"], 7.5)
check("non-numeric dropped", "bad" in m, False)
check("bool dropped", "bool" in m, False)

fd, p = tempfile.mkstemp(suffix=".json"); os.close(fd)
with open(p, "w") as f:
    f.write("[1, 2, 3]")
check("malformed -> {}", load_rules_font_map(p), {})
os.unlink(p)
check("missing -> {}", load_rules_font_map("/no/such/file.json"), {})

# The shipped default file must load clean and carry no active entries.
check("shipped rules_font_map.json has no active entries",
      load_rules_font_map(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                       "rules_font_map.json")), {})

print("== resolve_rules_font_size: precedence ==")
m = {"dark ritual": 45, "ghazbán ogre": 8}
check("override beats global", resolve_rules_font_size("Dark Ritual", m, default=35), 45)
check("global when unlisted", resolve_rules_font_size("Serra Angel", m, default=35), 35)
check("None when nothing set", resolve_rules_font_size("Serra Angel", {}, default=None), None)
check("override works without global", resolve_rules_font_size("Dark Ritual", m, default=None), 45)
check("case-insensitive override", resolve_rules_font_size("DARK RITUAL", m, default=None), 45)
check("accent-tolerant override", resolve_rules_font_size("Ghazban Ogre", m, default=None), 8)
check("empty name -> default", resolve_rules_font_size("", m, default=35), 35)

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
