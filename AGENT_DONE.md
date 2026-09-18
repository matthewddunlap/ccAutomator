# AGENT DONE — completed items

## Notes created  [2026-09-18]
Wrote the four handoff files (`AGENT_OVERVIEW.md` with the full review + user
rulings, `AGENT_TODO.md` with T1–T8 + deferred list, `AGENT_DOING.md`,
`AGENT_DONE.md`). Commit: 88567ad.

## T1 — C5: surface upload failures  [2026-09-18]
**Change:**
- New `class UploadError(RuntimeError)` in `mixins/image_mixin.py`; exported
  via `mixins/__init__.py`; imported in `automator.py`.
- `_upload_image`, `_upload_art_asset`, `_save_or_upload_image` (local-save
  branch) now `raise UploadError(...) from e` after their existing error
  prints, instead of returning silently. The "no destination configured"
  branch in `_save_or_upload_image` deliberately stays a warning (the json
  path legitimately falls back to the remote Scryfall URL there).
- `download_saved_cards` (automator.py): a timed-out/failed project-file
  download now raises (fatal — a lost .cardconjurer file must not be a
  silent success).
- `render_project_file` (automator.py): broad except now re-raises so the
  caller's handler exits non-zero.
- Net effect: a failed card-PNG upload propagates out of `capture_card`
  (no inner try around it — verified) → per-card handler in
  ccAutomator.py counts the card in `error_count`/`error_list` instead of
  `results['captured'] += 1`.
**Verify:** `python -m py_compile` clean on all touched files. End-to-end
upload-failure run pending (needs a server that rejects the PUT).
Commit: 76519cd.

## T2 — H1: non-zero exit on failure  [2026-09-18]
**Change (ccAutomator.py):**
- End of `main()`: after "Automation complete.", `if error_count: sys.exit(1)`
  — a batch with per-card failures now exits 1 (fatal exceptions already
  exit 1 in the outer handler; clean/skipped runs still exit 0).
- Combo-mode critical handler: was printing the error and falling through to
  `sys.exit(0)` unconditionally; now `sys.exit(1)` inside the except, with
  the success-path `sys.exit(0)` after it.
**Verify:** `python -m py_compile` clean. Runtime check (bogus card name →
`echo $?` = 1) pending live run.
Commit: a867ec1.

## T3 — C3: `_prepare_art_asset` None-return crash  [2026-09-18]
**Change (mixins/image_mixin.py):**
- Both failure paths that returned inconsistent values now return the full
  4-tuple: `return None` (original-art fetch failed) and
  `return None, None` (no Scryfall art_crop URL) → `return (None,
  type_line, None, None)`.
- Signature annotation was `-> tuple[str, str]`; now
  `-> tuple[Optional[str], Optional[str], Optional[int], Optional[int]]`
  with a docstring stating the "art is None → use default art" contract.
- Audit of all callers: automator.py (~649) guards `if final_art_url:`
  ("Using default art"); land_generator.py:167 falls back to the Scryfall
  art_crop URL; ccAutomator.py:1280 guards `if final_art_url:`. None of them
  write `artSource: null` on the None path.
**Verify:** `python -m py_compile` clean; AST scan of
`_prepare_art_asset` confirms all top-level returns are 4-tuples (the only
2-tuples are inside the nested `get_dims` helper, which is correct).
Commit: 27f7c68.

## T4 — C4: naive/aware datetime TypeError  [2026-09-18]
**Change (automator.py, local-save branch of should_skip_file):**
`datetime.fromtimestamp(os.path.getmtime(output_path))` →
`datetime.fromtimestamp(os.path.getmtime(output_path), tz=timezone.utc)`
(`timezone` was already imported at automator.py:22).
**Verify:** `python -m py_compile` clean; snippet reproduced the old
`TypeError: can't compare offset-naive and offset-aware datetimes` with the
old expression and confirmed the fixed expression compares against
`parse_time_string`'s aware-UTC values without error. Full end-to-end run
with `--overwrite-older-than` pending (needs the app/server).
Commit: 88309f9.

## T5 — C8: requirements  [2026-09-18]
**Change:**
- Renamed `requirments.txt` → `requirements.txt`.
- Added the missing `selenium` dependency (it was imported throughout but
  absent from the file).
- Discovery: the file was never tracked — `.gitignore` has a blanket
  `*.txt` rule (for decklists). Added `!requirements.txt` negation so the
  dependency list is version-controlled while decklists stay ignored.
**Verify:** `git check-ignore -v requirements.txt` → matches the negation
(no longer ignored); `git status` shows it untracked-and-addable; file now
lists gradio_client, pillow, lxml, requests, selenium.
Commit: 69389ce.

## T6 — H2: surface set-symbol fetch failures  [2026-09-18]
**Change:**
- `mixins/symbol_mixin.py`: new `_verify_symbol_loaded(set_code, rarity,
  source)`, called at the end of `set_set_symbol` (after the existing
  fetch + `render_delay` sleep). It checks the app's own record —
  `card.setSymbolSource` holds the RESOLVED asset URL (confirmed from
  saved projects, e.g. `.../img/setSymbols/official/ddn-m.svg`):
  - 'stale' — for the 'cardconjurer' source (default; main call site
    automator.py:696-699 always passes set+rarity+source) the expected
    asset is `{set}-{c|u|r|m}.svg`; recorded URL not matching → the fetch
    never applied to THIS card (previous card's URL still there).
  - 'none' — no URL recorded at all.
  - 'failed' — URL looks right but the asset doesn't load: we load it
    in-page with `crossOrigin='anonymous'` (same way the app draws it to
    cardCanvas) so we see the same 404/CORS result the app sees.
  - JS error → "could not verify", NOT counted (unverifiable ≠ failure).
  Each counted case prints a stderr warning and does
  `self.symbol_failures += 1`. Card still renders (warning, not error).
- `automator.py` `__init__`: `self.symbol_failures = 0` (next to
  `set_symbol_source`).
- `ccAutomator.py` final summary: `Symbol failures: N (cards produced
  without their set symbol)` when N > 0 (`getattr`-defensive; only
  selenium + cc-file paths reach the summary, both with `automator`
  defined; json/combo `sys.exit` earlier).
**Verify:** `py_compile` clean on symbol_mixin.py, automator.py,
ccAutomator.py. Live check pending: card from a set lacking a
symbol asset → stderr warning + summary line, card still produced.
Commit: (this commit).

## T7 — H3: full-res capture in `render_project_file`  [2026-09-18]
**Change (automator.py):**
- `render_project_file` (per-card loop): replaced the inline preview-canvas
  capture+save block (`_get_canvas_data_url()` → base64 decode →
  `_upload_image` / local `open(...,'wb')` — half-res, 1005×1407) with a
  single `self.capture_card(filename)` call. `capture_card`
  (automator.py:953) prefers the full-res `cardCanvas` (2010×2814, 3
  retries), falls back to the preview canvas, blank-checks the frame, and
  handles upload/local-save; upload failures raise `UploadError` (T1) so a
  failed card can no longer be counted as captured.
- Kept the pre-capture canvas-stabilization call and the
  metadata/filename generation (`set_code`/`collector_number` from
  `card_metadata_list[i]` with `MTG`/`0` defaults,
  `_generate_final_filename`).
- No import churn: `base64` still used elsewhere (automator.py:896/945/999).
**Verify:** `py_compile` clean. End-to-end pending: cc-file mode on
`long.cardconjurer` → output PNG is 2010×2814 (needs the app/server).
Commit: (this commit).

## T8 — H4: Scryfall timeouts / 429 / duplicate fallback  [2026-09-18]
**Change (automator_utils.py):**
- New `scryfall_search(query)` helper: `requests.get(..., timeout=(10, 60))`
  (the four inline calls previously had no timeout at all); on 429 → sleep
  `Retry-After` (default 10s, capped 60s) and retry once; transient network
  errors retried once then reported; returns the `data` list.
- Replaced the four inline `requests.get` blocks in
  `scryfall_query_with_fallback` with the helper.
- Deleted the old "Fallback 1" (stripped `not:covered`, which
  `build_scryfall_query` never adds → byte-identical duplicate of Try 1);
  surviving fallbacks renumbered (log messages now Step 1 / Step 2).
**Verify:** `py_compile` clean; AST parses; no dangling refs
(`is_basic_land`/`current_*` only remain inside `build_scryfall_query`);
`time`/`sys` already imported. Live check pending: Scryfall 429 behavior
under rate limit.
Commit: (this commit).
