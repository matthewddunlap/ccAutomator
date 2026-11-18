"""
Tests for inject_ability_reminders / load_reminder_map (the --inject-reminder-text
feature: reminder-text normalization).

Semantics under test:
  - Every mapped keyword ability mentioned in the rules text ends up with the
    canonical sentence from reminder_map.json.
  - A printed reminder of a mapped ability (wording may differ) is REPLACED
    by the canonical one; parentheticals that are not convincing reminders
    are never touched.
  - Card Conjurer text-box text tags reminders '{i}(...) {/i}'; raw oracle
    text (json builder path) uses plain '(...)'.
  - Idempotent: a second pass strips the canonical segment and re-appends
    the identical one.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from automator_utils import inject_ability_reminders, load_reminder_map

MAP = load_reminder_map(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'reminder_map.json'))
FLYING = MAP["flying"]
VIGILANCE = MAP["vigilance"]
HASTE = MAP["haste"]
FIRST_STRIKE = MAP["first strike"]
DOUBLE_STRIKE = MAP["double strike"]
MENACE = MAP["menace"]
PLAIN = lambda s: f" ({s})"  # json-builder style formatter


def check(label, cond, detail=""):
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {label}" + (f"  -> {detail}" if detail and not cond else ""))
    return cond


def run_all():
    ok = True
    print("== Serra Angel: Flying missing, Vigilance present (printed == canonical here) ==")
    text = "Flying\nVigilance {i}(Attacking doesn't cause this creature to tap.){/i}"
    new, abilities = inject_ability_reminders(text, MAP)
    ok &= check("both abilities carry canonical reminders", abilities == ["flying", "vigilance"],
                f"abilities={abilities}")
    ok &= check("flying line gains reminder",
                new.split("\n")[0] == f"Flying {{i}}({FLYING}){{/i}}", new.split("\n")[0])
    ok &= check("vigilance line carries the canonical sentence",
                new.split("\n")[1] == f"Vigilance {{i}}({VIGILANCE}){{/i}}", new.split("\n")[1])

    print("== Sengir Vampire: printed Flying reminder (already canonical wording) ==")
    text = ("Flying {i}(This creature can't be blocked except by creatures with flying or reach.){/i}\n"
            "Whenever a creature dealt damage by this creature this turn dies, put a +1/+1 counter on this creature.")
    new, abilities = inject_ability_reminders(text, MAP)
    ok &= check("text byte-identical, flying normalized", new == text and abilities == ["flying"],
                f"abilities={abilities} new={new!r}")

    print("== Printed VARIANT wording is replaced by the canonical sentence ==")
    # Menace card printing the flying-variant reminder wording (only candidate is menace).
    text = "Menace {i}(This creature can't be blocked except by creatures with flying or reach.){/i}"
    new, abilities = inject_ability_reminders(text, MAP)
    ok &= check("menace normalized to canonical", abilities == ["menace"] and
                new == f"Menace {{i}}({MENACE}){{/i}}", f"abilities={abilities} new={new!r}")
    ok &= check("old variant wording gone (incl. its 'flying' mention)", "flying" not in new)

    print("== Haste variant 'It can attack and {T} this turn.' replaced ==")
    text = "Haste {i}(It can attack and {T} this turn.){/i}"
    new, abilities = inject_ability_reminders(text, MAP)
    ok &= check("haste normalized to canonical", abilities == ["haste"] and
                new == f"Haste {{i}}({HASTE}){{/i}}", f"abilities={abilities} new={new!r}")

    print("== 'Flying, vigilance' with no reminders: both appended, in order ==")
    new, abilities = inject_ability_reminders("Flying, vigilance", MAP)
    ok &= check("both in line order", abilities == ["flying", "vigilance"], f"abilities={abilities}")
    ok &= check("both segments appended",
                new == f"Flying, vigilance {{i}}({FLYING}){{/i}} {{i}}({VIGILANCE}){{/i}}", new)

    print("== First strike + double strike: single ds reminder replaced, both canonical ==")
    text = ("First strike, double strike {i}(This creature deals both first-strike and regular "
            "combat damage.){/i}")
    new, abilities = inject_ability_reminders(text, MAP)
    ok &= check("both normalized", abilities == ["first strike", "double strike"], f"abilities={abilities}")
    ok &= check("one reminder each, old text replaced",
                new == f"First strike, double strike {{i}}({FIRST_STRIKE}){{/i}} {{i}}({DOUBLE_STRIKE}){{/i}}",
                new)

    print("== Non-reminder parenthetical is preserved; keyword still normalized ==")
    text = "Flying (choose one or more of the following)"
    new, abilities = inject_ability_reminders(text, MAP)
    ok &= check("parenthetical kept, flying reminder appended",
                abilities == ["flying"] and
                new == "Flying (choose one or more of the following)" + f" {{i}}({FLYING}){{/i}}",
                f"abilities={abilities} new={new!r}")

    print("== Idempotency (tagged and plain formatters) ==")
    once, _ = inject_ability_reminders("Flying, vigilance", MAP)
    twice, ab2 = inject_ability_reminders(once, MAP)
    ok &= check("second run byte-identical", once == twice and ab2 == ["flying", "vigilance"],
                f"second={twice!r} ab2={ab2}")
    src = "Haste (It can attack and {T} this turn.)\nFlying"
    once_p, _ = inject_ability_reminders(src, MAP, segment_formatter=PLAIN)
    twice_p, ab2p = inject_ability_reminders(once_p, MAP, segment_formatter=PLAIN)
    ok &= check("variant replacement idempotent (plain)", once_p == twice_p and
                ab2p == ["haste", "flying"], f"second={twice_p!r} ab2p={ab2p}")

    print("== Token with a bare keyword ==")
    new, abilities = inject_ability_reminders("Vigilance", MAP)
    ok &= check("vigilance normalized", abilities == ["vigilance"] and
                new == f"Vigilance {{i}}({VIGILANCE}){{/i}}", new)

    print("== Ward: cost is substituted; printed ward reminder is normalized ==")
    new, abilities = inject_ability_reminders("Ward {1}", MAP)
    ok &= check("ward {1} reminder", abilities == ["ward"] and "unless that player pays {1}." in new, new)
    text = ("Ward {2} {i}(Whenever this creature becomes the target of a spell or ability an opponent "
            "controls, counter it unless that player pays {2}.){/i}")
    new, abilities = inject_ability_reminders(text, MAP)
    ok &= check("printed ward reminder replaced with identical canonical", new == text and
                abilities == ["ward"], f"abilities={abilities} new={new!r}")
    new, abilities = inject_ability_reminders("Ward {R}", MAP)
    ok &= check("ward {R} cost substituted", "pays {R}." in new, new)

    print("== Flavor tail is never touched ==")
    text = "Flying {flavor}It once said, “flying was easy.”"
    new, abilities = inject_ability_reminders(text, MAP)
    ok &= check("flying normalized once", abilities == ["flying"], f"abilities={abilities}")
    ok &= check("flavor tail byte-identical",
                new.endswith("{flavor}It once said, “flying was easy.”"), new)
    ok &= check("reminder before the flavor marker",
                new.index("{/i}") < new.index("{flavor}"), new)

    print("== Word boundaries ==")
    new, abilities = inject_ability_reminders("This creature has hexproof.", MAP)
    ok &= check("hexproof matched", abilities == ["hexproof"], f"abilities={abilities}")
    new, abilities = inject_ability_reminders("This spell is infectious.", MAP)
    ok &= check("'infectious' does not match infect", abilities == [], f"abilities={abilities}")
    new, abilities = inject_ability_reminders("The ward against this is strong.", MAP)
    ok &= check("noun 'ward' with no cost is skipped", abilities == [], f"abilities={abilities}")

    print("== Multi-line segment: inner keywords don't grant; both line keywords normalized ==")
    text = "Flying, reach (A reminder\nthat spans two lines and mentions reach.)"
    new, abilities = inject_ability_reminders(text, MAP)
    ok &= check("flying + reach normalized, 'reach' inside segment didn't add more",
                abilities == ["flying", "reach"], f"abilities={abilities}")
    ok &= check("segment preserved (not a convincing reminder), reminders after line 1",
                new == "Flying, reach (A reminder" + f" {{i}}({MAP['flying']}){{/i}} {{i}}({MAP['reach']}){{/i}}\n"
                      "that spans two lines and mentions reach.)", new)
    # A segment whose content matches reach's reminder is removed and replaced.
    text = "Flying, reach (This creature can block creatures with flying.)"
    new, abilities = inject_ability_reminders(text, MAP)
    ok &= check("reach variant removed, both canonical",
                new == f"Flying, reach {{i}}({FLYING}){{/i}} {{i}}({MAP['reach']}){{/i}}", new)

    print("== Plain (json-builder) text ==")
    text = "Flying\nVigilance (Attacking doesn't cause it to tap.)"
    new, abilities = inject_ability_reminders(text, MAP, segment_formatter=PLAIN)
    ok &= check("flying added, vigilance variant replaced",
                abilities == ["flying", "vigilance"] and
                new == f"Flying ({FLYING})\nVigilance ({VIGILANCE})", f"abilities={abilities} new={new!r}")

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
