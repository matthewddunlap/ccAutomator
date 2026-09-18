# AGENT DOING — current work item

## All ordered fixes T1-T8 complete  [2026-09-18]

Commits (branch `user-agent`):
- T1 `76519cd` — C5: surface upload failures
- T2 `a867ec1` — H1: exit non-zero on failure
- T3 `27f7c68` — C3: `_prepare_art_asset` always returns a 4-tuple
- T4 `88309f9` — C4: compare local file mtime in UTC
- T5 `69389ce` — C8: requirements filename + missing selenium
- T6 `f0c350e` — H2: surface set-symbol fetch failures
- T7 `53b8141` — H3: full-res cardCanvas capture in render_project_file
- T8 (this commit) — H4: Scryfall timeouts, 429 retry, drop duplicate fallback

### Pending live verification (needs app/server)
- [ ] T1+T2: upload-failure run — failed card counts as error, batch exits 1
- [ ] T2: bogus-card run → `echo $?` = 1
- [ ] T4: `--overwrite-older-than` end-to-end
- [ ] T7: cc-file mode on `long.cardconjurer` → output PNG is 2010×2814
- [ ] T6: card from a set lacking a symbol asset → stderr warning +
      "Symbol failures: N" summary line, card still produced
- [ ] T8: Scryfall 429 behavior under rate limit
