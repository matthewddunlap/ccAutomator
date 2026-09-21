# AGENT DOING — current work item

**NEXT SESSION, START HERE (2026-09-20):**
**H8 is DONE** (tests 34/34, fix commit 41c31f5, notes below) —
**proceed to #3 perf — state-based waits** (full spec: `AGENT_TODO.md` →
"Now" #2). Keep the AGENT_ files current; one commit per fix + a notes
commit recording the hash (trailer:
`Co-Authored-By: Claude Code <noreply@anthropic.com>`).

## H8 — live-path text-mod tag duplication on re-run  [DONE 2026-09-20, commit 41c31f5]
**Problem:** `_apply_text_mods` (mixins/text_mixin.py) guarded with
`if prefix in current_text: return` — a re-run with CHANGED values skipped
the field (stale tag survived) or prepended a full second tag set (silent
wrong output); the guard also false-positived on substrings
({fontsize1} "in" {fontsize10}). `_apply_flavor_font_mod` stacked a
{fontsize} after {flavor} every run. `_process_all_text_modifications`:
docstring claimed a return it never had; gate listed pt_* args the body
never applied; `pt_left` missing from the gate.
**Fix (ALL CODE DONE 2026-09-20, in the working tree, UNCOMMITTED):**
- `automator_utils.py`: new pure `apply_text_tags(text, fontsize=None,
  shadow=None, kerning=None, left=None, up=None, down=None, bold=False)` —
  per tag kind: existing tag (anchored, decimal/negative-aware pattern,
  `{fontsize64pt}` never mis-matched) UPDATED in place; missing tag
  prepended; duplicated stale tags converge to one at the first's position;
  `{bold}` idempotent, never stripped; unchanged input → equal string
  (caller's `==` guard skips the DOM write). Single source of truth.
- `mixins/text_mixin.py`: `_apply_text_mods` core = helper +
  `new_text == current_text` no-op check; `_apply_flavor_font_mod` applies
  to the part after {flavor} via the helper; `_process_all_text_modifications`
  = honest docstring + `return False`/`return any_text_mod_made` + gate
  includes `pt_left` + body applies P/T mods (identical args to the live
  path automator.py:767-768).
- `cc_file_editor.py` + `land_generator.py`: both `_update_tag` copies
  delegate to the helper; land_generator's flavor-stacking bug fixed to the
  same REPLACE semantics; its now-dead `import re` removed.
- `test_apply_text_tags.py` (repo root, 30+ assertions): prepend,
  replace-in-place (the H8 changed-values case), duplicate convergence,
  decimals/negatives, 64pt + 10-vs-1 no false-positive, bold idempotent,
  no-op guard, flavor first/re/changed runs, `_update_tag` delegation for
  all six tag kinds, and a full `CcFileEditor.apply_edits`
  run1/run2-same-values/run3-changed-values scenario (read the edited state
  from `ed.data` — `apply_edits` does NOT write back to the file).
- `py_compile` clean on all five touched .py files (verified 2026-09-20).
**Completed 2026-09-20:**
1. `test_apply_text_tags.py` → **34/34 PASS** (one test expectation initially
   assumed the wrong prepend accumulation order — the code was correct, the
   expectation fixed).
2. Fix commit: **41c31f5** (the 5 files above).
3. Notes commit: this one (see AGENT_DONE.md entry, `Commit: 41c31f5`).

NOTE (flagged for user, in TODO/DONE): the helper's decimal-aware regex also
resolves deferred **H10** (integer-only tag regex) as a side effect of the
convergence — recommended to keep; user's call.

(Startup decklist validation — completed 2026-09-20, moved to AGENT_DONE.md.)

## All ordered fixes T1-T9 complete AND verified  [2026-09-19]

- T1-T8: fixed 2026-09-18 (see `AGENT_DONE.md`), **live + offline
  verification completed 2026-09-19** — all six pending verifications PASS.
  Full results: `AGENT_DONE.md` → "Live verification of T1-T8".
- T9 (P/T box stateful set/restore, the Karn left-shift bug) was completed
  and live-verified 2026-09-19 (earlier) — see `AGENT_DONE.md`.

## Next up (after H8's 3 pending steps)

Per the user's 2026-09-20 order, **#3 perf — state-based waits** is next
(full spec in `AGENT_TODO.md` "Now" #2). Then:

1. **H9 residual**: scryfall_cache false-success (`except IOError` swallows
   request errors → "finished by another instance", returns True) +
   hardcoded `/data/ccAutomator/` paths. (plan item #4)
2. **H7**: delete dead no-op `apply_set_filters`.
