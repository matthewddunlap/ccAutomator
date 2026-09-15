import math
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple
import requests
from PIL import Image
import io
import time
import sys

# Optional dependency for SVG parsing
try:
    from lxml import etree
    HAS_LXML = True
except ImportError:
    HAS_LXML = False
    etree = None

# Basic Land Names
BASIC_LAND_NAMES = {
    'Island', 'Forest', 'Mountain', 'Plains', 'Swamp',
    'Snow-Covered Island', 'Snow-Covered Forest', 'Snow-Covered Mountain', 
    'Snow-Covered Plains', 'Snow-Covered Swamp'
}

# Default Configuration
DEFAULT_UPSCALER_MODEL = 'RealESRGAN_x2plus'

# Scryfall API requires a custom User-Agent (rejects the default Python-requests one)
SCRYFALL_HEADERS = {'User-Agent': 'ccAutomator/1.0 (custom card frame automation tool)'}

def parse_time_string(time_str: str) -> Optional[datetime]:
    """Parses a timestamp string (yyyy-mm-dd-hh-mm-ss) or relative time (e.g., 5m, 2h) into a timezone-aware datetime object (UTC)."""
    if not time_str:
        return None
    # Try parsing as a fixed timestamp first (assuming local time, then converting to UTC)
    try:
        local_dt = datetime.strptime(time_str, '%Y-%m-%d-%H-%M-%S')
        # Assume the user provides the timestamp in their local time, convert it to UTC for comparison
        utc_dt = local_dt.astimezone().replace(microsecond=0).astimezone(timezone.utc)
        return utc_dt
    except ValueError:
        pass

    # Try parsing as relative time
    match = re.match(r'(\d+)([mh])$', time_str.lower())
    if match:
        value, unit = int(match.group(1)), match.group(2)
        # Relative time is always calculated from now
        now_utc = datetime.now(timezone.utc)
        if unit == 'm':
            delta = timedelta(minutes=value)
        elif unit == 'h':
            delta = timedelta(hours=value)
        else: # Should not happen with the regex
            return None
        
        result_dt = now_utc - delta
        return result_dt
    
    print(f"Error: Invalid time format for '{time_str}'. Use 'yyyy-mm-dd-hh-mm-ss' or a relative time like '5m' or '2h'.")
    return None

def check_server_file_details(url: str) -> tuple[bool, Optional[datetime]]:
    """Check if a file exists at a URL and return its last-modified time as a timezone-aware UTC datetime."""
    if not url:
        return False, None
    try:
        r = requests.head(url, timeout=15, allow_redirects=True)
        if r.status_code == 200:
            last_modified_str = r.headers.get('Last-Modified')
            if last_modified_str:
                try:
                    # HTTP-date format is RFC 1123, e.g., 'Wed, 21 Oct 2015 07:28:00 GMT'
                    dt_naive = datetime.strptime(last_modified_str.replace(' GMT', ''), '%a, %d %b %Y %H:%M:%S')
                    dt_aware_utc = dt_naive.replace(tzinfo=timezone.utc)
                    return True, dt_aware_utc
                except ValueError:
                    return True, None # File exists, but can't parse date
            return True, None # File exists but no time info
        if r.status_code == 404:
            return False, None
        print(f"Warning: Received status {r.status_code} when checking {url}. Assuming it does not exist.")
        return False, None
    except requests.exceptions.RequestException as e:
        print(f"Warning: Network error while checking {url}: {e}. Assuming it does not exist.")
        return False, None

def generate_safe_filename(value: str) -> str:
    if not isinstance(value, str): value = str(value)
    value = value.replace("'", "")
    value = value.replace(",", "")
    value = unicodedata.normalize('NFKD', value).encode('ascii', 'ignore').decode('ascii')
    value = re.sub(r'[\s/:<>:"\\|?*&]+', '-', value)
    value = re.sub(r'-+', '-', value)
    value = value.strip('-')
    return value.lower()

def get_image_mime_type_and_extension(image_bytes: bytes) -> tuple[Optional[str], Optional[str]]:
    try:
        fmt = None
        try:
            img = Image.open(io.BytesIO(image_bytes))
            fmt = img.format
            img.close()
        except Exception:
            pass
        if fmt == "JPEG": return "image/jpeg", ".jpg"
        if fmt == "PNG": return "image/png", ".png"
        if fmt == "GIF": return "image/gif", ".gif"
        if image_bytes.startswith(b'\xff\xd8\xff'): return "image/jpeg", ".jpg"
        if image_bytes.startswith(b'\x89PNG\r\n\x1a\n'): return "image/png", ".png"
        if image_bytes.startswith(b'GIF87a') or image_bytes.startswith(b'GIF89a'): return "image/gif", ".gif"
        if image_bytes.startswith(b'RIFF') and len(image_bytes) > 12 and image_bytes[8:12] == b'WEBP': return "image/webp", ".webp"
        return "application/octet-stream", ""

    except Exception as e:
        print(f"   Error determining image type: {e}")
        return "application/octet-stream", ""

def parse_set_list(sets_arg) -> set:
    """
    Parses a set list argument which can be a string (comma-separated), 
    a list of strings, or None. Returns a set of lowercase set codes.
    """
    if not sets_arg:
        return set()
    
    result = set()
    if isinstance(sets_arg, str):
        result.update(s.strip().lower() for s in sets_arg.split(',') if s.strip())
    elif isinstance(sets_arg, (list, tuple, set)):
        for item in sets_arg:
            if isinstance(item, str):
                result.update(s.strip().lower() for s in item.split(',') if s.strip())
    return result

# ==============================================================================
# Deck List Parsing Functions
# ==============================================================================

BASIC_LANDS = ['Plains', 'Island', 'Swamp', 'Mountain', 'Forest', 'Wastes']

def parse_card_file(filepath):
    """
    Parses the input file to extract card names and categories (e.g., from # Headers).
    Returns a list of dictionaries: [{'name': 'Card Name', 'category': 'CategoryName'}, ...]
    """
    cards = []
    current_category = 'deck' # Default category
    
    try:
        with open(filepath, 'r') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                
                # Check for headers (lines starting with #)
                if line.startswith('#'):
                    # It's a header/category change, not just a comment
                    # Strip the # and whitespace to get category name
                    # e.g. "# Tokens" -> "tokens"
                    current_category = line.lstrip('#').strip().lower()
                    continue

                # Use regex to ignore leading numbers and capture the rest of the line.
                match = re.match(r'^\d+\s+(.*)', line)
                if match:
                    full_name = match.group(1).strip()
                else:
                    # Assume the whole line is the card name if no number prefix
                    full_name = line
                
                set_code = None
                if '|' in full_name:
                    parts = full_name.split('|', 1)
                    card_name = parts[0].strip()
                    set_code = parts[1].strip()
                else:
                    card_name = full_name
                
                cards.append({'name': card_name, 'category': current_category, 'set': set_code})
                    
    except FileNotFoundError:
        import sys
        print(f"Error: Input file not found at '{filepath}'", file=sys.stderr)
        sys.exit(1)
    return cards


def split_basic_lands(cards):
    """
    Split a list of cards into basic lands and non-basic cards.
    
    Args:
        cards: List of card dictionaries with 'name' and 'category' keys
    
    Returns:
        Tuple of (non_basic_cards, basic_land_types)
        - non_basic_cards: List of non-basic card dictionaries
        - basic_land_types: Set of unique basic land type names
    """
    non_basic = []
    basic_lands = set()
    
    for card in cards:
        card_name = card['name'] if isinstance(card, dict) else card
        if card_name in BASIC_LANDS:
            basic_lands.add(card_name)
        else:
            non_basic.append(card)
    
    return non_basic, basic_lands

# ==============================================================================
# Set Filtering Functions
# ==============================================================================

def apply_set_filters(cards, section, spells_include_set=None, spells_exclude_set=None,
                     basic_land_include_set=None, basic_land_exclude_set=None):
    """
    Apply set inclusion/exclusion filters based on card section.
    
    Args:
        cards: List of card dictionaries
        section: Section name ('deck', 'land', 'token', etc.)
        spells_include_set: Whitelist of sets for spells
        spells_exclude_set: Blacklist of sets for spells
        basic_land_include_set: Whitelist of sets for basic lands
        basic_land_exclude_set: Blacklist of sets for basic lands
    
    Returns:
        Filtered list of cards (note: filtering is informational; 
        actual Scryfall filtering happens in query building)
    """
    # This function is a placeholder for now - actual filtering happens
    # in build_scryfall_query() which adds set filters to the query string
    # We return all cards here since filtering is done via Scryfall API
    return cards

# ==============================================================================
# Scryfall Query Building
# ==============================================================================

def build_scryfall_query(card_name, section='deck', set_code=None, collector_number=None,
                        scryfall_filter=None, spells_include_set=None, spells_exclude_set=None,
                        basic_land_include_set=None, basic_land_exclude_set=None):
    """
    Build Scryfall query string based on card name and filters.
    
    Filtering is based on card name:
    - Basic lands (Island, Forest, etc.) use basic_land filters
    - Everything else (including non-basic lands) uses spell filters
    - Token section adds 't:token' modifier
    
    Args:
        card_name: Name of the card
        section: Section name ('deck', 'land', 'token', etc.) - only used for token detection
        set_code: Optional set code
        collector_number: Optional collector number
        scryfall_filter: Additional Scryfall query filters
        spells_include_set: Whitelist of sets for spells (non-basic lands + spells)
        spells_exclude_set: Blacklist of sets for spells (non-basic lands + spells)
        basic_land_include_set: Whitelist of sets for basic lands
        basic_land_exclude_set: Blacklist of sets for basic lands
    
    Returns:
        Scryfall query string
    """
    # Start with exact card name match
    query = f'!"{card_name}"'
    
    # Add set code if provided
    if set_code:
        query += f" set:{set_code}"
    
    # Add collector number if provided
    if collector_number:
        query += f" cn:{collector_number}"
    
    # Add token modifier if in token section
    section_lower = section.lower()
    if section_lower == 'token' or section_lower == 'tokens':
        query += " t:token"
    
    # Determine if this is a basic land based on card name
    is_basic_land = card_name in BASIC_LAND_NAMES
    
    # Add set filters based on card name (basic land vs spell)
    if is_basic_land:
        # Basic land filters
        if basic_land_include_set:
            include_sets = parse_set_list(basic_land_include_set)
            if include_sets:
                set_query = " OR ".join(f"set:{s}" for s in include_sets)
                query += f" ({set_query})"
        
        if basic_land_exclude_set:
            exclude_sets = parse_set_list(basic_land_exclude_set)
            for s in exclude_sets:
                query += f" -set:{s}"
    else:
        # Spell filters (applies to everything that's not a basic land)
        if spells_include_set:
            include_sets = parse_set_list(spells_include_set)
            if include_sets:
                set_query = " OR ".join(f"set:{s}" for s in include_sets)
                query += f" ({set_query})"
        
        if spells_exclude_set:
            exclude_sets = parse_set_list(spells_exclude_set)
            for s in exclude_sets:
                query += f" -set:{s}"
    
    # Add additional Scryfall filters
    if scryfall_filter:
        query += f" {scryfall_filter}"
    
    return query

def scryfall_query_with_fallback(card_name, section='deck', set_code=None, collector_number=None,
                                 scryfall_filter=None, spells_include_set=None, spells_exclude_set=None,
                                 basic_land_include_set=None, basic_land_exclude_set=None):
    """
    Query Scryfall with multi-step fallback logic.
    Prioritizes local cache for simple name and set lookups to prevent rate-limiting.
    """
    import sys
    from scryfall_cache import ScryfallCache
    
    # 1. Try Local Cache first
    # Now supports set_code lookups!
    if not collector_number and not scryfall_filter:
        cache = ScryfallCache()
        local_card = cache.get_card(card_name, set_code=set_code)
        if local_card:
            # print(f"   Scryfall lookup: '{card_name}'{' ('+set_code+')' if set_code else ''} found in local cache.")
            return local_card

    # Determine which filters to use based on card name
    is_basic_land = card_name in BASIC_LAND_NAMES

    current_include_set = basic_land_include_set if is_basic_land else spells_include_set
    current_exclude_set = basic_land_exclude_set if is_basic_land else spells_exclude_set
    
    data = None
    
    # Try 1: Full query with all filters
    query = build_scryfall_query(
        card_name=card_name,
        section=section,
        set_code=set_code,
        collector_number=collector_number,
        scryfall_filter=scryfall_filter,
        spells_include_set=spells_include_set,
        spells_exclude_set=spells_exclude_set,
        basic_land_include_set=basic_land_include_set,
        basic_land_exclude_set=basic_land_exclude_set
    )
    
    print(f"   Scryfall query (with filters): {query}")
    try:
        resp = requests.get("https://api.scryfall.com/cards/search", params={'q': query}, headers=SCRYFALL_HEADERS)
        if resp.status_code == 200:
            results = resp.json().get('data', [])
            if results:
                return results[0]
    except Exception as e:
        print(f"   Warning: Query failed: {e}", file=sys.stderr)
    
    # Fallback 1: Remove 'not:covered', but KEEP all set selection criteria (including set_code/includes/excludes)
    if section.lower() not in ['token', 'tokens']:
        print(f"   Warning: Initial query found no matches. Step 1: Stripping 'not:covered' but keeping all set filters...", file=sys.stderr)
        fallback_1_query = build_scryfall_query(
            card_name=card_name,
            section=section,
            set_code=set_code,
            collector_number=collector_number,
            scryfall_filter=scryfall_filter,
            spells_include_set=spells_include_set,
            spells_exclude_set=spells_exclude_set,
            basic_land_include_set=basic_land_include_set,
            basic_land_exclude_set=basic_land_exclude_set
        )
        if "not:covered" in fallback_1_query:
            fallback_1_query = fallback_1_query.replace("not:covered", "").replace("  ", " ").strip()
        
        print(f"   Scryfall fallback query (set filters kept, no not:covered): {fallback_1_query}")
        try:
            resp = requests.get("https://api.scryfall.com/cards/search", params={'q': fallback_1_query}, headers=SCRYFALL_HEADERS)
            if resp.status_code == 200:
                results = resp.json().get('data', [])
                if results:
                    return results[0]
        except Exception as e:
            print(f"   Warning: Fallback query 1 failed: {e}", file=sys.stderr)
    
    # Fallback 2: Strip ALL set filters (including set_code and collector_number), KEEP paper/layout
    print(f"   Warning: Still no matches. Step 2: Stripping ALL set criteria but keeping paper/layout constraints...", file=sys.stderr)
    fallback_2_query = f'!"{card_name}" unique:art not:token -layout:art-series game:paper'
    if section.lower() in ['token', 'tokens']:
        fallback_2_query = f'!"{card_name}" unique:art is:token'
    
    print(f"   Scryfall fallback query (sets stripped): {fallback_2_query}")
    try:
        resp = requests.get("https://api.scryfall.com/cards/search", params={'q': fallback_2_query}, headers=SCRYFALL_HEADERS)
        if resp.status_code == 200:
            results = resp.json().get('data', [])
            if results:
                return results[0]
    except Exception as e:
        print(f"   Warning: Fallback query 2 failed: {e}", file=sys.stderr)

    # Fallback 3: Broadest search, additionally strip game:paper and -layout:art-series
    print(f"   Warning: Still no matches. Step 3: Stripping paper/layout filters for broadest search.", file=sys.stderr)
    simple_query = f'!"{card_name}" unique:art not:token'
    if section.lower() in ['token', 'tokens']:
        simple_query = f'!"{card_name}" unique:art is:token'
    
    print(f"   Scryfall fallback query (broadest): {simple_query}")
    try:
        resp = requests.get("https://api.scryfall.com/cards/search", params={'q': simple_query}, headers=SCRYFALL_HEADERS)
        if resp.status_code == 200:
            results = resp.json().get('data', [])
            if results:
                return results[0]
    except Exception as e:
        print(f"   Warning: Final fallback query failed: {e}", file=sys.stderr)
    
    return None

# ==============================================================================
# Title Auto-Fit (width model measured from the LIVE renderer)
# ==============================================================================
#
# The CardConjurer name bar is a fixed band: the name sits left-aligned and the
# mana cost is right-aligned in the same row.  The name therefore has a budget
# that shrinks as the cost gets longer.  We do NOT derive this from the JSON
# box geometry -- the real pixel relationship is measured from the renderer
# itself (see title_calibrate.py) and encoded below as per-character constants.
#
# CardConjurer tag semantics (app "Text Codes" reference):
#   * `{fontsize#}`  -- RELATIVE size adjustment: the value is in canvas px.
#   * `{kerning#}`   -- ABSOLUTE letter-spacing applied between glyphs.
#   * `{left#}`      -- shift text N px left (frees N px on the right).
#
# Measured ground truth (canvas px) for 'Rofellos, Llanowar Emissary' (27 chars),
# rendered with NO {left} tag (origin 88px):
#   name width = 6.20 * {fontsize}  +  13.0 * {kerning}  +  660
#   -> per char:  base 24.444, +0.230 per fontsize unit, +0.4815 per kerning unit
#   (the renderer caps the name at the title box for very large settings, so these
#    hold up to that cap, which is well above any sensible autofit range)
#   mana cost right edge fixed at 931, one symbol ~ 52.4 px, name origin ~ 88 px.
# Re-run title_calibrate.py after any frame/font change to refresh the numbers.

_CHAR_W_BASE = 24.444    # px per char at default (fontsize offset 0, kerning 0)
_CHAR_W_FONT = 0.230     # px per char gained per +1 {fontsize} unit
_CHAR_W_KERN = 0.4815    # px per char gained per +1 {kerning} unit

_BAR_RIGHT_PX  = 931     # right edge of the rightmost mana symbol (measured)
_SYMBOL_PX     = 52.4    # horizontal room consumed by one mana symbol
_NAME_ORIGIN   = 88      # leftmost px of the name at {left}=0 (measured)
_LEFT_GAIN     = 0.5     # {leftN} in tag units shifts the name N*0.5 px left (measured: left40 -> 20px)

# Target clearance (canvas px) we require between the name's last letter and
# the leftmost mana symbol.  26 px reads as "touching" to the eye on a ~863 px
# bar; 45 px (~half a mana symbol) reads as clearly separated.  Raise to shrink
# more aggressively, lower to allow the name to sit closer to the cost.
_CLEARANCE_PX  = 45

_KERNING_MIN = 0         # floor for the {kerning} value
_FONT_FLOOR  = -20       # floor for the {fontsize} offset


def count_mana_symbols(mana_cost):
    """Count rendered mana symbols in a Scryfall mana_cost string.

    Handles {1}-{20} generics, single/hybrid/phyrexian colors, X/Y/Z, {T},
    snow {s}, energy {e}, etc.  Each `{...}` group is one rendered symbol.
    """
    if not mana_cost:
        return 0
    return len(re.findall(r'\{[^}]+\}', mana_cost))


def estimate_name_width(name, font_offset, kerning):
    """Estimated rendered width of `name` (canvas px) at the given tags.

    Calibrated linear law: width = n * (base + font_off*wf + kern*wk).
    """
    if not name:
        return 0.0
    n = len(name)
    return n * (_CHAR_W_BASE + _CHAR_W_FONT * (font_offset or 0) + _CHAR_W_KERN * (kerning or 0))


def _title_budget(n_syms, title_left):
    """Name width budget (canvas px) for a cost of n_syms symbols.

    budget = cost_left - name_origin - clearance, where the {leftN} tag moves
    the name origin left by N*_LEFT_GAIN px (N is in the card's 2010px space,
    measured canvas is half that).  A target clearance keeps the name visually
    clear of the leftmost mana symbol.
    """
    cost_left = _BAR_RIGHT_PX - n_syms * _SYMBOL_PX
    origin = _NAME_ORIGIN - (title_left or 0) * _LEFT_GAIN
    return cost_left - origin - _CLEARANCE_PX


def autofit_title(name, mana_cost, kerning=None, font_size=None, title_left=0):
    """
    Determine a title `(kerning, font_size)` pair that fits the name bar.

    Args:
        name:        raw card name (tags stripped).
        mana_cost:   Scryfall `mana_cost` (e.g. '{X}{X}{2}{W}') or None.
        kerning:     starting kerning (absolute px) or None.
        font_size:   starting {fontsize} offset (relative px) or None.
        title_left:  value of `{left#}` tag (positive = room gained).

    Returns:
        (kerning, font_size):  may equal the inputs.  Kerning never below
        _KERNING_MIN and font offset never below _FONT_FLOOR.  If the name
        already fits, the inputs are returned unchanged.
    """
    k = kerning if kerning is not None else 0
    fs = font_size if font_size is not None else 0
    left = title_left if title_left else 0

    n_syms = count_mana_symbols(mana_cost)
    budget = _title_budget(n_syms, left)

    name_w = estimate_name_width(name, fs, k)
    if name_w <= budget:
        return k, fs  # no change needed

    # The name is too wide.  Reduce kerning first (letter-spacing is the most
    # cosmetic thing to give back), but only as far as needed -- and never above
    # the user's starting value.  Only after kerning hits its floor do we cut the
    # font size.  Both results are bounded so we never END up larger than the
    # user's input.
    n = max(1, len(name))

    def fits(font_off, kern):
        return estimate_name_width(name, font_off, kern) <= budget

    # Largest kerning (clamped to <= the user's value and >= floor) that fits
    # at the current font size.
    if n > 1:
        per_kern = n * _CHAR_W_KERN
        ideal_k = (budget - n * (_CHAR_W_BASE + fs * _CHAR_W_FONT)) / per_kern
        k = max(_KERNING_MIN, min(k, int(ideal_k + 1e-9)))
        k = max(k, _KERNING_MIN)

    # If it still overflows at that kerning, drop the font size to exactly fit.
    if not fits(fs, k):
        target_per_char = (budget - n * _CHAR_W_KERN * k) / n
        fs = (target_per_char - _CHAR_W_BASE) / _CHAR_W_FONT
        fs = max(_FONT_FLOOR, int(round(fs)))

    print(f"   [Auto-Fit-Title] '{name}' ({n_syms} cost, left={left}) "
          f"-> kerning {kerning}->{k}, fontsize {font_size}->{fs} "
          f"(budget {budget:.0f}px, name_w {name_w:.0f}px)")
    return k, fs


# ==============================================================================
# Type-Line Auto-Fit (width model measured from the LIVE renderer)
# ==============================================================================
#
# The type line sits in its own fixed row, left-aligned.  On the RIGHT end of
# the same row lives the set symbol, so a very long type line ("Legendary
# Creature - Dragon, Wizard, Cleric") will grow rightward and run INTO the
# symbol / past the card edge.  The type therefore has a width budget bounded by
# the set symbol's left edge (or, when there is no symbol, the field's right cap).
#
# Like autofit_title(), the real pixel relationship is measured from the live
# renderer (see type_calibrate.py) and encoded below as per-character constants.
# For the sample "Dragon Wizard" (13 chars) least-squares fit on the Seventh
# frame (residuals within ~2 px):
#   width = 3.50 * {fontsize} + 6.15 * {kerning} + 299.7
#   -> per char: base 23.054, +0.269 per fontsize unit, +0.473 per kerning unit
#   type origin ~ 108 px (left edge at {left}=0), row right cap ~ 905 px, and
#   the set symbol begins near there (measured left edge ~ 904 px), so the symbol
#   effectively defines the row's right boundary.  We reserve room for it.
# Re-run type_calibrate.py after any frame/font change to refresh the numbers.

# Row right boundary, measured on the Seventh frame (canvas 1005px wide):
#   * the type text field itself extends to ~897px (field x=0.1074, w=0.7852),
#   * the very-long-type cap sits at ~909px,
#   * the set symbol is right-aligned starting ~890-904px.
# So when a set symbol is present it is the effective right wall (we stop a hair
# short of it), and without one the field cap (~905px) bounds the type.
_TYPE_ORIGIN = 108      # leftmost px of the type text at {left}=0 (field x=0.1074 -> 107px)
_TYPE_LEFT_GAIN = 0.5   # {leftN} shifts the type N*0.5 px left (measured: left40 -> ~20px)
_TYPE_ROW_RIGHT = 905   # right cap when NO set symbol occupies the row (measured very-long-type)
_SET_SYMBOL_LEFT = 711  # tightest symbol-left edge observed (ons set, zoom=0.241);
                        #   use as a floor (conservative) so the type never runs under
                        #   a large symbol; cards with smaller symbols will be
                        #   over-shrunk slightly but will never overrun
_TYPE_CLEARANCE = 45    # required gap between the type's last letter and the boundary
                        #   (45 px reads as clearly separated; matches title-line's gap)


#   (canvas px at fontsize 0, kerning 0), solved by least-squares against MEASURED
#   rendered widths of real MTG type lines on the Seventh frame.  A constant
#   per-char cannot fit both wide-letter lines ("Legendary Creature -- Human
#   Druid") and narrow-letter ("-- Phyrexian Dreadnought"); a per-category model
#   can.  Cross-check error is within +-7 px on every line used for the fit.
_TYPE_W_UL = 26.5        # uppercase
_TYPE_W_LL = 21.5        # lowercase
_TYPE_W_SPACE = 11.5     # space
_TYPE_W_DASH = 16.0      # em-dash / hyphen
_TYPE_W_COMMA = 8.5      # comma
_TYPE_W_OTHER = 22.0     # digits / other
# Per-char font-size / kerning scale coefficients (px per char per tag unit).
# These scale all glyphs together, so a constant is fine -- the per-category
# base above already handles the letter-shape differences.
_TYPE_W_FONT = 0.5       # px per char gained per +1 {fontsize} unit
_TYPE_W_KERN = 0.625     # px per char gained per +1 {kerning} unit

def _estimate_type_width(text, font_offset=None, kerning=None):
    """Estimated rendered width of `text` (canvas px) at the given tags.

    Uses a per-glyph-category width table (upper/lower/space/em-dash/comma/other)
    instead of a single per-char constant, because MTG type lines mix wide
    (uppercase) and narrow (lowercase) letters -- e.g. "Phyrexian Dreadnought"
    is mostly narrow letters while "Legendary Creature -- Human Druid" has more
    wide ones.  A constant cannot fit both; a per-category model can.

    font_offset / kerning are folded in as a small per-char adjustment on top
    of the measured base (they mostly scale all glyphs together).
    """
    if not text:
        return 0.0
    tot = 0.0
    n = 0
    for ch in text:
        n += 1
        if ch.isupper():
            tot += _TYPE_W_UL
        elif ch.islower():
            tot += _TYPE_W_LL
        elif ch == "\u2014" or ch == "-":
            tot += _TYPE_W_DASH
        elif ch == " ":
            tot += _TYPE_W_SPACE
        elif ch == ",":
            tot += _TYPE_W_COMMA
        else:
            tot += _TYPE_W_OTHER
    if n:
        tot += n * (_TYPE_W_FONT * (font_offset or 0) + _TYPE_W_KERN * (kerning or 0))
    return tot


def estimate_set_symbol_left(set_symbol_x=None, set_symbol_zoom=None, canvas_w=1005):
    """Estimate the set-symbol's left edge in canvas pixels from the card's own data.

    The symbol is right-aligned in its box (x = set_symbol_x, width = set_symbol_zoom).
    Its left edge = set_symbol_x*canvas_w − (set_symbol_zoom*canvas_w)/2.

    Returns None if no set-symbol info is available (caller should fall back to
    the _SET_SYMBOL_LEFT constant).
    """
    if set_symbol_x is None or set_symbol_zoom is None:
        return None
    return int(set_symbol_x * canvas_w - (set_symbol_zoom * canvas_w) / 2)


def _type_budget(type_left, has_set_symbol, set_symbol_left=None):
    """Type width budget (canvas px) bounded by the set symbol / field cap.

    budget = boundary - origin - clearance, where {leftN} moves the type origin
    left by N*_TYPE_LEFT_GAIN px.  boundary is the set-symbol left edge when a
    symbol occupies the right of the row, otherwise the field's right cap.
    """
    boundary = _SET_SYMBOL_LEFT if has_set_symbol else _TYPE_ROW_RIGHT
    origin = _TYPE_ORIGIN - (type_left or 0) * _TYPE_LEFT_GAIN
    return boundary - origin - _TYPE_CLEARANCE


def autofit_type(type_text, kerning=None, font_size=None, type_left=0,
                 has_set_symbol=True, set_symbol_left=None):
    """
    Determine a type `(kerning, font_size)` pair that fits the type row.

    Mirrors autofit_title(): computes a pixel budget for the available row width
    (reserving the set-symbol region on the right), and, if the type overflow,
    shrinks kerning first (the most cosmetic thing to give back) down to its
    floor, then drops font size to exactly fit.  Returns the inputs unchanged if
    the type already fits.  Neither result ever exceeds the caller's starting
    value, and both are bounded by the shared floors.

    Args:
        type_text:       raw type line (tags stripped), e.g. 'Elf Wizard'.
        kerning:         starting kerning (absolute px) or None.
        font_size:       starting {fontsize} offset (relative px) or None.
        type_left:       value of the {left#} tag (positive = room gained).
        has_set_symbol:  True if a set symbol occupies the right of the row;
        set_symbol_left: explicit symbol left edge (px) if known -- overrides the
                         fallback constant when True; None to use the constant.

    Returns:
        (kerning, font_size)
    """
    k = kerning if kerning is not None else 0
    fs = font_size if font_size is not None else 0
    left = type_left if type_left else 0

    if not type_text:
        return k, fs

    budget = _type_budget(left, has_set_symbol, set_symbol_left)
    type_w = _estimate_type_width(type_text, fs, k)
    if type_w <= budget:
        return k, fs  # no change needed

    n = max(1, len(type_text))
    base0 = _estimate_type_width(type_text, 0, 0)          # width at fs=0, k=0
    per_font = n * _TYPE_W_FONT                              # px gained per +1 {fontsize}
    per_kern = n * _TYPE_W_KERN                              # px gained per +1 {kerning}

    def fits(font_off, kern):
        return _estimate_type_width(type_text, font_off, kern) <= budget

    # Largest kerning (clamped to <= the user's value and >= the floor) that fits
    # at the current font size.
    if per_kern > 0:
        ideal_k = (budget - (base0 + per_font * fs)) / per_kern
        k = max(_KERNING_MIN, min(k, int(math.floor(ideal_k + 1e-9))))

    # If it still overflows at that kerning, drop the font size to fit.
    # Use floor (not round): we are SHRINKING, so rounding up would give a font
    # size that is still too big, and the line would silently overrun.
    if not fits(fs, k) and per_font > 0:
        target_base = budget - per_kern * k
        fs_exact = (target_base - base0) / per_font
        fs = int(math.floor(fs_exact))
        fs = max(_FONT_FLOOR, fs)

    # Post-verify: integer floors can leave the result a couple of px over budget.
    # Step down until it genuinely fits (bounded by the font floor).
    while not fits(fs, k) and fs > _FONT_FLOOR:
        fs -= 1

    print(f"   [Auto-Fit-Type] '{type_text}' (symbol={has_set_symbol}, left={left}) "
          f"-> kerning {kerning}->{k}, fontsize {font_size}->{fs} "
          f"(budget {budget:.0f}px, type_w {type_w:.0f}px)")
    return k, fs


def autofit_land_symbols(n_small_lines, symbol_max=64, symbol_min=30, symbol_step=12):
    """
    Compute the largest large-symbol point size that can share the fixed
    rules-text box with `n_small_lines` lines of small body text below it.

    The rules box has a fixed height, so the larger the symbols, the less room
    is left for text.  Reserving space for each additional body line shrinks the
    symbols by `symbol_step` points down to a floor.  This generalizes the
    previously hardcoded per-branch sizes (Bayou=64, Hallowed Fountain=52) into
    one monotonic rule so multi-line lands (e.g. Golgari Rot Farm) never overflow.

    Args:
        n_small_lines: number of small body-text lines to render beneath the symbols
        symbol_max / symbol_min / symbol_step: size calibration bounds (points)

    Returns:
        dict with 'symbol' (pt), 'text' (pt), 'gap' (pt) and 'n' (line count)
    """
    n = max(0, int(n_small_lines))
    size = symbol_max - symbol_step * n
    size = int(max(symbol_min, min(symbol_max, size)))
    # Body text and the post-symbol spacer tighten once more than one line must
    # share the box with the symbols.  Single-line layouts keep roomier values.
    text_size = 12 if n <= 1 else 11
    gap = 32 if n <= 1 else 30
    return {"symbol": size, "text": text_size, "gap": gap, "n": n}

def classify_land_lines(lines):
    """
    Reduce a land's oracle-text lines to the small body text to render beneath
    the large mana symbols, in final on-card order.

    The large mana symbols already express the land's colored tap-to-add-mana,
    so a line that is *solely* a mana ability ('{T}: Add {B}{G}.' or
    '({T}: Add {B} or {G}.)') is dropped -- the symbols stand in for it.  Everything
    else (entering-tapped, triggers, damage, costs) is preserved.  A pain land's
    colorless clause ({T}: Add {C}) is kept, and its redundant colored add-clause
    is stripped, yielding the original symbols -> damage -> {T}: Add {C} order.

    Args:
        lines: list of stripped, non-empty oracle-text lines, in card order

    Returns:
        body_lines: the small body-text lines (in render order).  May be empty
                    (e.g. Bayou -> symbols only).
    """
    def is_pure_mana_tap(line):
        # A line that is purely a tap-to-add-mana ability is fully represented by
        # the large symbols, so it's dropped from the small body text.  Shapes:
        #   '{T}: Add {B}{G}.'            (bounce / dual colored add)
        #   '({T}: Add {B} or {G}.)'       (standard dual mana reminder)
        core = (line or "").strip()
        if core.startswith("(") and core.endswith(")"):
            core = core[1:-1].strip()
        core = core.rstrip(".")
        if re.match(r'^\{T\}: Add (?:\{[A-Z]\})+$', core):
            return True
        if re.match(r'^\{T\}: Add \{[A-Z]\} or \{[A-Z]\}$', core):
            return True
        return False

    def is_colored_add(line):
        return bool(re.search(r'\{T\}: Add \{[A-Z]\} or \{[A-Z]\}\.', line or ""))

    is_pain = any("{T}: Add {C}" in (l or "") for l in lines) and any(is_colored_add(l) for l in lines)

    if is_pain:
        damage_part = colorless_clause = None
        other_lines = []
        for line in lines:
            if "{T}: Add {C}" in line:
                colorless_clause = re.sub(r'\{T\}: Add \{[A-Z]\} or \{[A-Z]\}\.\s*', '', line)
            elif is_colored_add(line):
                damage_part = re.sub(r'\{T\}: Add \{[A-Z]\} or \{[A-Z]\}\.\s*', '', line)
            else:
                other_lines.append(line)
        body = []
        if damage_part:
            body.append(damage_part)
        if colorless_clause:
            body.append(colorless_clause)
        body.extend(other_lines)
        return body

    # Standard / bounce / other dual lands: keep every line except a pure
    # mana-ability line that the large symbols already represent.
    return [line for line in lines if not is_pure_mana_tap(line)]

def build_dual_land_rules_text(symbols, body_lines, formatter=None):
    """
    Build the Card Conjurer rules text for a land that shows large mana symbols
    plus an optional stack of small body-text lines.

    The symbol size is computed from the number of body lines so the pair always
    fits the fixed rules box (see autofit_land_symbols).

    Args:
        symbols:    large mana tokens, e.g. "{B} {G}"
        body_lines: small body-text lines to render under the symbols, in the
                    desired order, already stripped of redundant mana-ability
                    text.  May be empty (Bayou -> symbols only).
        formatter:  optional callable applied to each body line (e.g. to italicize
                    reminder text / normalize quotes).  Defaults to identity.

    Returns:
        the rules text string ready for Card Conjurer
    """
    fit = autofit_land_symbols(len(body_lines or []))
    sz = fit["symbol"]
    txt = fit["text"]
    gap = fit["gap"]

    body_lines = body_lines or []
    if not body_lines:
        return f"{{down80}}{{fontsize{sz}pt}}{{center}}{symbols}"

    fmt = formatter or (lambda s: s)
    base = f"{{fontsize{txt}pt}}"
    body = base + ("\n" + base).join(fmt(line) for line in body_lines)
    return f"{{fontsize{sz}pt}}{{center}}{symbols}{{fontsize{gap}pt}}\n{body}"

def autofit_art_position(art_width, art_height, card_data):
    """
    Calculate optimal art position and zoom to fit within artBounds.
    
    Translated from Card Conjurer JavaScript autoFitArt() function.
    
    Args:
        art_width: Width of the art image in pixels
        art_height: Height of the art image in pixels
        card_data: Card data dict containing width, height, artBounds, marginX, marginY
        
    Returns:
        Dict with artX, artY, artZoom, artRotate (all normalized values for JSON)
        Returns None if required data is missing
    """
    if not art_width or not art_height:
        return None
        
    if 'artBounds' not in card_data:
        return None
    
    try:
        # Card dimensions
        card_width = card_data.get('width', 2010)
        card_height = card_data.get('height', 2814)
        
        # Art bounds (normalized 0-1)
        bounds = card_data['artBounds']
        bounds_x = bounds.get('x', 0)
        bounds_y = bounds.get('y', 0)
        bounds_w = bounds.get('width', 1)
        bounds_h = bounds.get('height', 1)
        
        # Margins (normalized 0-1)
        margin_x = card_data.get('marginX', 0)
        margin_y = card_data.get('marginY', 0)
        
        # Scale functions (convert normalized to pixels)
        def scale_x(val): return val * card_width
        def scale_y(val): return val * card_height
        def scale_w(val): return val * card_width
        def scale_h(val): return val * card_height
        
        # Calculate aspect ratios
        art_ratio = art_width / art_height
        bounds_ratio = scale_w(bounds_w) / scale_h(bounds_h)
        
        # JavaScript logic:
        # if (art.width / art.height > scaleWidth(card.artBounds.width) / scaleHeight(card.artBounds.height))
        if art_ratio > bounds_ratio:
            # Art is wider than bounds -> Fit to HEIGHT
            # JS: document.querySelector('#art-y').value = Math.round(scaleY(card.artBounds.y) - scaleHeight(card.marginY));
            art_y_pixels = round(scale_y(bounds_y) - scale_h(margin_y))
            
            # JS: document.querySelector('#art-zoom').value = (scaleHeight(card.artBounds.height) / art.height * 100).toFixed(1);
            zoom = scale_h(bounds_h) / art_height
            
            # JS: document.querySelector('#art-x').value = Math.round(scaleX(card.artBounds.x) - (document.querySelector('#art-zoom').value / 100 * art.width - scaleWidth(card.artBounds.width)) / 2 - scaleWidth(card.marginX));
            # Note: zoom input is percentage, so zoom/100 is the factor
            scaled_art_width = zoom * art_width
            art_x_pixels = round(scale_x(bounds_x) - (scaled_art_width - scale_w(bounds_w)) / 2 - scale_w(margin_x))
        else:
            # Art is taller/narrower than bounds -> Fit to WIDTH
            # JS: document.querySelector('#art-x').value = Math.round(scaleX(card.artBounds.x) - scaleWidth(card.marginX));
            art_x_pixels = round(scale_x(bounds_x) - scale_w(margin_x))
            
            # JS: document.querySelector('#art-zoom').value = (scaleWidth(card.artBounds.width) / art.width * 100).toFixed(1);
            zoom = scale_w(bounds_w) / art_width
            
            # JS: document.querySelector('#art-y').value = Math.round(scaleY(card.artBounds.y) - (document.querySelector('#art-zoom').value / 100 * art.height - scaleHeight(card.artBounds.height)) / 2 - scaleHeight(card.marginY));
            scaled_art_height = zoom * art_height
            art_y_pixels = round(scale_y(bounds_y) - (scaled_art_height - scale_h(bounds_h)) / 2 - scale_h(margin_y))
        
        # Convert pixels back to normalized values for JSON
        # Card Conjurer JSON stores normalized values (0-1)
        # Note: Card Conjurer JSON stores zoom as the UI percentage value / 100
        # But based on testing, it seems to store the percentage value directly
        return {
            'artX': art_x_pixels / card_width,
            'artY': art_y_pixels / card_height,
            'artZoom': zoom,
            'artRotate': 0
        }
        
    except Exception as e:
        print(f"   Warning: Autofit calculation failed: {e}", file=sys.stderr)
        return None

def autofit_set_symbol(set_symbol_url, card_data, image_server_url=None):
    """
    Calculate optimal set symbol position and zoom based on SVG dimensions.
    
    Translated from Card Conjurer JavaScript resetSetSymbol() function.
    
    Args:
        set_symbol_url: URL or path to the set symbol SVG
        card_data: Card data dict containing width, height, setSymbolBounds, marginX, marginY
        image_server_url: Base URL for fetching SVG (if set_symbol_url is relative)
        
    Returns:
        Dict with setSymbolX, setSymbolY, setSymbolZoom (all normalized values for JSON)
        Returns None if required data is missing or SVG cannot be fetched
    """
    import sys
    
    # Check if lxml is available
    if not HAS_LXML:
        print(f"   Warning: lxml not available, skipping set symbol autofit. Install lxml for automatic set symbol positioning.", file=sys.stderr)
        return None
    
    if 'setSymbolBounds' not in card_data:
        return None
    
    try:
        # Fetch SVG to get dimensions
        svg_url = set_symbol_url
        if set_symbol_url.startswith('/') and image_server_url:
            svg_url = f"{image_server_url.rstrip('/')}{set_symbol_url}"
        
        svg_content = None
        
        # Handle Data URI
        if svg_url.startswith('data:image/svg+xml;base64,'):
            try:
                import base64
                b64_data = svg_url.split(',', 1)[1]
                svg_content = base64.b64decode(b64_data)
            except Exception as e:
                display_url = svg_url if len(svg_url) < 100 else svg_url[:97] + "..."
                print(f"   Warning: Failed to decode Data URI for set symbol: {e}", file=sys.stderr)
                return None
        else:
            # Fetch from URL
            for attempt in range(3):
                try:
                    headers = {"User-Agent": "ccAutomator/1.0 (custom card frame automation tool)"} if "scryfall.io" in svg_url else None
                    resp = requests.get(svg_url, headers=headers, timeout=10)
                    resp.raise_for_status()
                    svg_content = resp.content
                    break
                except Exception as e:
                    if attempt == 2:
                        display_url = svg_url if len(svg_url) < 100 else svg_url[:97] + "..."
                        print(f"   Warning: Failed to fetch set symbol SVG from {display_url}: {e}", file=sys.stderr)
                        return None
                    time.sleep(1)
        
        if not svg_content:
            return None
            
        # Parse dimensions based on file type
        svg_width, svg_height = None, None
        
        # Check if it's a PNG (based on extension or content header if available)
        is_png = svg_url.lower().endswith('.png')
        
        if is_png:
            try:
                img = Image.open(io.BytesIO(svg_content))
                svg_width, svg_height = img.size
                # print(f"   [Debug] Parsed PNG dimensions: {svg_width}x{svg_height}")
            except Exception as e:
                print(f"   Warning: Could not parse PNG: {e}", file=sys.stderr)
                return None
        else:
            # Assume SVG
            try:
                parser = etree.XMLParser(resolve_entities=False, no_network=True, recover=True)
                svg_root = etree.fromstring(svg_content, parser=parser)
                
                viewbox = svg_root.get("viewBox")
                width_str = svg_root.get("width")
                height_str = svg_root.get("height")
                
                # IMPORTANT: Prioritize explicit width/height attributes over viewBox
                # This matches how browsers render SVGs and how Card Conjurer's JavaScript gets dimensions
                
                def parse_dimension(dim_str):
                    if not dim_str or dim_str.endswith('%'):
                        return None
                    
                    # Normalize
                    dim_str = dim_str.strip().lower()
                    
                    # Extract value and unit
                    import re
                    match = re.match(r'^([\d\.\-e]+)([a-z]*)$', dim_str)
                    if not match:
                        return None
                        
                    value = float(match.group(1))
                    unit = match.group(2)
                    
                    # Convert to pixels (assuming 96 DPI)
                    if unit == 'mm':
                        return value * 3.7795
                    elif unit == 'cm':
                        return value * 37.795
                    elif unit == 'in':
                        return value * 96.0
                    elif unit == 'pt':
                        return value * 1.3333
                    elif unit == 'pc':
                        return value * 16.0
                    else:
                        # 'px' or no unit
                        return value

                if width_str:
                    svg_width = parse_dimension(width_str)
                if height_str:
                    svg_height = parse_dimension(height_str)
                
                # Fallback to viewBox only if width/height not available
                if (svg_width is None or svg_height is None) and viewbox:
                    import re
                    parts = [float(x) for x in re.split(r'[,\s]+', viewbox.strip())]
                    if len(parts) == 4:
                        if svg_width is None:
                            svg_width = parts[2]
                        if svg_height is None:
                            svg_height = parts[3]
                
                if not svg_width or not svg_height or svg_width <= 0 or svg_height <= 0:
                    print(f"   Warning: Could not parse valid SVG dimensions (W={svg_width}, H={svg_height})", file=sys.stderr)
                    return None
                
                # print(f"   [Debug] Parsed SVG dimensions: {svg_width}x{svg_height}")
                     
            except Exception as e:
                print(f"   Warning: Could not parse SVG: {e}", file=sys.stderr)
                return None
        
        # Card dimensions
        card_width = card_data.get('width', 2010)
        card_height = card_data.get('height', 2814)
        
        # Set symbol bounds (normalized 0-1)
        bounds = card_data['setSymbolBounds']
        bounds_x = bounds.get('x', 0)
        bounds_y = bounds.get('y', 0)
        bounds_w = bounds.get('width', 0.12)
        bounds_h = bounds.get('height', 0.0372)
        
        # Margins (normalized 0-1)
        margin_x = card_data.get('marginX', 0)
        margin_y = card_data.get('marginY', 0)
        
        # Alignment
        horizontal = bounds.get('horizontal', 'left')
        vertical = bounds.get('vertical', 'top')
        
        # Scale functions
        def scale_x(val): return val * card_width
        def scale_y(val): return val * card_height
        def scale_w(val): return val * card_width
        def scale_h(val): return val * card_height
        
        # Calculate zoom (fit to bounds)
        # JS: if (setSymbol.width / setSymbol.height > scaleWidth(card.setSymbolBounds.width) / scaleHeight(card.setSymbolBounds.height))
        # Calculate zoom (fit to bounds)
        # JS: if (setSymbol.width / setSymbol.height > scaleWidth(card.setSymbolBounds.width) / scaleHeight(card.setSymbolBounds.height))
        symbol_ratio = svg_width / svg_height
        bounds_ratio = scale_w(bounds_w) / scale_h(bounds_h)
        
        if symbol_ratio > bounds_ratio:
            # Symbol is wider -> fit to width
            zoom = scale_w(bounds_w) / svg_width
        else:
            # Symbol is taller -> fit to height
            zoom = scale_h(bounds_h) / svg_height
        
        # Initial position (top-left of bounds)
        symbol_x_pixels = round(scale_x(bounds_x))
        symbol_y_pixels = round(scale_y(bounds_y))
        
        # Adjust for horizontal alignment
        scaled_symbol_width = svg_width * zoom
        if horizontal == 'center':
            # JS: document.querySelector('#setSymbol-x').value = Math.round(scaleX(card.setSymbolBounds.x) - (setSymbol.width * setSymbolZoom / 100) / 2 - scaleWidth(card.marginX));
            symbol_x_pixels = round(scale_x(bounds_x) - scaled_symbol_width / 2 - scale_w(margin_x))
        elif horizontal == 'right':
            # JS: document.querySelector('#setSymbol-x').value = Math.round(scaleX(card.setSymbolBounds.x) - (setSymbol.width * setSymbolZoom / 100) - scaleWidth(card.marginX));
            symbol_x_pixels = round(scale_x(bounds_x) - scaled_symbol_width - scale_w(margin_x))
        
        # Adjust for vertical alignment
        scaled_symbol_height = svg_height * zoom
        if vertical == 'center':
            # JS: document.querySelector('#setSymbol-y').value = Math.round(scaleY(card.setSymbolBounds.y) - (setSymbol.height * setSymbolZoom / 100) / 2 - scaleHeight(card.marginY));
            symbol_y_pixels = round(scale_y(bounds_y) - scaled_symbol_height / 2 - scale_h(margin_y))
        elif vertical == 'bottom':
            # JS: document.querySelector('#setSymbol-y').value = Math.round(scaleY(card.setSymbolBounds.y) - (setSymbol.height * setSymbolZoom / 100) - scaleHeight(card.marginY));
            symbol_y_pixels = round(scale_y(bounds_y) - scaled_symbol_height - scale_h(margin_y))
        
        # Convert to normalized values for JSON
        return {
            'setSymbolX': symbol_x_pixels / card_width,
            'setSymbolY': symbol_y_pixels / card_height,
            'setSymbolZoom': zoom
        }
        
    except Exception as e:
        print(f"   Warning: Set symbol autofit failed: {e}", file=sys.stderr)
        return None

def fetch_and_fix_svg_source(url: str) -> str:
    """
    Fetches an SVG from the given URL.
    If the SVG has percentage dimensions (e.g. width="100%"), it replaces them with
    the viewBox dimensions (in pixels) and returns a Data URI.
    Otherwise, returns the original URL.
    """
    if not HAS_LXML:
        return url
        
    # Ignore PNGs
    if url.lower().endswith('.png'):
        return url
        
    try:
        # Fetch SVG
        resp = requests.get(url, timeout=10)
        if resp.status_code != 200:
            return url
            
        content = resp.content
        parser = etree.XMLParser(resolve_entities=False, no_network=True, recover=True)
        svg_root = etree.fromstring(content, parser=parser)
        
        if svg_root is None:
            return url
        
        width = svg_root.get("width")
        height = svg_root.get("height")
        viewbox = svg_root.get("viewBox")
        
        needs_fix = False
        if width and '%' in width: needs_fix = True
        if height and '%' in height: needs_fix = True
        
        if needs_fix and viewbox:
            # Extract dimensions from viewBox
            import re
            parts = [x for x in re.split(r'[,\s]+', viewbox.strip()) if x]
            if len(parts) == 4:
                vb_width = parts[2]
                vb_height = parts[3]
                
                # print(f"   [Fix] Replacing percentage dimensions with {vb_width}x{vb_height} for {url}")
                svg_root.set("width", vb_width)
                svg_root.set("height", vb_height)
                
                # Serialize back to string
                fixed_content = etree.tostring(svg_root, encoding='utf-8')
                
                # Convert to Data URI
                import base64
                b64 = base64.b64encode(fixed_content).decode('utf-8')
                return f"data:image/svg+xml;base64,{b64}"
                
    except Exception as e:
        print(f"   Warning: Failed to fix SVG source: {e}", file=sys.stderr)
        
    return url

# ==============================================================================
# Output File Saving
# ==============================================================================

def save_cardconjurer_file(cards_data, output_filename, output_dir='downloads'):
    """
    Save .cardconjurer JSON file locally.
    
    Args:
        cards_data: List of card JSON objects
        output_filename: Base filename (without extension)
        output_dir: Directory to save to
    
    Returns:
        Full path to saved file
    """
    import os
    import json
    
    # Ensure output directory exists
    os.makedirs(output_dir, exist_ok=True)
    
    # Add .cardconjurer extension if not present
    if not output_filename.endswith('.cardconjurer'):
        output_filename += '.cardconjurer'
    
    output_path = os.path.join(output_dir, output_filename)
    
    # Save JSON array
    with open(output_path, 'w') as f:
        json.dump(cards_data, f, separators=(',', ':'))
    
    return output_path
