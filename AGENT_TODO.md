# AGENT TODO — ccAutomator review-fix campaign

Read `AGENT_OVERVIEW.md` first (findings + user rulings). Items live here,
move to `AGENT_DOING.md` when started, and to `AGENT_DONE.md` when finished
(with outcome + verification). One commit per fix (user instruction,
2026-09-18).

## Now (ordered — user-specified sequence)

### T8 — H4: Scryfall timeouts / 429 / duplicate fallback  [DONE 2026-09-18 → AGENT_DONE.md]
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
- **H8** live-path `_apply_text_mods` tag-duplication on re-run with changed
  values (mixins/text_mixin.py:54-141) vs JSON path replacing correctly;
  `_process_all_text_modifications` docstring/return/gate inconsistencies.
- **H9** scryfall_cache.py:90-95 catches all requests errors as IOError →
  false "another instance updated the cache" + returns True; hardcoded
  `/data/ccAutomator/` paths; whole 500MB JSON loaded into memory.
- **H10** `_update_tag` integer-only regex misses decimal tags
  (cc_file_editor.py:238-253, land_generator.py:336-342) → old tag survives.
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
