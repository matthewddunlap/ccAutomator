# AGENT DOING — current work item

## T7 — H3: full-res capture in `render_project_file`  [DONE 2026-09-18 → AGENT_DONE.md]

## T8 — H4: Scryfall timeouts / 429 / duplicate fallback  [IN PROGRESS 2026-09-18]

Steps:
- [x] automator_utils.py: new `scryfall_search(query)` helper —
      `requests.get(..., timeout=(10, 60))`; on 429 → sleep `Retry-After`
      (default 10s, capped 60s) and retry once; transient network errors
      retried once then reported; returns the `data` list.
- [x] Replace the four inline `requests.get` blocks in
      `scryfall_query_with_fallback` with the helper.
- [x] Delete the old "Fallback 1" (stripped `not:covered`, which
      `build_scryfall_query` never adds → byte-identical duplicate of Try 1);
      renumber the surviving fallbacks (log messages now Step 1 / Step 2).
- [x] py_compile automator_utils.py
- [ ] Move item to AGENT_DONE.md, update AGENT_TODO.md, commit

Notes / partial progress:
- (empty)
