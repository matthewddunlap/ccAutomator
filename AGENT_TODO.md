# AGENT TODO — ccAutomator review-fix campaign

Read `AGENT_OVERVIEW.md` first (findings + user rulings). Items live here,
move to `AGENT_DOING.md` when started, and to `AGENT_DONE.md` when finished
(with outcome + verification). One commit per fix (user instruction,
2026-09-18).

## Now (ordered — user-specified sequence, 2026-09-20)

### 0) #5 — runtime-configurable data dir + find where the 5 minutes goes  [DONE 2026-09-22 → AGENT_DONE.md, commits 6a19ea8 + 76b1635]
User: "Whatver /data is being used for should be a runtime configurable
path. And the state based waits saving just 7 seconds seems ridiculously
low." (a) `--data-dir` + `configure_data_dir()` + cache-first per-card
art fetch — DONE, live-verified (commit 6a19ea8); (b) timestamped A/B
ANSWERED: ~85% of both sides is the CardConjurer app's own main-thread
work (canvas re-renders ~40%, startup/priming/UI-search ~30%); the cache
removes only ~1-5s of fast API calls here (production win = fewer calls /
less 429 exposure); (c) search cache-first — prior session had implemented
it contradicting its own notes; this session found+fixed a dead-path bug
in it (`game` vs current `games` JSON field), added an 8-test regression
suite, and live-verified byte-identical output under `--set-selection
earliest` (the `not:covered` gap is non-reproducible locally — real
output-risk only under latest/random/all). Presented to the user with
numbers; **user called KEEP** (commit 76b1635). Details + per-stage
breakdown: AGENT_DONE.md "#5".

### 1) H8 — live-path text-mod tag duplication on re-run  [DONE 2026-09-20 → AGENT_DONE.md, commit 41c31f5]
Tests 34/34 (`test_apply_text_tags.py`); fix + test committed 41c31f5;
notes committed with this file. (Was briefly blocked on the sandbox-
classifier outage, see OVERVIEW "Environment".)

### 2) #3 PERF — fixed sleeps → state-based waits  [DONE 2026-09-21 → AGENT_DONE.md, commits 989c7a9 + 9d03303]
A/B #3 (final, priming fix on both sides): **new 4m58.4s vs baseline
5m05.7s (−7.3s)**, EXIT 0 both, 3/3 cards uploaded, **all 3 output PNGs
byte-identical** (7.4–7.8 MB). Bonus: stability-only priming-wait fix
(989c7a9) is a 20–40s/run production win on its own (pre-existing
defect: `wait_for_change=True` burned the full 20s timeout when the same
card was already showing). Tests: test_wait_for_render.py 8/8 +
test_apply_text_tags.py 34/34, py_compile clean. Full history:
AGENT_DOING.md "#3 PERF". (Was: A/B #1 +14s regression from heavy
full-canvas toDataURL polling → fixed with a cheap downsampled probe;
A/B #2 +16s from the priming 20s burn → fixed in 989c7a9.)
**Why:** ~53 `time.sleep` calls in the selenium hot path + `render_delay`
(default 1.5s, CLI `--render-delay`) — the biggest wall-clock lever. Each
card pays seconds of blind waiting that usually finished rendering in
far less.
**Goal:** replace blind sleeps with waits on OBSERVABLE STATE; never longer
than necessary, never shorter than the render needs.
**Existing building block to build on:** `_wait_for_canvas_stabilization`
(canvas_mixin.py) — polls the rendered canvas hash until it stops changing;
already used pre-capture (automator.py:1390). That "stable-for-N-reads"
property is exactly the safety net a render-completion wait needs.
**Approach (selenium path first — user's focus):**
- Inventory: grep `time.sleep` + `render_delay` across automator.py and
  mixins/; classify each: (a) after a DOM write that re-renders the canvas
  (text edits, P/T box, art, symbol) → replace with canvas-stable wait with
  a max timeout; (b) waiting for an element/field to populate (0.2-0.5s
  after click/scroll) → replace with WebDriverWait on the specific state
  (element visible / value non-empty / expected value); (c) retry backoff
  (1s between attempts) → keep, it's deliberate pacing.
- `render_delay` stays as the CAP (max wait), not the floor:
  `poll until state stable (or change detected), timeout=render_delay`.
- Do NOT touch: pre-flight, Scryfall 429 sleep (Retry-After), validation
  `api_delay` — those are rate/network pacing, not render waits.
**Risks:** a state-wait can be satisfied by a STALE frame if the app hasn't
started re-rendering yet → mitigate by requiring the hash to be stable for
N consecutive reads AFTER the write (the existing stabilizer already does
this), or by waiting for the hash to CHANGE-then-STABILIZE where the app is
known to repaint synchronously.
**Verify:** A/B the same deck (`decks/long.txt` + `@custom.conf --save-cc-file`
or an equivalent real run) pre/post: per-card wall time and total; output
PNGs must be byte-identical or visually identical (PIL compare); logs must
show the waits resolving (timeouts are a FAILURE, print them).
**Deliverable:** one commit (or a small set) + AGENT notes; record the
measured speedup.

### (history) T8 — H4: Scryfall timeouts / 429 / duplicate fallback  [DONE 2026-09-18 → AGENT_DONE.md]
**Problem:** `scryfall_query_with_fallback` (automator_utils.py:325-434):
no `timeout=` on the four `requests.get` calls (367/394/410/426); no
429/Retry-After handling; "Fallback 1" (375-400) strips `not:covered`, which
`build_scryfall_query` never adds → always a byte-identical duplicate of
Try 1 (stale log line).
**Fix:**
- Helper `scryfall_search(query)`: `requests.get(url, params={'q': query},
  headers=SCRYFALL_HEADERS, timeout=(10, 60))`; on 429 → sleep
  `Retry-After` (default 10s, cap 60s) and retry once; return `data` list.
- Replace the four inline blocks with the helper; **delete Fallback 1**
  (375-400); renumber Fallback 2/3 log messages.
**Verify:** read-through; small run shows Try 1 → sets-stripped → broadest.

## Later review (explicitly deferred by user, 2026-09-18)

- **C1** combo `apply_edits` TypeError (type_gap/min_kerning kwargs not in
  signature, ccAutomator.py:966-967 & :1082-1084 vs cc_file_editor.py:50-54)
  — only selenium mode matters right now.
- **C2** cc_file_editor.py:8 missing import of `estimate_set_symbol_left`
  (called at :155) → NameError with `--auto-fit-type` in edit/combo.
- **C6** `--card-selection cardconjurer` dead branch (automator.py:418-433).
- **C7** full-art-basic-land / `--generate-lands` — user has added the
  template `.cardconjurer` file to `templates/`; review the whole flow later.
- **H5** full-art-land mods — **user notes:** lands have NO P/T (P/T mods
  N/A), Type mods ARE needed, full-art lands do NOT get a title. Verify Type
  mods applied + title appropriately absent. Likely mostly intentional.
  (Also the `--upload-path` stub at ccAutomator.py:1312-1314.)
- ~~**H6-adjacent feature:** validate the decklist at startup so bad names
  fail fast~~ — **DONE 2026-09-20 → AGENT_DONE.md**
  (`validate_decklist` in automator_utils.py; wired into the
  selenium/combo startup in ccAutomator.py; `--skip-validation` flag;
  validates against local Scryfall cache then API, mirroring the run's
  own resolution; `#` lines are category headers and are already stripped
  by parse_card_file, per the user ruling that comment-out is a feature).
- **H7** `apply_set_filters` no-op placeholder (automator_utils.py:223-243),
  imported but never called (ccAutomator.py:12) — dead code.
- ~~**H8** live-path `_apply_text_mods` tag-duplication on re-run with
  changed values (mixins/text_mixin.py) vs JSON path replacing correctly;
  `_process_all_text_modifications` docstring/return/gate inconsistencies~~
  — **DONE 2026-09-20 → AGENT_DONE.md** (commit 41c31f5; 34/34 unit tests;
  shared `apply_text_tags` helper in automator_utils.py; live + JSON +
  land-generator paths all delegate to it; gate/return/pt_* body fixed).
- ~~**H9** scryfall_cache.py:90-95 catches all requests errors as IOError →
  false "another instance updated the cache" + returns True; hardcoded
  `/data/ccAutomator/` paths; whole 500MB JSON loaded into memory~~
  — **DONE 2026-09-21 → AGENT_DONE.md** (commit da1b06d): contention-only
  flock catch + verified-after-wait result, targeted failure except (real
  error, honest False), `_db_is_usable` gate (kills the zero-byte-DB-
  fresh-for-a-week landmine), 60s failure cooldown, `CC_AUTOMATOR_DATA_DIR`
  env override + dev-box no-create guard, download timeout, streaming
  JSON→SQLite (chunked raw_decode + batched inserts). 17/17 tests, live
  run EXIT 0 with 3/3 cards, all 3 output PNGs byte-identical to the
  verified A/B #3 set.
- ~~**H10** `_update_tag` integer-only regex misses decimal tags
  (cc_file_editor.py:238-253, land_generator.py:336-342) → old tag survives~~
  — **Resolved as a side effect of the H8 fix (2026-09-20):** the shared
  `apply_text_tags` helper (which both `_update_tag` copies now delegate to)
  uses a decimal-aware anchored pattern `\{fontsize-?\d+(?:\.\d+)?\}`.
  **Flagged for the user:** this was not in the H8 scope the user approved —
  keep it (recommended: same helper, one code path) or call it out for a
  separate review.
- **H11** json mode: colorless non-land → artifact frame
  (seventh_generator.py:238-239); `sys.modules['gradio_client'] = MagicMock()`
  hack (:6-7); `upscale_art = True` hardcoded.
- **Medium/low:** stale `_cached_canvas_selector` (canvas_mixin.py:51);
  driver leak on init failure (automator.py:58-257); ilaria fixed-name
  /tmp temp file + assumed local gradio result (image_mixin.py:219-298);
  `generate_safe_filename` collisions + empty-result guard;
  `save_cardconjurer_file` non-atomic + unsanitized name;
  `_save_card_to_browser_storage` "might have saved" (automator.py:1042-1089);
  `download_saved_cards` mtime-based file picking; DEBUG prints
  (ccAutomator.py:1017-1018, automator.py:207); dev-note comments in shipped
  code (automator.py:418-433, image_mixin.py:476-494); duplicated pre-flight
  check (ccAutomator.py:788-844 vs :1139-1152) + bare except on HEAD;
  ~1300-line `main()`; redundant `except (NoSuchElementException, Exception)`
  (print_mixin.py:81); `strptime` with %Z (automator.py:1441).
- **Tests:** no test suite exists — add one for the pure functions
  (`autofit_*`, `parse_card_file`, `_update_tag`, `generate_safe_filename`,
  `parse_time_string`).
