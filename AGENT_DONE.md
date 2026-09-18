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
Commit: (this commit).
