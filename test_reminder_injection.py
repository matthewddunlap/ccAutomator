"""
Tests for inject_ability_reminders / load_reminder_map (the --inject-reminder-text
feature).  Run directly:  python3 test_reminder_injection.py
(or under pytest).

Conventions covered:
  - Card Conjurer text-box text: reminder segments are tagged '{i}(...) {/i}'.
  - Raw oracle text (json builder path): plain '(...)' segments.
  - The canonical map in reminder_map.json supplies the injected sentences.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from automator_utils import inject_ability_reminders, load_reminder_map

MAP = load_reminder_map(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'reminder_map.json'))
FLYING = MAP["flying"]
VIGILANCE = MAP["vigilance"]
PLAIN = lambda s: f" ({s})"  # json-builder style formatter


def check(label, cond, detail=""):
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {label}" + (f"  -> {detail}" if detail and not cond else ""))
    return cond


def run_all():
    ok = True
    print("== Serra Angel: Flying has no printed reminder, Vigilance does (tagged box text) ==")
    text = "Flying\nVigilance {i}(Attacking doesn't cause this creature to tap.){/i}"
    new, injected = inject_ability_reminders(text, MAP)
    ok &= check("only flying injected", injected == ["flying"], f"injected={injected}")
    ok &= check("flying line gains reminder",
                new.split("\n")[0] == f"Flying {{i}}({FLYING}){{/i}}", new.split("\n")[0])
    ok &= check("vigilance line untouched",
                new.split("\n")[1] == "Vigilance {i}(Attacking doesn't cause this creature to tap.){/i}")

    print("== Sengir Vampire: Flying reminder already present (tagged) ==")
    text = ("Flying {i}(This creature can't be blocked except by creatures with flying or reach.){/i}\n"
            "Whenever a creature dealt damage by this creature this turn dies, put a +1/+1 counter on this creature.")
    new, injected = inject_ability_reminders(text, MAP)
    ok &= check("no change, nothing injected", new == text and injected == [], f"injected={injected}")

    print("== Keywords inside a reminder segment must not trigger (reach/flying in Sengir's reminder) ==")
    text = ("Menace {i}(This creature can't be blocked except by creatures with flying or reach.){/i}")
    new, injected = inject_ability_reminders(text, MAP)
    ok &= check("menace satisfied; flying/reach not injected", new == text and injected == [],
                f"injected={injected}")

    print("== 'Flying, vigilance' with no reminders: both injected, in order ==")
    new, injected = inject_ability_reminders("Flying, vigilance", MAP)
    ok &= check("both injected in line order", injected == ["flying", "vigilance"], f"injected={injected}")
    ok &= check("both segments appended",
                new == f"Flying, vigilance {{i}}({FLYING}){{/i}} {{i}}({VIGILANCE}){{/i}}", new)

    print("== Idempotency (tagged and plain formatters) ==")
    once, inj1 = inject_ability_reminders("Flying, vigilance", MAP)
    twice, inj2 = inject_ability_reminders(once, MAP)
    ok &= check("second run is a no-op", once == twice and inj2 == [], f"second={twice!r} inj2={inj2}")
    once_p, _ = inject_ability_reminders("Flying, vigilance", MAP, segment_formatter=PLAIN)
    twice_p, inj2p = inject_ability_reminders(once_p, MAP, segment_formatter=PLAIN)
    ok &= check("plain formatter idempotent", once_p == twice_p and inj2p == [], f"second={twice_p!r}")

    print("== Token with a bare keyword ==")
    new, injected = inject_ability_reminders("Vigilance", MAP)
    ok &= check("vigilance injected", injected == ["vigilance"] and
                new == f"Vigilance {{i}}({VIGILANCE}){{/i}}", new)

    print("== Ward: cost is substituted; already-reminded ward is left alone ==")
    new, injected = inject_ability_reminders("Ward {1}", MAP)
    ok &= check("ward {1} reminder injected", injected == ["ward"] and
                "unless that player pays {1}." in new, new)
    text = "Ward {2} {i}(Whenever this creature becomes the target of a spell or ability an opponent " \
           "controls, counter it unless that player pays {2}.){/i}"
    new, injected = inject_ability_reminders(text, MAP)
    ok &= check("printed ward reminder not duplicated", new == text and injected == [], f"injected={injected}")
    new, injected = inject_ability_reminders("Ward {R}", MAP)
    ok &= check("ward {R} cost substituted", "pays {R}." in new, new)

    print("== Flavor tail is never touched ==")
    text = "Flying {flavor}It once said, “flying was easy.”"
    new, injected = inject_ability_reminders(text, MAP)
    ok &= check("flying injected once", injected == ["flying"], f"injected={injected}")
    ok &= check("flavor tail byte-identical",
                new.endswith("{flavor}It once said, “flying was easy.”"), new)
    ok &= check("reminder before the flavor marker",
                new.index("{/i}") < new.index("{flavor}"), new)

    print("== Word boundaries ==")
    new, injected = inject_ability_reminders("This creature has hexproof.", MAP)
    ok &= check("hexproof matched", injected == ["hexproof"], f"injected={injected}")
    new, injected = inject_ability_reminders("This spell is infectious.", MAP)
    ok &= check("'infectious' does not match infect", injected == [], f"injected={injected}")
    new, injected = inject_ability_reminders("The ward against this is strong.", MAP)
    ok &= check("'ward' as a noun still injects (acceptable) or not -- just record",
                True)  # informational only; either outcome is acceptable for v1
    print(f"      (info: 'ward as a noun' -> injected={injected})")

    print("== Multi-line reminder segment: keywords inside it don't trigger ==")
    # The generic segment is attributed to the nearest preceding keyword (reach);
    # 'flying' inside the multi-line segment must NOT itself trigger an injection.
    text = "Flying, reach (A reminder\nthat spans two lines and mentions reach.)"
    new, injected = inject_ability_reminders(text, MAP)
    ok &= check("only 'flying' (the unreminded keyword) injected", injected == ["flying"],
                f"injected={injected}")
    # A segment whose content matches a specific keyword's reminder attributes to it.
    text = "Flying, reach (This creature can block creatures with flying.)"
    new, injected = inject_ability_reminders(text, MAP)
    ok &= check("content match attributes segment to reach; flying injected",
                injected == ["flying"], f"injected={injected}")

    print("== Plain (json-builder) text ==")
    text = "Flying\nVigilance (Attacking doesn't cause it to tap.)"
    new, injected = inject_ability_reminders(text, MAP, segment_formatter=PLAIN)
    ok &= check("flying injected as plain segment", injected == ["flying"] and
                new == f"Flying (This creature can't be blocked except by creatures with flying or reach.)\n"
                       "Vigilance (Attacking doesn't cause it to tap.)", new)

    print("== Degenerate inputs ==")
    ok &= check("empty text", inject_ability_reminders("", MAP) == ("", []))
    ok &= check("empty map", inject_ability_reminders("Flying", {}) == ("Flying", []))
    ok &= check("no keywords", inject_ability_reminders("Destroy target creature.", MAP) ==
                ("Destroy target creature.", []))

    print("== Map loading ==")
    ok &= check("map has 13 abilities", len(MAP) == 13, f"got {len(MAP)}: {sorted(MAP)}")
    ok &= check("no underscore/comment keys", all(not k.startswith("_") for k in MAP))
    ok &= check("ward template carries {cost}", "{cost}" in MAP["ward"])
    ok &= check("missing file -> empty map", load_reminder_map("/nonexistent/reminder_map.json") == {})

    return ok


if __name__ == "__main__":
    ok = run_all()
    print("\n" + ("ALL TESTS PASSED" if ok else "SOME TESTS FAILED"))
    sys.exit(0 if ok else 1)
