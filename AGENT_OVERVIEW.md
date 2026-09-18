# AGENT OVERVIEW — ccAutomator review & fix campaign

**For future agents:** This directory contains the working notes for an ongoing
code-review → fix campaign on this repo. Read this file first, then:

- `AGENT_TODO.md`  — every work item, broken into small tasks with problem / proposed fix / verification
- `AGENT_DOING.md` — the item currently in flight, with partial progress notes
- `AGENT_DONE.md`  — completed items, with what changed and how it was verified

**Conventions:** when you start an item, move it to DOING; when finished (or
abandoned with reason), move it to DONE and record the outcome. Keep all four
files current — they are the handoff if a context window overflows. Do not
delete items from DONE.

---

## Project context

`ccAutomator` drives the live CardConjurer MTG-card web app via Selenium to
bulk-produce custom cards (custom art, title/type-line/P-T auto-fit sizing, set
symbols, PNG capture/upload). ~9,500 lines of Python. Five CLI modes:

- `selenium` (primary) — drives the live app, captures full-res PNGs
- `cc-file` — renders an existing `.cardconjurer` project file
- `edit` — JSON-edits a project file (via `cc_file_editor.py`)
- `combo` — selenium prep → JSON edit → render
- `json` — generates `.cardconjurer` directly, no browser (`seventh_generator.py`)

Auto-fit is pure math from per-glyph tables (`title_glyphs.json`,
`type_glyphs.json`, `pt_calib.json`) calibrated against the live renderer
(see README "Auto-fit calibration").

**User's stated focus (2026-09-18): only `selenium` mode matters right now.**
Edit/combo/json-mode bugs are deferred (see TODO "Later review").

---

## Full code review (baseline findings, 2026-09-18)

### Architecture (the good bones)

- Clean mixin composition: `CardConjurerAutomator(CanvasMixin, TextMixin, ImageMixin, PrintMixin, CollectorMixin, SymbolMixin)`.
- The auto-fit engine (title/type/P/T) is the strongest part: pure-math linear fits (`base + slope·fontsize` + per-gap kerning) from per-glyph tables calibrated against the live renderer with a magenta-ink technique. No per-card render loops, documented derivations, post-verification while-loops, sensible glyph-table fallbacks. The README's design notes (e.g. deliberately *not* adding a set-symbol position table, with the verification data for the decision) are exactly how you want decision records written.
- Robust overlay handling: `apply_rules_text_bounds_mods` / `apply_pt_bounds_mods` / `apply_auto_fit_pt` all guarantee `#textbox-editor` dismissal via `finally: self._close_textbox_editor()` (the recent commits).
- Config-file support (`@conf`, full-line + inline comment stripping, multi-file override) works correctly — traced `custom.conf` through the parser.

### Critical bugs (supported workflows that can't work)

**C1. `combo` mode crashes every run and exits 0.**
`ccAutomator.py:966-967` (and again `:1082-1084`) pass `type_gap=args.type_gap, min_kerning=args.min_kerning` to `CcFileEditor.apply_edits`, whose signature (`cc_file_editor.py:50-54`) accepts neither → guaranteed `TypeError`. The exception is swallowed by the broad handler at `ccAutomator.py:1011-1013`, which prints to stderr and calls `sys.exit(0)` — so a fatal combo run **reports success**.

**C2. `edit`/`combo` with `--auto-fit-type`: `NameError`.**
`cc_file_editor.py:8` imports only `autofit_title, autofit_type`, but `:155` calls `estimate_set_symbol_left(...)` (defined in `automator_utils.py:723`). Any card with a `setSymbolSource` hits `NameError`. In combo mode this is masked by C1's exit-0. (`mixins/text_mixin.py:706` does it right with a local import — the inconsistency is the tell.)

**C3. Art-fetch failure crashes every `_prepare_art_asset` caller.**
`mixins/image_mixin.py:424` returns bare `None`, but all callers unpack 4 values — `automator.py:649`, `land_generator.py:160`, `ccAutomator.py:1277` → `TypeError: cannot unpack non-iterable NoneType`. The intended graceful path ("fall back to default art") becomes a per-card crash. The annotation `-> tuple[str, str]` is wrong too (it's a 4-tuple on the success path).

**C4. `--overwrite-older-than`/`--overwrite-newer-than` crash in local-save mode.**
`automator.py:373-380` builds `local_mod_time` with naive `datetime.fromtimestamp(...)` and compares it against the aware UTC `self.overwrite_older_than_dt` → `TypeError: can't compare offset-naive and offset-aware datetimes`.

**C5. Failed uploads are reported as captured.**
`_upload_image` (`mixins/image_mixin.py:107-142`) prints HTTP errors but never raises; the caller does `results['captured'] += 1` (`automator.py:882`). With `--upload-path` — the primary production use per both config files — a card whose PNG never reaches the server shows up as a success. Same pattern in `_save_or_upload_image`.

**C6. `--card-selection cardconjurer` is a dead branch.**
`automator.py:418-433`: the branch body is a `pass` plus dev-note comments ("rely on methods not fully shown in the snippet", "TODO: Implement full CC logic"). Every card in that mode is counted as captured=0/errors, yet the CLI advertises the option and `custom.conf` documents the strategy family.

**C7. `--full-art-basic-land` / `--generate-lands` cannot run.**
`land_generator.py` loads `templates/full_art_basic_lands.cardconjurer` — there is **no `templates/` directory** in the repo. Both modes die with `FileNotFoundError`.

**C8. Fresh install can't run.**
`requirments.txt` (typo in the filename) lists `gradio_client, pillow, lxml, requests` — **`selenium` is missing**, though it's imported throughout.

### High severity (silent wrong output, misleading state)

**H1. Exit-code policy is inverted in places.** Broad `except Exception` + `sys.exit(0)` (`ccAutomator.py:1011-1013`), and `render_project_file` swallows all errors ("Error rendering project file", `automator.py:1405-1406`) so the caller still exits 0. A failing batch is indistinguishable from a successful one to any caller/cron.

**H2. Set-symbol fetch failure is silent.** `mixins/symbol_mixin.py` fires async `fetchSetSymbol()`, then only `time.sleep(render_delay)`. A 404 on the symbol asset yields a card captured *without* its set symbol, reported as success.

**H3. Two capture resolutions for the same card.** Selenium-mode `capture_card` uses full-res `cardCanvas` (2010×2814); `render_project_file` (`automator.py:1376-1403`) captures the **half-res preview canvas** (1005×1407). `cc-file` mode output is half the intended size with no warning. **User ruling: the right selection is `cardCanvas` (2010×2814).**

**H4. Scryfall client gaps.** In `scryfall_query_with_fallback` (`automator_utils.py:325-434`): no `timeout=` on the `requests.get` calls (lines ~367/394/410/426) — a hung connection hangs the whole run; no 429/Retry-After handling (Scryfall rate-limits hard in bulk); and "Fallback 1" strips `not:covered`, which `build_scryfall_query` never adds — fallback 1 is a byte-identical duplicate request, and the log line is stale.

**H5. Full-art-land mode is half-implemented.** `ccAutomator.py:1312-1314`: `if args.upload_path: # … upload … pass` — the upload is a **stub**; `:1283-1284` applies only Title mods with a `# … apply other mods …` placeholder (Type/P/T/rules mods never applied).
**User ruling (2026-09-18):** Lands don't have P/T, so P/T mods are N/A there — but **Type mods are needed**. Full-art lands do **not** get a title. Likely mostly intentional; verify Type mods are applied and title is appropriately skipped. Marked later review.

**H6. Deck-file parsing footguns.** `parse_card_file` (`automator_utils.py:147-192`): lines starting with `#` are *category headers* — so `decks/prime.txt`'s first two lines (`#1 Gravedigger`, `#1 Okk`) are silently discarded and never primed. And `"3 x Dark Ritual"` parses as card `x Dark Ritual`.
**User ruling (2026-09-18): `#` comment-out of cards is a FEATURE, not a bug.** Related feature request: **validate the decklist as actual cards at start** (Scryfall existence check) instead of discovering bad names mid-render.

**H7. `apply_set_filters` is a no-op placeholder** (`automator_utils.py:223-243`, docstring admits it) and is **imported but never called** (`ccAutomator.py:12`) — dead code describing behavior that happens elsewhere.

**H8. Live-path text mods duplicate tags on re-run.** `_apply_text_mods` (`mixins/text_mixin.py:54-141`) guards with `if prefix in current_text: return` — a re-run with *changed* values skips the card entirely, or prepends a full second tag set. The JSON path (`CcFileEditor._update_tag`) replaces correctly — the two paths diverge. Related: `_process_all_text_modifications`' docstring claims a `True` return it never has, and its "has mods" gate includes P/T args the body never applies.

**H9. Scryfall cache false-success.** `scryfall_cache.py:90-95`: `except (BlockingIOError, IOError)` catches **every** `requests` exception (`RequestException` subclasses `IOError`) — a failed 500 MB download prints "Cache update finished by another instance." and returns `True` for a cache that was never built. Also: `DB_FILE`/`LOCK_FILE` hardcoded to `/data/ccAutomator/…`; the 500 MB JSON is fully loaded into memory before insert.

**H10. Decimal tag updates silently no-op.** `_update_tag` (`cc_file_editor.py:238-253`, duplicated in `land_generator.py:336-342`) matches `\{tag-?\d+\}` — integer-only. A `{fontsize3.5}` never matches, so the new tag is **prepended** and the old tag survives.

**H11. `json` mode frames colorless non-lands as artifacts.** `seventh_generator.py:238-239`: zero-color non-land → code `'a'` (Artifact frame). Also: `seventh_generator.py:6-7` does `sys.modules['gradio_client'] = MagicMock()` to dodge a real import, and hardcodes `upscale_art = True` regardless of CLI intent.

### Medium / low

- **Stale selector cache** — `_cached_canvas_selector` (canvas_mixin.py:51) never invalidated after a page reload; the comment admits it.
- **Driver leak on init failure** — the WebDriver is created early in `__init__` (automator.py:58-257); a later init failure skips the `with`-block cleanup.
- **Ilaria upscaler** — fixed temp filename `ilaria_input_{filename}` in `/tmp` (cross-run collision); assumes the gradio result is a local path (`image_mixin.py:219-298`).
- **`generate_safe_filename`** — NFKD+ascii strips collide ("A/B" vs "A-B"); no guard against an empty result.
- **`save_cardconjurer_file`** — non-atomic write; unsanitized deck name into `os.path.join`.
- **`_save_card_to_browser_storage`** — alert timeout → "might have saved or failed" (automator.py:1042-1089); `download_saved_cards` picks by newest mtime (wrong file under interleaved runs).
- **Leftover DEBUG prints** in production paths (ccAutomator.py:1017-1018, automator.py:207); dev-note comments left in shipped code (automator.py:418-433, image_mixin.py:476-494).
- **Duplicated pre-flight existence check** (ccAutomator.py:788-844 vs :1139-1152) with a bare `except: pass` around the HEAD request.
- **`main()` is ~1,300 lines** orchestrating 5 modes; mode dispatch is the natural seam for splitting it up.
- **`except (NoSuchElementException, Exception)`** (print_mixin.py:81) — redundant.
- **No tests anywhere** — the pure-math auto-fit core is verified only by the calibration scripts.

### Resolved question

The `artZoom` factor-vs-percentage uncertainty in `autofit_art_position`'s comments: the saved projects (`dual-land.cardconjurer`, `long.cardconjurer`) use `artZoom` ≈ 2.71–2.76 and the json generator defaults to `0.67` — the convention is a **scale factor**, consistent across all three. The hedging comments can be replaced with the verified fact.

---

## User amendments & rulings (2026-09-18)

| Item | Ruling |
|------|--------|
| C1, C2, C6 | **Deferred** — user is only interested in `selenium` mode right now |
| C7 | **Deferred** — user has the template file and has added a `.cardconjurer` file to `templates/`; review the full-art-land flow later |
| C3, C4, C5, C8 | **Fix now** (in this order: C5/H1 → C3 → C4 → C8) |
| H3 | Fix: capture from **`cardCanvas` (2010×2814)** in `render_project_file` |
| H5 | **Deferred** — user note: lands have no P/T (P/T mods N/A), Type mods ARE needed, full-art lands don't get a title; likely intentional |
| H6 | `#` comment-out is a **feature**; add **startup decklist validation** (Scryfall check before rendering) as a future feature |
| H8, H10 | **Deferred** (later review) |
| Test suite | **Deferred** (later review) |
| H7, H9, H11, all Medium/Low | Not explicitly addressed — parked in TODO "Later review" |
