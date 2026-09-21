# AGENT DOING — current work item

**NEXT SESSION, START HERE (2026-09-21):**
**#3 perf — state-based waits: DONE** (fix commits **989c7a9** + **9d03303**;
A/B #3 final: new 4m58.4s vs baseline 5m05.7s, EXIT 0 both, all 3 output
PNGs byte-identical, tests 8/8 + 34/34). Next: **plan item #4 — H9 residual**
(scryfall_cache false-success + hardcoded `/data/ccAutomator/` paths).
H8 is DONE (34/34, commit 41c31f5). Keep the AGENT_ files current; one
commit per fix + a notes commit recording the hash (trailer:
`Co-Authored-By: Claude Code <noreply@anthropic.com>`).

## #3 PERF — fixed sleeps → state-based waits  [DONE 2026-09-21]

**OUTCOME: NET WIN, COMMITTED.** A/B #3 (final, both sides carry the
priming fix): **new 4m58.4s vs baseline 5m05.7s (−7.3s)**, EXIT 0 both,
3/3 cards, **all 3 output PNGs byte-identical** (7.4–7.8 MB full-res).
Fix commits: **989c7a9** (priming-wait fix) + **9d03303** (perf). Tests:
`test_wait_for_render.py` 8/8, `test_apply_text_tags.py` 34/34, py_compile
clean. Full history + root-cause analysis below.

**Implementation (6 files + 1 new test, committed 9d03303):**
- `mixins/canvas_mixin.py`: `_wait_for_canvas_stabilization(..., timeout=None,
  probe=False)` (timeout param + probe switch); `_get_canvas_probe_hash()`
  (downsampled 64×90 offscreen probe, cached on `window.__ccProbe`);
  `_wait_for_render(timeout=None)` — the drop-in for the old blind
  `time.sleep(render_delay)`: render_delay is now a CAP, poll the CHEAP
  probe until 3-stable, warn-and-continue on cap expiry, never raises.
  White-border site + set_frame_color tail now call it.
- `mixins/text_mixin.py`: all 9 `time.sleep(self.render_delay)` →
  `self._wait_for_render()`.
- `automator.py`: catch-all wait → `_wait_for_render()`; 2× `sleep(2)`
  (project flows) → `_wait_for_render(timeout=2)`; 2× `sleep(1.5)`
  (load flows) → `_wait_for_render(timeout=1.5)`.
- `mixins/symbol_mixin.py`: after `fetchSetSymbol()` → `_wait_for_render()`.
- `ccAutomator.py`: `--render-delay` help updated ("cap, not floor").
- `test_wait_for_render.py` (repo root): 8 checks, all pass (stub driver;
  probe vs full-res paths, caps honored, render_delay=0 skip, no
  current_canvas_hash clobber).

**A/B #1 (decks/long.txt + @custom.conf --debug --overwrite --save-cc-file):**
- baseline (old code, git stash): **4m51.059s**, EXIT 0, 3 cards uploaded
- new code v1: **5m5.006s**, EXIT 0 — **REGRESSION +14s**
- both runs also carry a pre-existing 20s startup
  `wait_for_change=True` timeout (log line 1) — equal in both, cancels out.
Logs: `$CLAUDE_JOB_DIR/tmp/ab_base.log`, `ab_new.log` (job ac1fc71f).

**Root cause (from ab_new.log debug timestamps):** the gap between poll
reads was 0.35s … **6.67s, 6.65s, 6.25s, 8.05s, 8.18s**. `_get_canvas_hash`
calls `toDataURL('image/png')` on the FULL 2010×2814 canvas (multi-MB
base64 string) then runs a JS hash loop over every character — at ~10
polls/s that's tens of MB allocated + GC'd per second on the very browser
we wait on, so each "poll" cost 0.3–8s and the 1.5s cap (only checked
BETWEEN reads) was never an honest cap. 14/14+ waits timed out, each paying
cap + one 6–8s read. The old blind sleep did zero browser work → always won.

**Fix (implemented, unit-verified):** poll a cheap probe — drawImage the
card canvas onto a cached 64×90 offscreen canvas and hash those few KB
(`_get_canvas_probe_hash`); `_wait_for_render` uses `probe=True`; full-res
hash kept for the one-off gates (art-apply, priming, pre-capture — unchanged).
`_wait_for_render` no longer writes the probe hash back into
`current_canvas_hash` (different basis — would corrupt full-res
wait_for_change comparisons).

**A/B #2 (after the probe fix — still REGRESSED, +16s):**
- baseline (old code, git stash): **5m03.5s**, EXIT 0
- new code v2 (probe): **~5m19s**, EXIT 0
- Diagnosis: the new run burned **2× the 20s priming timeout**
  ("change detected: False") vs **1×** in the baseline — the extra ~20s
  WAS the delta. Log signature: ~20s of SILENCE (the equal-hash branch
  `continue`s past the debug print) followed by one warning.

**Root cause #2 — a PRE-EXISTING priming defect (fixed separately,
989c7a9):** priming used `wait_for_change=True`, which burns the full
20s STABILIZE_TIMEOUT when (a) the same card is already showing (the app
persists the last card in browser storage; every run primes the same
card → the hash never changes) or (b) the app already rendered the new
card between two reads (change missed). Priming only needs "renderer
warm with *ANY* print" (existing comment, automator.py ~411) → both
priming sites (CC-mode ~421, scryfall-mode `_prime_via_scryfall` ~1190)
now do `self.current_canvas_hash =
self._wait_for_canvas_stabilization(None, wait_for_change=False)` —
stability-only. A stale settle is harmless (priming needs any print).
This is a **20–40s/run production win on its own** — both the old and
new code were paying it.

**A/B #3 (FINAL — priming fix present on BOTH sides):**
- baseline (old code, git stash): **5m05.676s**, EXIT 0, 3/3 cards uploaded
- new code (probe + stability-only priming): **4m58.354s**, EXIT 0,
  3/3 cards uploaded — **−7.3s**
- PNG compare (`compare_pngs.py ab_base ab_new`, separate `--upload-path`
  dirs ab_base/ab_new so the runs don't overwrite each other on the
  server): **ALL 3 CARDS BYTE-IDENTICAL** (7.4–7.8 MB full-res,
  kamahl-fist-of-krosa_ons_268 / phyrexian-dreadnought_mir_315 /
  karn-silver-golem_usg_298)
- Tests: `test_wait_for_render.py` **8/8**, `test_apply_text_tags.py`
  **34/34**; `py_compile` clean on all touched files.
- Logs: `$CLAUDE_JOB_DIR/tmp/ab3_base.log`, `ab3_new.log` (job ac1fc71f).

**Why the A/B #1/#2 deltas are still meaningful:** the state-wait
pipeline itself saved ~5–7s/run in all three A/Bs; the only masking
factor was the priming 20s burn, which is now eliminated in both
designs. `wait_for_change=True` remains at image_mixin.py:109 (the
art-apply wait) — it waits for a REAL change, settles in 0.7–1.1s in
every run, and was intentionally left unchanged.

**Commits (branch user-agent):**
- **989c7a9** "Fix priming canvas wait: stability-only, not
  change-detection" (automator.py, +19/−7)
- **9d03303** "Perf: replace blind render_delay sleeps with state-based
  canvas waits" (6 files + new test_wait_for_render.py, +228/−31)

**NEXT: plan item #4 — H9 residual** (AGENT_TODO.md): scryfall_cache
false-success (`except (BlockingIOError, IOError)` swallows request
errors → false "another instance updated the cache", returns True) +
hardcoded `/data/ccAutomator/` paths + whole ~500MB JSON in memory.

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

## Next up

**#3 perf — DONE** (2026-09-21, commits 989c7a9 + 9d03303; A/B #3 WIN,
see above). Per the user's ordered plan, next is:

1. **H9 residual** (plan item #4): scryfall_cache false-success
   (`except (BlockingIOError, IOError)` swallows request errors → false
   "another instance updated the cache", returns True) + hardcoded
   `/data/ccAutomator/` paths + whole ~500MB JSON loaded into memory.
2. **H7**: delete dead no-op `apply_set_filters`.
