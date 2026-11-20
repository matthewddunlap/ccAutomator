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

## #3 PERF — fixed sleeps → state-based waits  [2026-09-21]
**Outcome: NET WIN, shipped.** A/B #3 (final): **new 4m58.4s vs baseline
5m05.7s (−7.3s)**, EXIT 0 both, 3/3 cards uploaded, all 3 output PNGs
**byte-identical** (7.4–7.8 MB full-res, compared via
`compare_pngs.py ab_base ab_new` — byte-then-PIL).
**Change (2 commits on user-agent):**
- **989c7a9** — priming canvas wait: stability-only, not change-detection
  (automator.py, both priming sites: CC-mode ~421 and
  `_prime_via_scryfall` ~1190). Pre-existing defect: `wait_for_change=True`
  burned the full 20s STABILIZE_TIMEOUT when the same card was already
  showing (app persists last card in browser storage) or the change was
  missed between reads — 20–40s/run wasted in BOTH old and new code.
  Priming only needs "renderer warm with ANY print" →
  `self.current_canvas_hash =
  self._wait_for_canvas_stabilization(None, wait_for_change=False)`.
- **9d03303** — the perf change (6 files + new test, +228/−31):
  `canvas_mixin.py` gets `_wait_for_render(timeout=None)` +
  `_get_canvas_probe_hash()` (downsampled 64×90 offscreen probe cached on
  `window.__ccProbe` — the full-canvas `toDataURL`+hash-loop read cost
  0.3–8s each and made A/B #1 a +14s regression), and
  `_wait_for_canvas_stabilization(..., timeout=None, probe=False)`;
  `render_delay` is now a CAP, not a floor (poll until stable, warn-and-
  continue on cap expiry, never raises); `_wait_for_render` deliberately
  does not write the probe hash back to `current_canvas_hash` (different
  basis than the full-res gates). All 9 text_mixin `time.sleep(render_delay)`
  sites, the automator.py catch-all, 2× `sleep(2)` (project flows,
  cap 2s) and 2× `sleep(1.5)` (load flows, cap 1.5s), and the
  symbol_mixin fetch wait now call it. `--render-delay` help text updated.
  Left unchanged on purpose: image_mixin.py:109 art-apply
  `wait_for_change=True` (waits for a real change; settles 0.7–1.1s),
  rate/network pacing sleeps (Scryfall 429, `api_delay`, retry backoff).
- `test_wait_for_render.py` (repo root, 8 checks, stub driver): stable
  canvas returns fast (<1.0s), uses cheap probe not full-res, does not
  clobber `current_canvas_hash`, render_delay=0 → zero driver calls,
  changing canvas honors caps, stabilizer default stays full-res,
  signature has timeout+probe params. **8/8 pass.**
**Verify:** A/B #1 (+14s regression → heavy full-canvas reads), A/B #2
(+16s → priming 20s burn, diagnosed from log silence + "change detected:
False" counts), A/B #3 (WIN above). Baselines run-to-run variance ~±12s
(4m51.1 / 5m03.5 / 5m05.7s). Tests: `test_wait_for_render.py` 8/8,
`test_apply_text_tags.py` 34/34; `py_compile` clean on all touched files.
Logs: `$CLAUDE_JOB_DIR/tmp/ab3_base.log`, `ab3_new.log` (job ac1fc71f).
Commits: 989c7a9 (priming fix), 9d03303 (perf).

## #4 H9 — scryfall_cache false-success + hardcoded paths  [2026-09-21]
**Problem:** `except (BlockingIOError, IOError)` wrapped the entire
`update_scryfall_cache` body, and every `requests` exception subclasses
`IOError` — so ANY network failure (DNS, refused, timeout, 5xx via
`raise_for_status`) was reported as "Another instance is currently
updating the cache" and the function returned **True** although nothing
had been updated (holding the EX lock and re-flocking LOCK_SH on the same
fd succeeds instantly, so the "waiting" was fiction). Also: hardcoded
`/data/ccAutomator/` paths (uncaught FileNotFoundError on this dev box,
where /data doesn't exist — silently absorbed by get_card's except); the
staleness check accepted ANY existing file as fresh for a week, including
a zero-byte DB that `sqlite3.connect()` creates; the streaming download
had no timeout (could hang forever); the conversion held the whole ~500MB
JSON array in memory plus a second json.dumps'd copy while inserting.
**Change (scryfall_cache.py rewritten + new test_scryfall_cache.py):**
- Lock contention is now handled ONLY by `except BlockingIOError` around
  the `flock(EX|NB)` call — the one case that genuinely means "another
  instance". After waiting, the result is VERIFIED: True only if a usable
  cache exists (fresh, when `force`); otherwise honest False + warning.
- Expected update failures (requests.RequestException, sqlite3.Error,
  ValueError, OSError) caught in one targeted except → real error printed,
  False returned. 60s failure cooldown so a dead network does not make
  every card lookup pay the connect timeout again.
- `_db_is_usable()` (readonly open, `cards` table, COUNT(*)>0) gates the
  staleness check and `_get_conn`; on a failed update `_get_conn` raises
  instead of creating an empty 0-byte DB. `get_card`'s existing
  `except Exception → None` preserves the API fallback at every call site
  (ccAutomator.py:812/1154 pre-flight + skip-check,
  automator_utils.py validate_decklist + scryfall_query_with_fallback —
  all audited: a failed cache lookup degrades to "assume it needs work",
  which is the conservative direction).
- Paths: `DATA_DIR = os.environ.get("CC_AUTOMATOR_DATA_DIR",
  "/data/ccAutomator")` (production default unchanged); dev-box guard
  (`_cache_dir_ready`): default dir absent on the machine → no creation,
  no ~500MB download, immediate False → API fallback; explicit env var =
  opt-in bootstrap.
- Download `timeout=(20, 300)`; conversion now streams via
  `_iter_json_array_elements()` (1MB chunks + `raw_decode`, elements
  spanning chunk boundaries, unicode, nested) with 1000-row batch inserts;
  zero-row downloads refused (no "fresh" empty cache).
**Verify:** `test_scryfall_cache.py` **17/17** (false-success regression;
cooldown throttling; contention usable→True / none→False /
stale+force→False; chunk-boundary streaming at 16-byte chunks; truncation
/ not-array / empty-file errors; 1503-card batch boundary; zero-row
refusal; fresh-cache short-circuit with a network-call sentinel;
missing-default-dir guard asserts no dir created + no network; full
fake-download success with get_card round-trip). `test_apply_text_tags.py`
34/34 + `test_wait_for_render.py` 8/8 (no regressions); py_compile clean.
Dev-box smoke: get_card → None in 0.00s, /data NOT created. Live run
(2026-09-21, `decks/long.txt @custom.conf --debug --overwrite
--save-cc-file --upload-path /local_art/card_images/h9_new`): **EXIT 0,
Success 3 / Skipped 0 / Error 0**, 5m12.5s (within the ~±12s run band),
and `compare_pngs.py ab_new h9_new` → **all 3 cards BYTE-IDENTICAL**
(7.4–7.8 MB) to the A/B #3 verified set. Log:
`$CLAUDE_JOB_DIR/tmp/h9_new.log` (job ac1fc71f).
Commit: da1b06d.

## #5 DATA-DIR + where the 5 minutes goes  [2026-09-22]
**User request (verbatim):** "Whatver /data is being used for should be a
runtime configurable path. And the state based waits saving just 7 seconds
seems ridiculously low."

**(a) Runtime-configurable data dir — DONE (live-verified):**
- `scryfall_cache.py`: `configure_data_dir(path)` — repoints
  DATA_DIR/DB_FILE/JSON_FILE/LOCK_FILE, sets `_data_dir_explicit`
  (explicit choice = opt-in to bootstrapping that location even when it
  doesn't exist yet), resets the singleton's connection so a previously
  opened DB for another location is never served. `_cache_dir_ready()`
  keys off the flag (env var OR configure()) instead of re-reading the
  env var.
- `ccAutomator.py`: `--data-dir` flag (works from @conf files), wired
  right after `args = parser.parse_args()` (all cache imports are lazy —
  earliest safe point) + prints the resolved dir.
- `mixins/image_mixin.py`: `_get_scryfall_art_crop_url` is CACHE-FIRST
  (`ScryfallCache().get_card(name, set)` first; no-op → None on machines
  without a cache), API fallback unchanged, extraction shared via local
  `extract()`. Verified on the hot path (main flow passes no
  scryfall_data to `_prepare_art_asset` → all 3 cards log "Using local
  Scryfall cache ...").
- `test_scryfall_cache.py`: +`test_configure_data_dir_repoints_and_resets_
  singleton` (repoint, singleton reset, explicit-dir opt-in bootstrap
  allowed, honest None fallback, no empty DB left) → **18/18**.

**(b) Where the 5 minutes goes — ANSWERED (timestamped A/B, 2026-09-22):**
- Method: per-line timestamped logs, same 3-card deck
  (`decks/long.txt @custom.conf --debug --overwrite --save-cc-file`),
  sequential on the same app instance: **API side 306.8s (EXIT 0)** vs
  **cache side 289.6s (EXIT 0)** — delta inside the ±12-14s run-noise band
  measured in earlier A/Bs. `compare_pngs.py`: **all 3 PNGs
  byte-identical** in both `ts_api` vs `ts_cache2` AND `ts_cache2` vs
  `h9_new` (the previously verified set) — end-to-end output equivalence.
  Logs: job ac1fc71f tmp `ts_ts_api.log`, `ts_ts_cache2.log`.
- **Breakdown (both sides, same shape):** canvas waits/re-renders
  113-127s (~40%), startup/setup/priming/UI-search 94-103s (~30%),
  mods/autofit/symbols 18-29s (6-10%), art/capture/save ~9s (3%), other
  ~16s (5%). The single biggest steps (7-19s each: [Debug] Wait reads,
  "Bypassing further filters", "Ensuring Autofit is enabled", Rules
  Bounds dialogs) are the CardConjurer app's OWN main-thread work
  (re-render, autofit, search index) delaying our execute_script.
- **Why the state-wait change saved only ~7s:** the app does 8-9s of work
  per render pass in BOTH designs (the old code's next selenium op queued
  behind the same work); the blind sleep only added the ~1.5s residual
  after the app finished, which the state wait removed. The 5 minutes is
  app CPU work, not our waits or our network.
- **Cache's honest effect:** ~1-5s of Scryfall API calls removed per run
  on this box (search ~0.17s + art meta ~0.12s per card, fast network);
  production value = call COUNT (2/card → ~0) = less 429 exposure on big
  decks. Art BYTES still come from Scryfall's CDN in both modes (cache
  stores metadata, not images).

**(c) Search cache-first (`_resolve_prints_cache_first`) — verified,
commit is the user's call (per plan: "present to the user with
numbers"):**
- Implemented by the prior session in the working tree (while its own
  notes said "deliberately NOT cache-ified" — reconciled here).
- **DEAD-PATH BUG found in this session's verification (fixed):** the
  resolver read `c.get("game")`, but current Scryfall JSON stores a
  `games` LIST (e.g. `["paper","mtgo"]`) — every print was dropped, so
  the resolver silently ALWAYS fell back to the API (first cache A/B run
  showed no "Resolved N local cache print(s)" line). Fix: read `games`,
  with legacy `game`-string support (split on `+ ,`/whitespace).
  Regression suite: new `test_cache_first_resolve.py` **8/8** (games
  regression, legacy string, no-field drop, token layout, art_series,
  include/exclude/set-target, custom `--scryfall-filter` → API path,
  dev-box no-cache → None with zero network, oldest-first order).
- **`not:covered` investigated (the one filter NOT reproducible
  locally):** it is a search-engine-only concept — bisection shows it
  excludes box contents, judge gifts (e.g. Phyrexian Dreadnought g10),
  premium decks, some promos, while other promos survive; NO field in the
  bulk JSON marks it. Consequence: local candidates can include prints
  the API excludes. Empirically (live Scryfall search, 2026-09-22)
  `unique:art`'s representative is the EARLIEST release, so with
  `--set-selection earliest` (current config) local and API pick the SAME
  print (verified: ONS/MIR/USG, byte-identical PNGs). With
  `latest`/`random`/`all` the local pool can contain the covered prints
  (e.g. Dreadnought g10, Karn pal99/v10) → a DIFFERENT print may be
  picked. Documented in the resolver docstring.
- **Verify (2026-09-22):** cache run log shows the path LIVE: "Resolved
  4/2/3 local cache print(s)" + "Cross-referencing 4/2/3 ..." +
  "Using local Scryfall cache" per card; selection lands on the same
  ONS/MIR/USG prints; EXIT 0; PNGs byte-identical (see (b)).
- **Tests (2026-09-22):** `test_cache_first_resolve.py` 8/8 (new),
  `test_scryfall_cache.py` 18/18, `test_apply_text_tags.py` 34/34,
  `test_wait_for_render.py` 8/8; py_compile clean on all touched files.

**Commits (branch user-agent, 2026-09-22):**
- **6a19ea8** "Scryfall cache dir runtime-configurable + cache-first
  per-card art" (a): scryfall_cache.py configure_data_dir, ccAutomator.py
  --data-dir, mixins/image_mixin.py, test_scryfall_cache.py (18/18).
- **76b1635** "Cache-first print resolution for the search path" (c):
  scryfall_cache.py get_prints, automator.py _resolve_prints_cache_first
  (+ the games-field dead-path fix), test_cache_first_resolve.py (8/8).
- Notes commit: this one.
**User call (2026-09-22): KEEP BOTH PARTS** (presented with the numbers
above; earliest-selection equivalence + latest/random/all not:covered
risk accepted and documented).

## Accented names (sanitized decklists) + auto missing-card decklist  [2026-11-18]

**Problem (user report 2026-11-18):** decklists with accent-stripped names
('Ghazban Ogre', 'Ifh-Biff Efreet' — the user's hand-written
`decks/missing.dek`) errored even though Scryfall resolves them.  Two
expected behaviors were missing: (1) the Scryfall↔Card-Conjurer matching
must work across the accent boundary, (2) a run should AUTO-GENERATE a
re-runnable decklist of the errored cards (the user had to hand-copy them
from the summary).

**Root cause (verified against the live app + Scryfall, 2026-11-18):**
- The app's own import search is fine: it queries Scryfall with unquoted
  `name=Ghazban_Ogre` (js/creator-23.js `fetchScryfallData`), which is
  accent-insensitive, so the dropdown DOES carry `Ghazbán Ogre (5ED #298)`
  (+ `Ghazbán Ogress (5ED #299)`).
- **Killer:** `PrintMixin._normalize_card_name` folded case/whitespace
  only → `_option_name_matches` rejected EVERY accented option
  (`ghazbánogre != ghazbanogre`) → `_get_and_filter_prints` returned [].
- `_match_scryfall_to_cc_prints` pass 2 did `"ghazbán ogre" in "ghazban
  ogre (5ed #298)"` → False — the scryfall→CC name match failed across the
  accent boundary even with a populated CC pool.
- `ScryfallCache.get_card/get_prints` were exact-name SQL lookups; a
  sanitized name always missed the local cache → wasted API calls in
  pre-flight, validation, print resolution, and art metadata.
- The failure list did not exist — errors were only printed in the summary.

**Fix (5 files + new suite, commit d73bf36):**
- `automator_utils.py`: new `normalize_card_name()` — NFKD + drop-
  combining-marks + case/whitespace fold; undecomposable chars (ł) are
  KEPT so different names cannot compare equal.  `parse_card_file` now
  keeps the copy count (`'count'`, 1 when no number prefix).  New
  `write_missing_list(input, lines)` → `'<input>.missing'` (the existing
  repo convention: `decksold/*.dek.missing`, `NeoclassicalCube_01.txt.missing`).
- `mixins/print_mixin.py`: `_normalize_card_name` delegates to the helper.
- `automator.py`: `_match_scryfall_to_cc_prints` pass 2 compares both
  sides in `normalize_card_name` form (pass 1 set+CN unchanged).
- `scryfall_cache.py`: `_norm_name` + `_fetch_rows` — exact-name indexed
  lookup first (unchanged fast path), accent-folded fallback ONLY on a
  miss, via a SQLite `cc_norm()` Python function registered on the
  connection.  No schema change, no DB rebuild; the fallback honors the
  `set_code` scope (get_card) and returns ALL prints (get_prints,
  `limit_one=False`); clean `None`/[] on unknown cards preserved.
- `ccAutomator.py`: error lines keep the decklist's copy count
  (`3 Urza's Tower`, not `1 ...`); after the error summary a failed run
  writes `'<input>.missing'` (selenium + json modes) and points at it;
  clean runs write nothing.  Exit-code semantics unchanged (errors exit 1).

**Tests (new `test_accent_matching.py`, 15/15):** normalize (fold,
undecomposable kept, None-safe); `_option_name_matches` (accent both
directions, Ogress/DarkRituals boundaries, legacy semantics preserved);
`_match_scryfall_to_cc_prints` (pass-1 direct, pass-2 accent-crossing both
directions, Ogress rejected); cache fallback (sanitized get_card/get_prints,
set scope, boundary, clean miss, exact path unchanged); parse_card_file
counts; write_missing_list (location/format/re-parse/overwrite).
All five suites green: 15/15, 18/18, 8/8, 34/34, 8/8; py_compile clean.

**Live verification (real app http://mtgproxy:4242/ + production cache,
2026-11-18):**
- **Run A — `decks/missing.dek` (the 2 cards that used to error): EXIT 0,
  Success: 2 / Skipped: 0 / Error: 0** (1m12s). Both resolved via the LOCAL
  cache ("Resolved 6/1 local cache print(s)", "Using local Scryfall cache"
  for art) — zero Scryfall API calls; captured `ghazban-ogre_arn_49.png` +
  `ifh-biff-efreet_arn_50.png`; NO `.missing` file (clean run).
- **Run B — bogus deck (2× fake card + 1 real, `--skip-validation`): EXIT 1,
  Success: 1 / Error: 1**, and `bogus.txt.missing` was auto-written with
  exactly `2 Zqxqxqw Bogus Card` (copy count preserved; standard decklist,
  parses back cleanly and is re-runnable).

**Commits (branch user-agent-ts140, 2026-11-18):**
- **d73bf36** the fix + `test_accent_matching.py` (6 files, +447/−40).
- Notes commit: this one.

## Token search fix — `# Tokens` cards now resolve in Card Conjurer  [2026-11-20]
**Request:** ccAutomator intentionally skips tokens, but when a deck needs
them (e.g. `decks/teaching/rev2/t1_mono_black_graveyard_shift.dek` with a
`# Tokens` section) there should be a way to search them.
**Root cause:** the token plumbing (Scryfall `is:token` query, token-set
mapping, mana-cost clear, frame color — all present since ab25b18) was
gated behind `_get_and_filter_prints`, which typed `"<name> token"` into
the Card Conjurer search box. The app translates that into a Scryfall
`name=<name>_token` query — a partial name-contains match, and no card is
literally named "Serf token", so the search 404'd. `_get_and_filter_prints`
timed out all 3 retries, the CC print pool came back EMPTY, and the
cross-reference could never match — every `# Tokens` card was silently
skipped (they even land in the `.missing` file).
**Change (mixins/print_mixin.py, ~2 lines):** for token searches, type the
PLAIN NAME into the search box. `name=Serf` is a contains-match that finds
the token (verified live: the plain search returns the token print +
false-positives like "Venser, Fervent Forger" which contains "serf"), and
`_option_name_matches` narrows to exact names; `_match_scryfall_to_cc_prints`
then picks the token via Scryfall set/collector-number. The `is_token`
parameter still governs the token-only Scryfall query + set-filter bypass
in automator.py. Non-token searches are untouched.
**Verify (live, real app http://mtgproxy:4242/ + chromium + production
Scryfall cache, 2026-11-20):**
- Before: `_get_and_filter_prints('Serf', is_token=True)` → 3× timeout,
  0 prints (and 0 for 'Zombie'). After: Serf → 1 CC print (TEMA #5),
  Zombie → 89 exact 'Zombie' prints (tokens + normal; Scryfall's
  is:token query decides), Dark Ritual non-token path unchanged (58).
- End-to-end selenium run (`# Tokens` deck: 1 Dark Ritual, 2 Serf, 1
  Zombie): **Success 2 tokens + 1 spell, Error 0** (was Error 2 for the
  two tokens before the fix). Tokens captured full-res
  `serf_tema_5.png` / `zombie_tugl_91.png` with art, cleared mana cost,
  black frame from Scryfall colors, 0/1 P/T.
- Set symbol: token sets (t*) have no assets in Card Conjurer's built-in
  set (warning + counted, card still produced) — hexproof source covers
  them (verified 200 for tema/tugl); production `custom.conf` uses hexproof.
  Documented in README.
- `py_compile` clean.
Commit: bdfdccb (fix + README).

## Tokens in FullArtNew frame + first-use font tofu fix  [2026-11-20]
**Request:** token art crops don't match the deck frame's art window;
brainstorm options; user then ruled: always use the
--full-art-basic-land frame for tokens ("visually distinct is a bonus").
**Investigation (measured live from the app, not assumed):**
- Seventh art window = 1541x1246 (1.236, landscape) via card.artBounds;
  normal-card art_crop = 1.24-1.37 landscape; token art_crop =
  0.71-1.20 (mostly square/portrait) -> cover-fit crops tokens 25-43%.
- The --full-art-basic-land frame is app frame 'FullArtNew'
  (autoFullArtNewFrame -> makeM15NewFrameByLetter 'fullart', assets
  /img/frames/m15/new/fullart/{letter}.png). Its art window =
  1761x2278 (0.773, portrait) -> fits token art with 8-18% crop.
  Per-color base assets exist for w/u/b/r/g/m/a; colorless 'c' is 404
  -> colorless tokens keep the deck frame.
- Set-symbol source hexproof covers token sets (t*); cardconjurer built-in
  does not (warning already printed + counted; production conf uses hexproof).
**Change (commits bdfdccb pre-work on search; 55fe679 this feature):**
- `--token-frame` CLI flag (default FullArtNew, 'none' = deck frame),
  wired to selenium + combo phase-1 construction; automator.py applies
  it around the token branch (before set_frame_color so the color picker
  recolors the token frame; _restore_deck_frame() at the top of the next
  card's process_and_capture_card puts the deck frame back -- self-
  healing after a crash mid-token).
- Font tofu fix: first token in a fresh run rendered 'Ser|25A1'/'Toke|25A1'.
  Mechanism (creator-23.js): word-final f/h/m/n/k are replaced by PUA
  glyphs ue006-ue00a that exist only in the frame web font (belerenb);
  the text layer is pre-baked into a separate textCanvas by the app's
  debounced async drawText() (~500ms after frame/color rebuild) and
  drawCard() only blits it.  First bake can land while belerenb is still
  downloading -> ASCII falls back to system serif (OK) but PUA code
  points exist in no system font -> tofu boxes.  A plain drawCard()
  redraw does NOT fix it (verified byte-identical re-capture).
  _wait_frame_fonts_loaded(): polls document.fonts until every text-box
  face status == 'loaded' (12s in-page budget), then re-runs the app's
  own async drawText() to re-bake the layer with the real face, then
  settles the canvas.  Note: document.fonts.load() resolves when the
  request is ACCEPTED, not when bytes are in -- must poll status.
**Verify (live app + production cache + image-server upload mode):**
- Deterministic repro first (manual sequence w/ preceding full card):
  tofu, belerenb face 'loading' at PUA draw time, PUA+ASCII checks false.
- After fix, same sequence: 'Frame font state: loaded' + clean render.
- Full ccAutomator.py e2e (--token-frame FullArtNew, 1 Dark Ritual +
  2 Serf + 1 Zombie): Success 3/0/0, exit 0; first-token Serf clean
  (fetched from image server and eyeballed); post-token Dark Ritual in
  Seventh intact (frame restore + PUA 'k' ligature in 'Dark' render).
- py_compile clean.
Commits: 55fe679 (feature + font fix + README).

## --white-border crash on token frame (FullArtNew)  [2026-11-20]
**Request (user):** a run with `@custom.conf --overwrite --image-server
... token.txt` failed on the first token: "Error processing 'Serf':
Message: Stacktrace: ..." -- the white-border step.
**Root cause:** custom.conf enables `--white-border`.  `apply_white_border()`
(double-clicks the picker's `whiteThumb.png`) times out on FullArtNew
because that frame's picker has NO white/silver/gold border thumbnails
(only color / PT / land thumbs) -- so every token card on `--token-frame
FullArtNew` errored.  (A first attempt at the fix also passed
`timeout=` to `WebDriverWait.until()`, which is not a kwarg there --
that made ALL cards error, not just tokens; caught in isolation.)
**Change (mixins/canvas_mixin.py):** `apply_white_border()` now waits on
the thumbnail with a short (3s) `WebDriverWait` and treats its ABSENCE as
the expected state -> `_apply_white_border_injection()`.  The injection
prepends the app's own "White Border" frame entry (full-card
`/img/frames/white.png` masked to the outer boundary by
`seventh/regular/border.svg` -- identical to what land_generator's JSON
path builds) to `card.frames`, building the `.image` objects the way
`addFrame()` does.  KEY: `drawFrames()` silently skips any frame entry
without a pre-loaded `.image`, so a bare `unshift` + `drawCard()` is a
no-op (verified pixel-identical).  Idempotent; raises `UploadError` on a
load failure so the card is counted like the thumbnail path.  Frames that
still have the thumbnail (Seventh) keep the original UI path unchanged.
**Verify (live app + production cache + image-server upload mode):**
- Isolated: single Dark Ritual + `--white-border` on Seventh ->
  "White border applied." Success 1/0 (thumbnail path intact).
- Full run: 1 Dark Ritual + 2 Serf + 1 Zombie, `--frame Seventh
  --token-frame FullArtNew --white-border`: **Success 3 / Skipped 0 /
  Error 0**.  Serf log shows "Applying token frame" -> "White border
  applied (injected)" -> "Restoring deck frame 'Seventh'"; pixel check
  token border 0,0,0 -> 255,255,255; token text clean (no first-use font
  tofu).
- `py_compile` clean.
Commit: 7793e99.

## Tokens in the full-art land frame (seventhTextless)  [2026-11-20]
**Request (user):** tokens still rendered looking like the Seventh deck frame
("still rendering on the seventh frame, but with the art sized for the
FullArtNew"); user then pinned the target with an example render:
`ccAutomator/13-26/mountain_blb_276_13-26.png` -- "Example of the frame I
desire for tokens and is used by --full-art-basic-land".
**Root cause (measured, not guessed):**
- The committed --token-frame mapped to the app's M15 `FullArtNew` frame.
  Its creature base assets (m15/new/fullart/{letter}.png) are full-art
  CREATURE frames with a baked-in silver title plaque and translucent type/
  rules boxes over the art -- live pixel probes confirmed the token renders
  were faithful FullArtNew composites; the plaque reads as "Seventh" to the
  eye.  The mechanics worked; the frame family was wrong for the desired look.
- The --full-art-basic-land output actually uses version **seventhTextless**
  (verified from `land.cardconjurer` on the server: version 'seventhTextless',
  frames = [White Border, {Color} Frame seventhTextlessFrame{W..G}.png],
  artBounds 0.768x0.7772 portrait -- aspect 0.988, nearly square, minimal
  token-art crop).  packSeventhTextless.js defines the frame family; #autoFrame
  has NO seventhTextless entry, so set_frame() cannot select it.
**Change:**
- `mixins/canvas_mixin.py`: `apply_seventh_textless_frame(color_code)` --
  loads packSeventhTextless.js (frame-search path; picker repopulates),
  NEUTRALIZES the autoFrame dropdown ('false' -- every text edit schedules a
  debounced autoFrame() that rebuilds card.frames from the dropdown value,
  which still reads 'Seventh' and would clobber the textless stack mid-apply),
  invokes the pack's own #loadFrameVersion.onclick (version 'seventhTextless',
  resetCardIrregularities, autoFitArt to the portrait window, textless text
  layout), then swaps card.frames to the single full-card color asset
  (W/U/B/R/G/M/A/L -- colorless tokens work via the Artifact frame, unlike
  FullArtNew whose 'c' asset 404s).  set_frame() now recovers when the
  dropdown reads 'false' (skips only on genuine same-value match).
- `automator.py`: token branch -- 'seventhTextless' goes through the new
  method (color picked from Scryfall colors: single -> letter, multi -> 'M',
  none/artifact -> 'A'), blanks the set symbol afterwards (the textless
  layout puts setSymbolBounds in the P/T corner -- fetched symbols collided
  with '2/2'; the land path blanks it the same way), and skips
  set_frame_color (color thumbs don't apply to the pack path).  Dropdown
  frames (FullArtNew etc.) keep the old path.  `_restore_deck_frame` now
  reloads the deck frame's pack script and re-invokes its #loadFrameVersion
  handler after a textless token (the handler slot still holds
  packSeventhTextless's, and only a Load-Frame-Version restores the deck
  version's geometry + text boxes; set_frame alone rebuilds frames only).
- `mixins/symbol_mixin.py`: `clear_set_symbol()` (blank.png via the app's
  setSymbolEdited path).
- `automator_utils.py`: (1) parse_card_file accepts MTGO-style '<count>x Name'
  ('6x Serf' parsed as the literal name '6x Serf' before -- the user's
  .dek/.missing files use that notation, so the cards failed validation);
  (2) write_missing_list takes a parallel category list and interleaves
  '# Tokens'/'# Deck' headers so the file is actually re-runnable (a bare
  'Serf' re-ran as a deck card, its not:token query found nothing, and the
  fix-file reproduced the failure); ccAutomator passes categories at all
  three .missing write sites.
- ccAutomator.py default --token-frame seventhTextless; custom.conf updated;
  README rewritten.
**Verify (live app + production cache + image-server upload mode):**
- token.txt (2 Serf + 1 Zombie): both captured in seventhTextless -- textured
  per-color border, top-left title, art filling the card, clean 0/1 / 2/2
  (zombie corner inspected after set-symbol blanking: no collision).
- # Tokens + # Deck mixed run (Serf, Zombie, then Dark Ritual): Success 3/0/0;
  post-token Dark Ritual is an INTACT Seventh render (title/mana/type/parchment
  rules/set symbol all correct) -- deck restore + text-layout reload verified.
- The real .missing decklist (user's file, now with '# Tokens' header): the
  6x Serf + 1x Zombie from the failed teaching run rendered, Success 2/0/0.
- test_accent_matching.py: 15/15 PASS (write_missing_list plain-format
  regression caught and fixed during development).
- py_compile clean (automator, ccAutomator, automator_utils, canvas_mixin,
  symbol_mixin).
Commits: this entry (see git log for the fix commit).

## Type line on textless tokens (bottom-left, opposite P/T)  [2026-11-20]
**Request (user):** add the Type line ("Token Creature — Serf") at the
bottom-left, opposite the P/T box, on seventhTextless tokens.
**Change (mixins/canvas_mixin.py, apply_seventh_textless_frame):** when the
frame stack is swapped to the color asset, re-add a 'type' text box to
card.text at x:0.108, y:0.8981 (same row/height as the P/T box), width 0.64,
oneLine, goudymedieval + white + shadow (matches the title's on-border
styling).  Content comes from the app's savedTextContents['type'] -- the
deck frame's Type text (with its {left}/{kerning}/{fontsize} tags) is
preserved there when the pack's loadTextOptions replaced the layout -- and
drawTextBuffer() re-bakes the layer.  For the next card, the restore path's
packSeventh handler + import overwrite type text normally.
**Verify (live app + image-server upload mode):**
- Serf + Zombie re-rendered: 'Token Creature — Serf' / 'Token Creature —
  Zombie' on the bottom border, left-aligned, clear of the 0/1 / 2/2; no
  clipping at 23 characters.
- Mixed token+spell run (Serf, Zombie, Dark Ritual): Success 3/0/0; the
  post-token spell is intact Seventh (title/mana/type/rules/set symbol).
- py_compile clean.
Commit: see git log (type-line commit).
