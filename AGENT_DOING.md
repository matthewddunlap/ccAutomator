# AGENT DOING — current work item

## T6 — H2: surface set-symbol fetch failures  [IN PROGRESS 2026-09-18]

Steps:
- [ ] mixins/symbol_mixin.py: after fetchSetSymbol() + sleep, verify the
      symbol <img> actually loaded (JS: find img with /setSymbol/i src,
      check complete && naturalWidth > 0; fallback: card.setSymbolSource
      non-empty). Confirm selector against live DOM.
- [ ] On failure: stderr warning + self.symbol_failures += 1 (init 0 in
      CardConjurerAutomator.__init__)
- [ ] ccAutomator.py final summary: "Symbol failures: N" line when N > 0
- [ ] py_compile touched files
- [ ] Move item to AGENT_DONE.md, update AGENT_TODO.md, commit

Notes / partial progress:
- (empty)
