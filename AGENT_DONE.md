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
Commit: f0c350e.

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
Commit: 53b8141.

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
Commit: 9d3b101.

## T9 — P/T box: stateful set/restore (Karn left-shift bug)  [2026-09-19]
**Problem:** CardConjurer carries the P/T box geometry over to subsequently
loaded cards. The old auto-fit was widen-only (`_set_pt_box_abs`: `new_w =
max(new_w, base)`, fits → "leave alone"), so Karn (4/4) — loaded after
Phyrexian Dreadnought (12/12) — inherited Dreadnought's widened 423du box and
rendered with its P/T floated left of the frame edge (old
`long.cardconjurer`: Karn x=0.7338/w=0.2104, identical to Dreadnought).
**Fix (user-mandated design — keep state, move only when needed):**
- `mixins/text_mixin.py`: `_set_pt_box_abs` replaced with `_pt_state_init` /
  `_reset_pt_box_state` / `_set_pt_box(width, x)`. `apply_auto_fit_pt` is now a
  state machine over the whole session: `_pt_base` = the frame-default P/T box
  (width, x) in dialog units, read live ONCE per frame and cached;
  `_pt_current` = last set geometry (None = at home). HOME = base + manual
  `--pt-bounds-width/x`. Per card the box moves ONLY when the target differs
  from the current: narrow card at home → no dialog (fast path); wide card →
  one widen (right edge held); narrow card after a wide card → one
  `restore_pt_box()`. New `restore_pt_box()`: best-effort restore to home via
  the existing `_open_pt_dialog`/`_set_pt_dialog`/`_close_textbox_editor`
  path — logged warning on failure, never raises, state then assumed home.
  `apply_pt_bounds_mods` now defers width/x to the auto-fit when
  `--auto-fit-pt` is on (prevents double-apply of `--pt-bounds-x/width`) and
  applies only y/height deltas in that mode.
- `mixins/canvas_mixin.py` `set_frame`: invalidates the P/T state on an
  actual frame change (a different frame may have a different default box);
  no-op when the frame was already set.
- `automator.py` `__init__`: initializes `_pt_base`/`_pt_current` to None.
**Verify:**
- Offline (PASS): stub-driver state-machine test simulating the app's
  box carry-over — long.txt order yields
  base/base/base/base/base/(423,1475)/base with only 3 dialog opens (1
  base-read + 1 widen + 1 restore); consecutive identical wides de-duped; two
  different wides both set (423du then 428du); manual-delta home applied
  exactly once; frame change re-reads the base; a failed widen or restore is
  contained (warning, no exception).
- Live (PASS): `.venv/bin/python ccAutomator.py @custom.conf --debug
  --overwrite --save-cc-file decks/long.txt` → Success: 3, Error: 0. Log shows
  Kamahl 4/3 "box already at 275du x=1623du; no change", Dreadnought 12/12
  "widening to 423du x=1475du (right edge held)", Karn 4/4 "P/T box restored
  to home 275du x=1623du (was 423du x=1475du)". Re-dumped
  `long.cardconjurer`: Karn now x=0.8075/w=0.1368 (base box, matching Kamahl
  0.8074/0.1367 to rounding; right edge 0.9443 like the others) vs the old
  buggy 0.7338/0.2104; Dreadnought still 0.7338/0.2104 (widen preserved).
NOTE: the runtime interpreter is `.venv/bin/python` (has gradio_client);
system `python3` does not.
Commit: 29690da.

## Live verification of T1-T8  [2026-09-19]

All six pending live verifications (AGENT_DOING checklist) completed PASS.
Environment: app live at `http://mtgproxy:4242/` (custom.conf target),
chromium + chromedriver present, `.venv/bin/python`. No writes to the shared
image server were attempted (T1+T2 test deliberately pointed the image server
at an unreachable `.invalid` host).

**T1 — upload failure surfacing: PASS.**
- Offline (14/14 checks, mock transport): `_upload_image` 403 →
  `UploadError`; network error → `UploadError`; 200 → ok.
  `_upload_art_asset` 500 / network error → `UploadError`.
  `_save_or_upload_image` local-save failure → `UploadError`; success writes
  the file; empty bytes → warning (documented non-raising path).
  `UploadError` is a `RuntimeError` subclass → caught by the per-card
  `except Exception`.
- LIVE: selenium run of `Karn, Silver Golem` with `--image-server
  http://uploadfail.invalid:4242` → `UploadError: Network error while
  uploading art asset ...` propagated out of the pipeline → card counted as
  **Error, not captured** (`Success: 0 / Error: 1`).

**T2 — non-zero exit on failure: PASS.**
- LIVE, two paths: (a) unresolvable card name (`Bloodsoaked Chasm`, does not
  exist) → `Error: 1` → **exit code 1**; (b) the T1 upload-failure run above
  → `Error: 1` → **exit code 1**.
- Successful runs exit 0 (T6/T4/T7 runs above and in T9).
- Combo-mode critical handler `sys.exit(1)` confirmed by read
  (ccAutomator.py:1013).

**T4 — `--overwrite-older-than` datetime fix: PASS.**
- Offline (9/9 checks against the REAL `should_skip_file` +
  `parse_time_string`, file ages set with `utime`): pre-fix expression
  reproduced the `TypeError: can't compare offset-naive and offset-aware
  datetimes`; fixed code: 2h-old file + 1h cutoff → proceed; fresh file + 1h
  cutoff → skip; `--overwrite` wins; `--overwrite-newer-than` both
  directions; missing file → never skip. `parse_time_string('2h')` =
  aware-UTC `now-2h` (cutoff is "how old"; regex accepts m/h only).
- LIVE: fresh `action-news-crew_tmt_1.png` + `--overwrite-older-than 1h`
  (no `--overwrite`) → `Skipping ... file exists locally.` → `Skipped: 1`,
  exit 0 (the pre-fix code would have raised TypeError here); same file aged
  2h → re-rendered → `Success: 1`, exit 0.

**T6 — set-symbol failure surfacing: PASS.**
- Probe: on the app server, `img/setSymbols/official/` has sld/ddn/m21
  symbols but **all tmt symbols 404**.
- LIVE with `Action News Crew | tmt` (tmt/1 common): stderr `WARNING: set
  symbol for set 'tmt' was not applied (app's recorded symbol doesn't match
  the expected asset 'tmt-c.svg')...`; summary line `Symbol failures: 1
  (cards produced without their set symbol)`; card still produced
  (`Success: 1`, exit 0); card PNG visually confirmed — type line
  "Creature — Human Citizen" with NO symbol at the right.

**T7 — full-res capture in render_project_file: PASS.**
- LIVE cc-file mode on `long.cardconjurer` (Kamahl, Karn, Dreadnought) →
  3/3 output PNGs exactly **2010x2814** (PIL-verified). Pre-fix this path
  captured the 1005x1407 preview canvas.

**T8 — Scryfall timeouts / 429 / duplicate fallback: PASS (offline).**
- 26/26 mock-transport checks: `timeout=(10, 60)` passed on every call;
  429 → `Retry-After` honored (clamped to 1-60s; garbage value → default
  10s), exactly one retry then give up (`[]`); transient network error
  retried once then data returned / one retry then `[]`; 500 → no retry.
- Fallback orchestration: full-miss chain = exactly 3 DISTINCT queries
  (full filters → sets stripped keeping paper/layout → broadest), no
  byte-identical duplicate (old Fallback 1 gone); early stop on first hit.
- Live 429 under real Scryfall rate-limiting can't be forced on demand;
  logic verified against a mocked transport.

### Observations (not T1-T8 items; noted for later)

- **cc-file summary counter**: a successful cc-file render prints
  `Success: 0 / Skipped: 0 / Error: 0` even though all cards were captured
  (the cc-file branch never increments `success_count`). Cosmetic; exit code
  is still correct (0 on success, 1 on render failure via re-raise).
- **Local-save mode art renders black**: with no `--image-server`, custom
  art is saved to a local path and that *filesystem path* is applied as the
  card's art URL — the browser can't fetch it, so the art box renders black
  (seen on the T6 card). Production (`custom.conf`) uses image-server mode
  where the art is uploaded and referenced by URL; likely fine there, but
  worth a look if local mode is ever used with custom art.

(Verification campaign: no code changes were needed — all T1-T8 fixes
already in place behaved correctly.)
Commit: ae1c4c7 (notes; verification runs used no new code).

## Startup decklist validation (user-requested feature, H6-adjacent)  [2026-09-20]
**Request:** validate the decklist at startup, before the expensive
CardConjurer/Selenium phase, so bad names fail fast. NOT limited to the
Scryfall cache -- use whatever source the run resolves with: local
Scryfall cache first, then the Scryfall API (mirrors
`scryfall_query_with_fallback`). `#` lines (category headers / comment-out,
a user-ruling FEATURE) are already stripped by `parse_card_file` and are
never validated.
**Change:**
- `automator_utils.py`: new `validate_decklist(cards, label=, api_delay=)`
  (after `scryfall_query_with_fallback`). Per card: (1) local Scryfall
  cache -- name+set, then name in any set (the run's fallback chain strips
  set criteria, so a set-miss that still resolves validates fine);
  (2) Scryfall API with the broadest query the run's fallback ends on --
  `!"<name>" unique:art not:token` or `... is:token`, token-ness from the
  `# Tokens` category, same rule as automator.py:456. A card that exists
  only on the *other* side of the token boundary gets an actionable hint
  ("exists ONLY as a token -- list it under '# Tokens'") instead of a bare
  not-found. Dedupes (name, set, is-token); 0.5s between API calls
  (cache hits are free); returns failure strings (empty = all resolved);
  prints ✓/✗ per line.
- `ccAutomator.py`: wired into the selenium/combo block right after
  `parse_card_file` (before pre-flight check, before any automator
  construction): validates `cards_to_process` plus the `--prime-file`
  cards; on any failure prints the list to stderr and `sys.exit(1)`.
  New `--skip-validation` escape flag (store_true).
**Verify (2026-09-20, live API, no local cache in test env -- cache path
failed over to API as designed):**
- Unit: decklist `Dark Ritual` ✓, `Tundra | 3ED` ✓, real token `Bat` ✓
  under `# Tokens` (and ✓ in the main section too -- a non-token "Bat"
  exists on Scryfall), typo `Dark Ritull` ✗ "not found in local cache or
  on Scryfall", fake card ✗. All assertions passed.
- CLI: invalid deck → 2-card ✗ report + `Refusing to start...` + **exit
  1, browser never launched**; valid deck → "all cards resolved." →
  proceeds to pre-flight → browser; `--skip-validation` on invalid deck →
  no validation output (grep-verified) → proceeds to pre-flight.
- `python -m py_compile` clean on both touched files.
Commit: ff132e4.

## H8 — live-path text-mod tag duplication on re-run  [2026-09-20]
**Problem (per AGENT_TODO H8):** the live Selenium path
(`_apply_text_mods`, mixins/text_mixin.py) guarded tag application with
`if prefix in current_text: return` — a re-run with CHANGED values either
skipped the field (stale tag survived) or prepended a full second tag set
(silent wrong output); the guard also false-positived on substrings
(`{fontsize1}` "found" inside `{fontsize10}`). `_apply_flavor_font_mod`
stacked a new `{fontsize}` right after `{flavor}` on every run. The JSON
path (`cc_file_editor._update_tag`) and the land-generator's copy of the
same closure did replace-in-place, but with an integer-only regex (H10).
Related: `_process_all_text_modifications` (render_project_file path — the
re-run-over-saved-cards case) had a docstring claiming a `True` return the
function never had (no return statement), its "has mods" gate listed `pt_*`
args the body never applied, and was missing `pt_left` from that gate.
**Fix (single source of truth):**
- `automator_utils.py`: new pure `apply_text_tags(text, fontsize=None,
  shadow=None, kerning=None, left=None, up=None, down=None, bold=False)` —
  per tag kind: existing tag (anchored, decimal/negative-aware pattern
  `\{kind-?\d+(?:\.\d+)?\}`, so `{fontsize64pt}` and `{fontsize10}` are
  never mis-matched) is UPDATED in place; missing tag prepended; duplicated
  stale tags converge to one at the first's position (repairs text already
  corrupted by the old bug); `{bold}` wrap idempotent and existing bold
  never stripped; unchanged input → equal string returned so callers skip
  the DOM write. Docstring documents all of it.
- `mixins/text_mixin.py`: `_apply_text_mods` core replaced with the helper
  + `new_text == current_text` no-op check (no redundant write/re-render);
  `_apply_flavor_font_mod` applies the flavor fontsize to the part after
  `{flavor}` via the helper (no more stacking); `_process_all_text_modifications`
  now: honest docstring, `return False` early / `return any_text_mod_made`
  at end, gate includes `pt_left`, and the body actually applies the P/T
  text mods (mirrors the live per-card path, automator.py:767).
- `cc_file_editor.py`: `_update_tag` delegates to the helper (one-line).
- `land_generator.py`: its nested `_update_tag` copy delegates too; the
  same flavor-stacking bug in its rules block fixed to the same REPLACE
  semantics; now-dead `import re` removed; `apply_text_tags` imported.
  All three tag-applying paths (live Selenium, JSON edit, land generator)
  are now the same code.
**Verify (2026-09-20):**
- `python -m py_compile` clean on automator_utils.py, mixins/text_mixin.py,
  cc_file_editor.py, land_generator.py, ccAutomator.py.
- Unit tests (`test_apply_text_tags.py`, repo root; `apply_text_tags` +
  `CcFileEditor._update_tag` delegation + a full `apply_edits`
  run1/run2-same/run3-changed scenario): prepend; REPLACE-in-place (the H8
  changed-values scenario, single and multi-tag); duplicate convergence
  (front/mid/triple); decimal + negative values; `{fontsize64pt}` untouched;
  `{fontsize1}` vs `{fontsize10}` no false-positive; bold idempotent + never
  stripped; unchanged → equal (no-op guard); flavor first-run / re-run /
  changed-run; all six delegation kwarg names.
  **34/34 passed** (`.venv/bin/python test_apply_text_tags.py`, 2026-09-20;
  one test expectation initially assumed the wrong prepend accumulation
  order — the CODE was correct, the expectation fixed to match the old
  prepend semantics).
- Live re-run verification (same card, changed `--title-font-size`, saved
  `.cardconjurer` re-rendered) still pending — needs the app/browser.
**Scope note (flagged for user):** the helper's decimal-aware regex also
resolves deferred **H10** (integer-only `_update_tag` regex) as a side
effect of converging on one shared helper — recommended to keep (one code
path); noted in AGENT_TODO.
Commit: 41c31f5.
