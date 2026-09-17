# ccAutomator

Drives the live CardConjurer renderer (CardConjurer / Card Conjurer) via
Selenium to bulk-produce custom MTG cards: art, name auto-fit, type-line
auto-fit, P/T sizing, set symbols, and PNG/PDF export.

## Example runs

Single card (inline options):

```bash
python3 ccAutomator.py --prime-file prime.txt --url http://mtgproxy:4242/ \
  --frame Seventh --include-set 4ed --exclude-set 30a,sld,pblb --set-selection latest \
  --white-border --autofit-art --image-server http://mtgproxy:4242 \
  --upload-path /local_art/card_images/ccAutomator/ \
  --title-left 40 --title-kerning 4 --title-shadow 5 \
  --type-left 40 --type-kerning 3 --pt-kerning 5 --pt-font 10 --pt-shadow 7 \
  --flavor-font -25 --pt-up 15 --rules-down 15 single.txt
```

With a config file and art upscaling:

```bash
python3 ccAutomator.py @my.conf single.txt
#   (see my.conf for the full annotated option set)
```

## Auto-fit calibration

- Title, type, and P/T widths are estimated from per-glyph tables calibrated
  against the *live* renderer, not from the JSON box geometry:
  - `title_calibrate.py`  -> `title_glyphs.json`
  - `type_calibrate.py`   -> `type_glyphs.json`
  - `pt_calibrate.py`     -> `pt_calib.json`  (per-glyph P/T law + box width-capacity law)
- All three are measured with the same magenta-ink + band technique
  (`glyph_measure.py` for the name/type; `pt_calibrate.py` is standalone for P/T).
  Each glyph is measured across the fontsize range actually used and fit to
  `base + slope*fontsize`; kerning is a uniform per-gap coefficient. A glyph
  whose fit residual exceeds 1.5px is flagged non-linear (would need more
  sample points).
- Title, type, and P/T autofit are all PURE MATH at card time (read the value,
  compute the size, apply once) — no per-card render. Re-run the calibrators
  after any frame/font change to refresh the tables.

## Design notes / open recommendations

**Set-symbol position table (NOT added — on purpose).** The type autofit needs
the card's set-symbol left edge. It already gets this per-card from
`setSymbolX` (read live via `get_symbol_geometry()`, or from the project file),
where `left_edge = setSymbolX * canvas_width`. This was verified live: every
symbol in the current project (ddn/ons/usg/mir/uds/vow) matched `x*CW` within
~7px, while the old "centered" model (`x*CW - zoom*CW/2`) was 80-130px low.

A `set_glyphs.json` keyed by (set, rarity) -> left-edge would only help the one
case where geometry is missing (fallback to the `_SET_SYMBOL_LEFT=818`
constant). Recommendation: **do not add it now.** Per-card `setSymbolX` already
carries the position with the card, and a per-frame symbol table is more
surface to keep in sync (frame-specific, must be re-measured per frame). Revisit
only if real cards appear whose geometry is genuinely absent and mis-sized by
the 818 floor.
