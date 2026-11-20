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
  --type-left 40 --type-kerning 3 --pt-kerning 5 --pt-font-size 10 --pt-shadow 7 \
  --flavor-font -25 --pt-up 15 --rules-down 15 single.txt
```

With a config file and art upscaling:

```bash
python3 ccAutomator.py @my.conf single.txt
#   (see my.conf for the full annotated option set)
```

## Reminder text (teaching decks)

Scryfall's oracle text only carries reminder text when WotC printed it on
that particular card face, so the same keyword may be reminded on one print
and unreminded on another (Serra Angel has no Flying reminder; Sengir
Vampire does).

- `--inject-reminder-text` (default: off) normalizes this: every card
  carrying a listed keyword ability gets the canonical sentence from
  `reminder_map.json` -- printed variants are **replaced**, missing ones
  **added**.  Uniform wording across the deck, no double reminders.
- `reminder_map.json` (next to `ccAutomator.py`) is user-editable: keyword
  abilities today (flying, vigilance, haste, first strike, double strike,
  trample, deathtouch, lifelink, reach, hexproof, menace, ward, infect,
  defender, regenerate).
- Card-specific overrides: Add entries like `"trample:overrun"` in the map
  to use special reminder text for specific cards. When a card's name
  matches the suffix (case-insensitive), that reminder is used instead of
  the generic one. For example, Overrun uses: "Each of those creatures can
  deal excess combat damage to the player it's attacking."
- Card-type overrides: Add entries like `"flying:wall"` for cards with a
  specific subtype. When the card has that subtype (e.g., "Legendary
  Creature - Wall"), the type-specific reminder is used. For example, Wall
  of Air's Flying uses: "This creature can block creatures with flying."
- `--reminder-map PATH` points at an alternative map.
- The injected/replacement text uses the app's `{i}(...) {/i}` italic form,
  so it renders like printed reminders -- and is stripped by
  `--hide-reminder-text` if that is also set (that checkbox removes *all*
  tagged reminders at render).
- Detection/injection logic is pure and covered by
  `test_reminder_injection.py` (31 checks, run directly or under pytest).

## Tokens in decklists

Lines after a `# Tokens` header in the input decklist are searched as token
cards:

```
1 Dark Ritual

# Tokens
2 Serf
1 Zombie
```

Token cards are searched with an `is:token` Scryfall query, matched to the
token prints Card Conjurer offers, then rendered with the mana cost cleared
and the frame color taken from the token's color. Set include/exclude
filters are bypassed for tokens (token sets use their own `t`-prefixed
codes). Note: the `cardconjurer` set-symbol source has no assets for token
sets — use `--set-symbol-source hexproof` (which covers them) if you want
the set symbol on token cards.

## Token analysis

The `--tokens` flag in `deck_reminder_report.py` analyzes a decklist for
token requirements:

```bash
python3 deck_reminder_report.py --tokens decks/mydeck.dek
```

This scans each card in the decklist, looks up its Scryfall data, and lists
all tokens that need to be produced. The output shows:

```
Tokens needed:
  Bear:
    Grizzly Fate (x1)
  Beast:
    Fresh Meat (x1)
  Copy:
    Cadric, Soul Kindler (x1)
    Dark Depths (x1)
```

Tokens are identified from Scryfall's `all_parts` field for cards that have
`component: token`. Cards that produce tokens are typically spells, abilities,
or lands that create tokens as part of their effect.

## MTGO style decklists

Combine `--tokens --mtgo` to generate an MTGO-compatible .dek file with tokens
appended at the end. The format is `<count> <token-name>`, one per line, with
a `# Tokens needed (MTGO format):` header.

```bash
python3 deck_reminder_report.py --tokens --mtgo decks/mydeck.dek
```

This reads `mydeck.dek` and appends the token list to the same file:

```
# Existing deck content...

# Tokens needed (MTGO format):
2 Bear
1 Beast
1 Copy
```

### Directory support

Both the input decklist can be a directory (analyzes all `.dek` files in it)
or a single `.dek` file. When using `--mtgo`, only a single file is supported.

```bash
python3 deck_reminder_report.py --tokens decks/      # Analyze all .dek files
python3 deck_reminder_report.py --tokens --mtgo decks/mydeck.dek  # Generate tokens
```

### Output directory

Use `--output-dir` to write the generated .dek file to a different location:

```bash
python3 deck_reminder_report.py --tokens --mtgo --output-dir /path/to/output decks/mydeck.dek
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
