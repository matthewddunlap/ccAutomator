# AGENT DOING — current work item

**NEXT SESSION, START HERE (2026-09-22):**
**#5 COMPLETE** — user called KEEP BOTH PARTS (2026-09-22, presented with
the A/B numbers). Commits on branch user-agent: **6a19ea8** (data-dir +
cache-first art) + **76b1635** (search cache-first + games-field fix +
8-test suite); notes commit records the hashes. All four suites green
(18/18, 34/34, 8/8, 8/8); live A/B EXIT 0 both sides; PNGs byte-identical
(API side vs cache side, and cache side vs the verified h9_new set).
Full record: AGENT_DONE.md "## #5". **Next candidate (deferred item,
not yet started): H7** — delete the dead no-op `apply_set_filters`
(automator_utils.py:223-243, imported but never called).
(Prior: #4 H9 DONE — da1b06d; #3 perf DONE — 989c7a9 + 9d03303;
H8 DONE — 41c31f5.)

ENV NOTES (this box): `CLAUDE_JOB_DIR` is unset in-session — the job dir
with all A/B logs + `compare_pngs.py` + `seed_cache.py` + the seeded test
cache is `/home/i3/.claude/jobs/ac1fc71f/tmp/` (cache:
`/home/i3/cc_test_cache/`, 5 cards incl. the 3 deck cards + 2 prime cards;
rebuild with `seed_cache.py <dir>` if missing). App
`http://mtgproxy:4242/` + Scryfall API reachable; venv
`.venv/bin/python`. Four test suites at repo root.

## #5 DATA-DIR + where the 5 minutes goes  [DONE 2026-09-22 — commits 6a19ea8 + 76b1635]

**Full outcome + verification: AGENT_DONE.md "## #5 DATA-DIR + where the
5 minutes goes". Short state:**
- (a) `--data-dir` + `configure_data_dir()` + cache-first per-card art
  fetch: DONE, live-verified.
- (b) "where the 5 minutes goes": ANSWERED — timestamped A/B; the
  CardConjurer app's own main-thread work is ~85% of both sides (canvas
  re-renders ~40%, startup/priming/UI-search ~30%, mods/autofit ~10%);
  the cache removes only ~1-5s of fast Scryfall API calls here (real
  production win = fewer calls / less 429 exposure on big decks);
  art BYTES still come from Scryfall's CDN in both modes.
- (c) search cache-first (`_resolve_prints_cache_first`): implemented in
  the working tree by the prior session (contradicting its own notes);
  this session found + fixed a DEAD-PATH bug in it (`game` vs the current
  `games` JSON field — it silently always fell back to the API), added a
  regression suite (8 tests), and live-verified it end-to-end
  (byte-identical PNGs vs the API side and vs the verified h9_new set,
  with `--set-selection earliest`). The `not:covered` gap is
  non-reproducible locally (search-engine-only; e.g. drops the g10 judge
  promo) → equivalent under earliest, real output-risk under
  latest/random/all. **User called KEEP (2026-09-22) — committed
  76b1635.**

**(a) Runtime-configurable data dir — DONE (verified 2026-09-22):**
- `scryfall_cache.py`: new `configure_data_dir(path)` — repoints
  DATA_DIR/DB_FILE/JSON_FILE/LOCK_FILE, sets `_data_dir_explicit = True`,
  resets the singleton (no stale conn for a previous location).
  `_cache_dir_ready()` now keys off `_data_dir_explicit` (= env var set OR
  configure() called) instead of re-reading the env var.
- `ccAutomator.py`: new `--data-dir` flag (works from @conf files too);
  right after `args = parser.parse_args()`: `scryfall_cache.
  configure_data_dir(args.data_dir)` (all cache imports are lazy, so this
  is the earliest safe point) + prints the resolved dir.
- `test_scryfall_cache.py`: `test_configure_data_dir_repoints_and_resets_
  singleton` (repoint, singleton reset, explicit-dir opt-in bootstrap
  allowed, honest None fallback, no empty DB left).
- **Cache-first per-card art fetch:** `mixins/image_mixin.py:
  _get_scryfall_art_crop_url` tries `ScryfallCache().get_card(name,
  set_code)` first (no-op → None on machines without a cache), API fetch
  unchanged as fallback; extraction shared via local `extract()`. Confirmed
  on the hot path: the main flow (automator.py:754) calls
  `_prepare_art_asset` WITHOUT scryfall_data, so all 3 cards log
  "Using local Scryfall cache ..." in the cache run. (Note: that same
  call has the card's scryfall_data in hand — passing it would skip even
  the cache/API meta lookup; left as-is, out of scope.) Validation
  (automator_utils.py) was already cache-first.

**(b) Why the state-wait A/B saved only ~7s — CONFIRMED (log analysis +
timestamped A/B 2026-09-22):**
- The [Debug] Wait reads of 8-9s each (10+ of them, after Title/Type/
  P/T/flavor-font writes and priming) are the APP's own main-thread
  re-render/auto-fit work delaying our execute_script — ~113-127s of each
  run (the single biggest bucket, ~40%). That app work is paid by BOTH
  designs (the old code's next selenium op queued behind the same work) →
  cancels out of the A/B delta. This is why the sleep→state-wait change
  only moved ~7s of a ~300s run: the blind sleep was only the ~1.5s
  residual AFTER the app finished, which the state wait removed.
- Timestamped A/B (2026-09-22, `ts_ts_api.log` 306.8s / `ts_ts_cache2.log`
  289.6s; per-line timestamps, gaps between lines = un-logged work):
  canvas waits ~40% (113-127s), startup/setup/priming ~30% (94-103s:
  driver+page load, frame/bounds dialogs, 2 priming card loads), per-card
  mods/autofit/symbols ~6-10%, per-card UI print-lookup ~9-10%, art+
  capture+save ~3%, "other" ~5%. NO single network step exceeds ~0.5s on
  this box (search ~0.17s, art meta ~0.12s each) — the ~120-150s
  "un-logged" time is accounted for: it IS the app's main-thread work,
  visible as 8-19s gaps before [Debug] Wait / Bypassing-filters /
  Ensuring-Autofit / Rules-Bounds lines.
- **Cache's honest effect:** removes ~1-5s of Scryfall API calls per run
  here (print-lookup bucket: 32.1s → 27.3s, within the ±12-14s run-noise
  band); production value is call COUNT (2 per card → ~0) = less 429
  rate-limit exposure on big decks, not wall time on this box. Art BYTES
  still download from Scryfall's CDN in both modes (the cache stores
  metadata, not images).

## #4 H9 — scryfall_cache false-success + hardcoded paths  [DONE 2026-09-21, commit da1b06d]

**Implementation (scryfall_cache.py rewritten + new test_scryfall_cache.py,
committed da1b06d):**

*Headline bug (fixed):* `except (BlockingIOError, IOError)` wrapped the
WHOLE update — and `requests.exceptions.*` all subclass `IOError` — so ANY
network failure (DNS, refused, timeout, 5xx via raise_for_status) was
reported as "Another instance is currently updating the cache" and the
function returned **True** although nothing had been updated. Worse, holding
the EX lock and re-flocking LOCK_SH on the same fd succeeded instantly, so
the "waiting for another instance" message was pure fiction.

*Fix (scryfall_cache.py):*
- Lock contention now handled ONLY by `except BlockingIOError` around the
  `flock(EX|NB)` call itself — the one case that genuinely means "another
  instance". After waiting (LOCK_SH), the result is VERIFIED: True only if
  a usable cache exists (and is fresh, when `force`); otherwise honest
  False + warning.
- Expected update failures (requests.RequestException, sqlite3.Error,
  ValueError from the JSON iterator, OSError) are caught in ONE targeted
  except around the update body → real error printed → False. No more
  blanket swallow; no false "another instance".
- **Zero-byte-DB landmine closed:** `_db_is_usable()` (table exists,
  COUNT(*)>0, readonly open) gates BOTH the staleness check and
  `_get_conn`; on a failed update `_get_conn` raises instead of letting
  `sqlite3.connect()` create an empty DB the old code would have treated
  as "fresh" for a week. `get_card`'s existing `except Exception → None`
  preserves the API fallback at every call site (verified:
  ccAutomator.py:812/1154 pre-flight + skip-check, automator_utils.py
  validate_decklist + scryfall_query_with_fallback).
- **Failure cooldown:** `_UPDATE_RETRY_COOLDOWN = 60s` — a failed update is
  not re-attempted (full connect timeout each time) on every card lookup.
- **Paths no longer hardcoded:** `DATA_DIR = os.environ.get(
  "CC_AUTOMATOR_DATA_DIR", "/data/ccAutomator")` — production default
  unchanged. Plus a **dev-box guard** (`_cache_dir_ready`): if the DEFAULT
  dir does not exist on the machine (true on this dev box — /data is
  absent), a card lookup must NOT create it or start a ~500MB download;
  it returns False immediately → API fallback (old code died with an
  uncaught FileNotFoundError at `lock_path.touch()`; same net result,
  no traceback, no side effects). Explicit env var = opt-in bootstrap.
- **Timeout on the streaming download** (`timeout=(20, 300)`) — the old
  `requests.get(download_uri, stream=True)` had none and could hang
  forever.
- **Memory (the "whole 500MB JSON in memory" item):** new
  `_iter_json_array_elements()` streams the bulk JSON in 1MB chunks via
  `json.JSONDecoder().raw_decode` (handles elements spanning chunk
  boundaries, unicode, nested structures); conversion inserts in 1000-row
  batches. Peak extra memory is now ~one chunk + one card instead of the
  full cards list PLUS a full json.dumps'd copy. Zero-row downloads are
  refused (count==0 → False, no install) so a bad payload can't become a
  "fresh" empty cache.
- `_db_is_usable` also guards the contention branch and the fresh-cache
  short-circuit (which still skips the download entirely — unit-tested
  with a network-call sentinel).

*Verify (so far):*
- `test_scryfall_cache.py` (repo root, NEW): **17/17 PASS** — iterator
  (basic / whitespace+unicode+nested / chunk-boundary at 16-byte chunks /
  empty array / truncated+not-array+empty-file ValueError); `_db_is_usable`
  (missing / zero-byte / non-DB / empty-table / valid); **H9 regression**
  (network failure → False, not True; no DB left behind); cooldown
  throttling; contention ×3 (usable→True, none→False, stale+force→False);
  full fake-download success (URI pick from 2 entries, round-trip
  get_card, JSON cleaned, no .tmp left); 1503-card batch boundary;
  zero-row refusal; fresh-cache short-circuit (no network call);
  missing-default-dir guard (no dir created, no network).
- `test_apply_text_tags.py` 34/34, `test_wait_for_render.py` 8/8 (no
  regressions), py_compile clean.
- Dev-box smoke: `ScryfallCache().get_card('Kamahl, Fist of Krosa')` →
  None in 0.00s, **/data NOT created** (old code: uncaught FileNotFoundError
  inside get_card's silent except).
- **Live run (2026-09-21):** `decks/long.txt @custom.conf --debug
  --overwrite --save-cc-file --upload-path /local_art/card_images/h9_new`
  → **EXIT 0, Success: 3 / Skipped: 0 / Error: 0**, 5m12.5s (within the
  ~±12-14s run variance of the 4m51-5m12s A/B band), log
  `$CLAUDE_JOB_DIR/tmp/h9_new.log`.
- **PNG compare (2026-09-21):** `.venv/bin/python
  $CLAUDE_JOB_DIR/tmp/compare_pngs.py ab_new h9_new` → **ALL 3 CARDS
  BYTE-IDENTICAL** (7.4–7.8 MB; the A/B #3 `ab_new` set was itself verified
  identical to the baseline, so this run's outputs equal the verified
  outputs end-to-end).
- **Commits:** fix commit **da1b06d** (scryfall_cache.py +
  test_scryfall_cache.py, +648/−43); notes commit: this one.

**Verification summary:** 17/17 unit tests (incl. the H9 false-success
regression, contention ×3, chunk-boundary streaming, cooldown, full
fake-download success, zero-row refusal, dev-box guard); other suites
34/34 + 8/8; py_compile clean; dev-box smoke (no /data created, 0.00s
fallback); live run EXIT 0, 3/3 cards, byte-identical PNGs.

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

**#3 perf — DONE** (2026-09-21, commits 989c7a9 + 9d03303; A/B #3 WIN).
**#4 H9 residual — IN PROGRESS** (implementation + 17/17 tests + live run
done; PNG compare + commits pending — see "#4 H9" above). After H9:

1. **H7**: delete dead no-op `apply_set_filters`.
2. H10 keep/revert call is still the user's (flagged in TODO/DONE since
   2026-09-20).
