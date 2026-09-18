# AGENT TODO — ccAutomator review-fix campaign

Read `AGENT_OVERVIEW.md` first (findings + user rulings). Items live here,
move to `AGENT_DOING.md` when started, and to `AGENT_DONE.md` when finished
(with outcome + verification). One commit per fix (user instruction,
2026-09-18).

## Now (ordered — user-specified sequence)

### T1 — C5: surface upload failures  [TODO]
**Problem:** `_upload_image` (mixins/image_mixin.py:107-142) prints
HTTP/network errors but never raises; `capture_card` returns normally and
`results['captured'] += 1` (automator.py:882) counts a card whose PNG never
reached the server as a success. Same swallow pattern: `_upload_art_asset`
(image_mixin.py:144-170), `_save_or_upload_image` (171+), and the broad
excepts in `download_saved_cards` (automator.py:1155-1156) and
`render_project_file` (automator.py:1405-1406).
**Fix:**
- Add `class UploadError(RuntimeError)` in `mixins/image_mixin.py`.
- `_upload_image`: `raise UploadError(...) from e` after each existing print
  (HTTPError + RequestException branches). Same for `_upload_art_asset` and
  `_save_or_upload_image`.
- `capture_card` path: verified no inner try/except around automator.py:880-882
  → `UploadError` propagates to per-card handler ccAutomator.py:1155-1169 →
  counted in `error_count`/`error_list` (no change needed there).
- `download_saved_cards` (automator.py:1155): add `raise` after the print.
- `render_project_file` (automator.py:1405): add `raise` after the print.
**Verify:** upload run where the server rejects the PUT (403/405) → card in
"Error:" summary, not "Success:"; `python -m py_compile` on touched files.

### T2 — H1: non-zero exit on failure  [TODO]
**Problem:** failing batch exits 0. Summary at ccAutomator.py:1342-1344 then
implicit exit 0 even with `error_count > 0`. Combo critical handler exits 0
(ccAutomator.py:1011-1013).
**Fix:** compute `exit_code = 1 if error_count else 0` and `sys.exit(exit_code)`
at the very end of `main()` (after `--no-close` input / "Automation complete.").
Combo handler: `sys.exit(0)` → `sys.exit(1)`.
**Verify:** run with one bogus card name → exit code 1; clean run → 0.

### T3 — C3: `_prepare_art_asset` None-return crash  [TODO]
**Problem:** failure path returns bare `None` (image_mixin.py:424); all
callers unpack 4 → TypeError. Callers: automator.py:649,
land_generator.py:160, ccAutomator.py:1277.
**Fix:** image_mixin.py:424 → `return (None, type_line, None, None)`.
automator.py:648-657 already guards `if final_art_url:` → "Using default
art" (verified). Fix the annotation to the real 4-tuple. Audit
land_generator.py:160 and ccAutomator.py:1277 for None-art handling (don't
write `artSource: null`).
**Verify:** mocked art-fetch failure → 4-tuple returned, no TypeError.

### T4 — C4: naive/aware datetime TypeError  [TODO]
**Problem:** automator.py:374 `datetime.fromtimestamp(os.path.getmtime(...))`
(naive) compared against aware-UTC `overwrite_*_dt` (parse_time_string,
automator_utils.py:35-44, returns UTC-aware) → TypeError with
`--overwrite-older-than`/`--overwrite-newer-than` in local-save mode.
**Fix:** one line — add `tz=timezone.utc` (`timezone` already imported,
automator.py:22).
**Verify:** existing local output + `--overwrite-older-than
2020-01-01-00-00-00` → clean skip, no TypeError.

### T5 — C8: requirements  [TODO]
**Problem:** `requirments.txt` (typo name, tracked) missing `selenium`.
**Fix:** `git mv requirments.txt requirements.txt`; add `selenium` line
(keep unpinned style).
**Verify:** file lists gradio_client, pillow, lxml, requests, selenium.

### T6 — H2: surface set-symbol fetch failures  [TODO]
**Problem:** `set_set_symbol` (mixins/symbol_mixin.py:57-139) fires async
`fetchSetSymbol()` then only `time.sleep(render_delay)`; 404 symbol asset →
card captured without its symbol, reported as success.
**Fix:**
- After fetch + sleep (line 136): verify via JS that the symbol `<img>`
  (src matching /setSymbol/i) has `complete && naturalWidth > 0`; fallback
  check `card.setSymbolSource` non-empty. Confirm selector against live DOM.
- On failure: clear stderr warning + `self.symbol_failures += 1` (init `0`
  in `CardConjurerAutomator.__init__`). Card still renders (warning, not error).
- Summary (ccAutomator.py:1342-1344): `Symbol failures: N` line when N > 0.
**Verify:** card from a set lacking a symbol asset → warning + summary line,
card still produced.

### T7 — H3: full-res capture in `render_project_file`  [TODO]
**Problem:** captures half-res preview canvas (`_get_canvas_data_url()`,
1005×1407) at automator.py:1376-1403 while selenium mode uses full-res
`cardCanvas` (2010×2814). **User ruling: cardCanvas is the correct source.**
**Fix:** replace the inline capture+save block with `self.capture_card(filename)`
(automator.py:947-1013) — already does cardCanvas-preferred (3 retries),
preview fallback, blank check, upload/local-save. Keep filename/metadata
generation (1385-1393). Inherits T1 `UploadError` propagation.
**Verify:** cc-file mode on `long.cardconjurer` → PNG is 2010×2814.

### T8 — H4: Scryfall timeouts / 429 / duplicate fallback  [TODO]
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
- **H6-adjacent feature:** validate the decklist against Scryfall at startup
  (before any rendering) so bad names fail fast. NOTE: `#` comment-out of
  cards in decklists is an intentional FEATURE (user ruling) — validation
  must skip `#` lines, not flag them.
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
