# AGENT DOING — current work item

## T3 — C3: `_prepare_art_asset` None-return crash  [IN PROGRESS 2026-09-18]

Steps:
- [ ] image_mixin.py:360 `return None, None` → `return (None, type_line, None, None)`
- [ ] image_mixin.py:424 `return None` → `return (None, type_line, None, None)`
- [ ] Fix signature annotation `-> tuple[str, str]` → 4-tuple (with Optional)
- [ ] Audit land_generator.py:160 + ccAutomator.py:1277 for None-art handling
      (must not write artSource: null)
- [ ] `python -m py_compile` on touched files
- [ ] Move item to AGENT_DONE.md, update AGENT_TODO.md, commit

Notes / partial progress:
- automator.py caller (648-657) already guards `if final_art_url:` →
  "Using default art" — verified safe.
