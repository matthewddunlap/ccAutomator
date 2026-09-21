"""Unit tests for apply_text_tags (H8) + the cc_file_editor delegation path.

Run:  .venv/bin/python test_apply_text_tags.py
Pure-function tests: no browser, no network, no server.
"""
import sys, os, json, tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from automator_utils import apply_text_tags

passed = failed = 0
def check(name, actual, expected):
    global passed, failed
    if actual == expected:
        passed += 1
        print(f"  PASS {name}")
    else:
        failed += 1
        print(f"  FAIL {name}: got {actual!r}, want {expected!r}")

print("== apply_text_tags ==")
# 1. New tag prepended
check("prepend fontsize", apply_text_tags("Text", fontsize=7), "{fontsize7}Text")
check("prepend kerning negative", apply_text_tags("T", kerning=-2), "{kerning-2}T")

# 2. REPLACE in place (THE H8 scenario: re-run with CHANGED values)
check("H8 changed fontsize",
      apply_text_tags("{fontsize7}{shadow2}Text", fontsize=9),
      "{fontsize9}{shadow2}Text")
check("H8 multi-tag changed",
      apply_text_tags("{fontsize7}{shadow2}{kerning1}Text", fontsize=9, kerning=3),
      "{fontsize9}{shadow2}{kerning3}Text")

# 3. Duplicated stale tags converge to one at first position
check("converge duplicates front",
      apply_text_tags("{fontsize7}{fontsize7}{shadow2}Text", fontsize=9),
      "{fontsize9}{shadow2}Text")
check("converge duplicates mid",
      apply_text_tags("Text {kerning2} more {kerning2}", kerning=5),
      "Text {kerning5} more ")
check("converge 3 duplicates",
      apply_text_tags("{shadow1}{shadow1}{shadow1}T", shadow=2),
      "{shadow2}T")

# 4. Decimals / negatives round-trip
check("decimal new", apply_text_tags("T", left=3.5), "{left3.5}T")
check("decimal replace", apply_text_tags("{left3.5}T", left=-2.25), "{left-2.25}T")
check("negative replace", apply_text_tags("{fontsize-4}T", fontsize=4), "{fontsize4}T")

# 5. {fontsize64pt} (pt-suffix form) must NOT be treated as a fontsize tag
check("64pt untouched",
      apply_text_tags("{fontsize64pt}Text", fontsize=7),
      "{fontsize7}{fontsize64pt}Text")

# 6. Substring false-positive ({fontsize1} vs {fontsize10})
check("10 not matched by 1 (old code skipped/duplicated)",
      apply_text_tags("{fontsize10}Text", fontsize=10), "{fontsize10}Text")
check("1 replaces 10 (replace semantics)",
      apply_text_tags("{fontsize10}Text", fontsize=1), "{fontsize1}Text")

# 7. Bold idempotent; existing bold never stripped
check("bold wrap", apply_text_tags("Text", bold=True), "{bold}Text{/bold}")
check("bold idempotent", apply_text_tags("{bold}Text{/bold}", bold=True), "{bold}Text{/bold}")
check("bold=False keeps existing bold",
      apply_text_tags("{bold}Text{/bold}", fontsize=7),
      "{fontsize7}{bold}Text{/bold}")

# 8. Unchanged -> equal string (caller's no-op guard fires, no DOM write)
s = "{fontsize7}{shadow2}Text"
check("unchanged value-equal", apply_text_tags(s, fontsize=7, shadow=2), s)
check("caller no-op guard (==) fires",
      apply_text_tags(s, fontsize=7, shadow=2) == s, True)

# 9. All six kinds at once (each prepend goes to the FRONT, so the applied
#    order reads reversed — same accumulation order as the old prepend code;
#    tag order is semantically irrelevant to CardConjurer)
check("all six",
      apply_text_tags("T", fontsize=7, shadow=2, kerning=1, left=3, up=1, down=4),
      "{down4}{up1}{left3}{kerning1}{shadow2}{fontsize7}T")

print("== flavor path (simulates _apply_flavor_font_mod) ==")
def flavor_apply(text, font):
    pre, part = text.split("{flavor}", 1)
    return f"{pre}{{flavor}}{apply_text_tags(part, fontsize=font)}"

check("flavor first run", flavor_apply("Rules {flavor}Old flavor", 5),
      "Rules {flavor}{fontsize5}Old flavor")
check("flavor re-run no stack",
      flavor_apply("Rules {flavor}{fontsize5}Old flavor", 5),
      "Rules {flavor}{fontsize5}Old flavor")
check("flavor re-run changed",
      flavor_apply("Rules {flavor}{fontsize5}Old flavor", 6),
      "Rules {flavor}{fontsize6}Old flavor")

print("== cc_file_editor._update_tag delegation ==")
from cc_file_editor import CcFileEditor
def make_editor():
    with tempfile.NamedTemporaryFile("w", suffix=".cardconjurer", delete=False) as f:
        json.dump({"cards": []}, f)
        p = f.name
    ed = CcFileEditor(p)
    os.unlink(p)
    return ed

ed = make_editor()
# Unbound-safe: _update_tag only touches the shared helper.
check("delegate fontsize (kwarg mapping)", ed._update_tag("T", "fontsize", 7), "{fontsize7}T")
check("delegate kerning replace", ed._update_tag("{kerning1}T", "kerning", 4), "{kerning4}T")
check("delegate shadow new", ed._update_tag("T", "shadow", 2), "{shadow2}T")
check("delegate left", ed._update_tag("T", "left", -3), "{left-3}T")
check("delegate up", ed._update_tag("T", "up", 2), "{up2}T")
check("delegate down", ed._update_tag("T", "down", 1), "{down1}T")

print("== cc_file_editor.apply_edits re-run scenario (JSON path) ==")
import io, contextlib
def run_edits(proj, **kw):
    """apply_edits mutates the in-memory .data (save() is separate) — read it."""
    with tempfile.NamedTemporaryFile("w", suffix=".cardconjurer", delete=False) as f:
        json.dump(proj, f)
        p = f.name
    with contextlib.redirect_stdout(io.StringIO()):
        ed = CcFileEditor(p)
        ed.apply_edits(**kw)
        data = ed.data
    os.unlink(p)
    return data.get("cards", data) if isinstance(data, dict) else data

proj = {"cards": [
    {"key": "k1", "data": {
        "text": {
            "title": {"text": "Test Card"},
            "type": {"text": "Creature — Beast"},
            "pt": {"text": "2/2"},
            "rules": {"text": "Rules {flavor}Old flavor text"},
        },
        "frames": []}}]}

# Run 1: baseline values
cards = run_edits(proj, title_font_size=7, title_kerning=1, rules_down=3, flavor_font=5)
title1 = cards[0]["data"]["text"]["title"]["text"]
check("run1 title", title1, "{fontsize7}{kerning1}Test Card")
rules1 = cards[0]["data"]["text"]["rules"]["text"]
check("run1 rules", rules1, "{down3}Rules {flavor}{fontsize5}Old flavor text")

# Run 2: SAME values over run 1's output -> byte-identical (no stacking)
cards2 = run_edits({"cards": [json.loads(json.dumps(cards[0]))]},
                   title_font_size=7, title_kerning=1, rules_down=3, flavor_font=5)
check("run2 title unchanged (no duplicate tags)",
      cards2[0]["data"]["text"]["title"]["text"], title1)
check("run2 rules unchanged (no duplicate tags)",
      cards2[0]["data"]["text"]["rules"]["text"], rules1)

# Run 3: CHANGED values over run 1's output -> replace in place (THE H8 case)
cards3 = run_edits({"cards": [json.loads(json.dumps(cards[0]))]},
                   title_font_size=9, rules_down=4, flavor_font=6)
check("run3 title replaced",
      cards3[0]["data"]["text"]["title"]["text"],
      "{fontsize9}{kerning1}Test Card")
check("run3 rules replaced",
      cards3[0]["data"]["text"]["rules"]["text"],
      "{down4}Rules {flavor}{fontsize6}Old flavor text")

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
