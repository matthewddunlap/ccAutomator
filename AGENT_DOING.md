# AGENT DOING — current work item

## T7 — H3: full-res capture in `render_project_file`  [IN PROGRESS 2026-09-18]

Steps:
- [ ] automator.py render_project_file (~1376-1403): replace the inline
      preview-canvas capture+save block with `self.capture_card(filename)`
      (automator.py:947-1013) — cardCanvas-preferred (3 retries), preview
      fallback, blank check, upload/local-save. Keep the stabilize sleep
      before it and the metadata/filename generation (1385-1393).
- [ ] Remove now-unused imports if any become dead (base64? check usage).
- [ ] py_compile automator.py
- [ ] Move item to AGENT_DONE.md, update AGENT_TODO.md, commit

Notes / partial progress:
- (empty)
