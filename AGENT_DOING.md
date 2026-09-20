# AGENT DOING — current work item

No item in flight.

## All ordered fixes T1-T9 complete AND verified  [2026-09-19]

- T1-T8: fixed 2026-09-18 (see `AGENT_DONE.md`), **live + offline
  verification completed 2026-09-19** — all six pending verifications PASS.
  Full results: `AGENT_DONE.md` → "Live verification of T1-T8".
- T9 (P/T box stateful set/restore, the Karn left-shift bug) was completed
  and live-verified 2026-09-19 (earlier) — see `AGENT_DONE.md`.

## Next up (per 2026-09-19 planning)

Deferred list in `AGENT_TODO.md` ("Later review") is unchanged; user's focus
remains `selenium` mode. Highest-value follow-ups identified 2026-09-19:

1. **H8** (live-path text-mod tag duplication on re-run — selenium path,
   silent wrong output) — fold in when touching the text-mod hot path.
2. **Startup decklist validation** (user-requested feature, H6-adjacent):
   validate names against the local Scryfall cache before rendering; skip
   `#` lines (user ruling: comment-out is a feature).
3. **Perf: fixed sleeps → state-based waits** (~53 `time.sleep` in hot path,
   `render_delay` default 1.5s) — biggest wall-clock lever.
4. **H9 residual**: scryfall_cache false-success (`except IOError` swallows
   request errors → "finished by another instance", returns True) +
   hardcoded `/data/ccAutomator/` paths.
5. **H7**: delete dead no-op `apply_set_filters`.
