# AGENT DOING — current work item

## T1 — C5: surface upload failures  [IN PROGRESS 2026-09-18]

Steps:
- [ ] `class UploadError(RuntimeError)` in mixins/image_mixin.py
- [ ] `_upload_image`: raise UploadError from e in both except branches
- [ ] `_upload_art_asset`: same
- [ ] `_save_or_upload_image`: same
- [ ] automator.py `download_saved_cards` (1155): add `raise` after print
- [ ] automator.py `render_project_file` (1405): add `raise` after print
- [ ] `python -m py_compile` on touched files
- [ ] Move item to AGENT_DONE.md, update AGENT_TODO.md, commit

Notes / partial progress:
- (empty)
