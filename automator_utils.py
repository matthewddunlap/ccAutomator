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
    
    Tries progressively broader queries:
    1. Full query with all filters
    2. Remove include filters, keep exclude filters
    3. Remove 'not:covered', keep exclude filters  
    4. Remove all filters (broadest search)
    
    Args:
        Same as build_scryfall_query
        
    Returns:
        Scryfall card data dict if found, None otherwise
    """
    import sys
    
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
        resp = requests.get("https://api.scryfall.com/cards/search", params={'q': query})
        if resp.status_code == 200:
            results = resp.json().get('data', [])
            if results:
                return results[0]
    except Exception as e:
        print(f"   Warning: Query failed: {e}", file=sys.stderr)
    
    # Fallback 1: Remove include filters, keep exclude filters
    if current_include_set and current_exclude_set:
        print(f"   Warning: Initial query found no matches. Stripping include sets but keeping exclude sets...", file=sys.stderr)
        fallback_query = build_scryfall_query(
            card_name=card_name,
            section=section,
            set_code=set_code,
            collector_number=collector_number,
            scryfall_filter=scryfall_filter,
            spells_include_set=None,
            spells_exclude_set=spells_exclude_set if not is_basic_land else None,
            basic_land_include_set=None,
            basic_land_exclude_set=basic_land_exclude_set if is_basic_land else None
        )
        print(f"   Scryfall fallback query (excludes only): {fallback_query}")
        try:
            resp = requests.get("https://api.scryfall.com/cards/search", params={'q': fallback_query})
            if resp.status_code == 200:
                results = resp.json().get('data', [])
                if results:
                    return results[0]
        except Exception as e:
            print(f"   Warning: Fallback query failed: {e}", file=sys.stderr)
    
    # Fallback 2: Remove 'not:covered', keep exclude filters
    if current_exclude_set:
        print(f"   Warning: Fallback 1 found no matches. Stripping 'not:covered' but keeping exclude sets...", file=sys.stderr)
        # Build a simpler query without not:covered
        base_query = f'!"{card_name}"'
        if set_code:
            base_query += f" set:{set_code}"
        if collector_number:
            base_query += f" cn:{collector_number}"
        if section.lower() in ['token', 'tokens']:
            base_query += " t:token"
        
        # Add exclude filters
        if current_exclude_set:
            exclude_sets = parse_set_list(current_exclude_set)
            for s in exclude_sets:
                base_query += f" -set:{s}"
        
        if scryfall_filter:
            base_query += f" {scryfall_filter}"
        
        print(f"   Scryfall fallback query (excludes only, no not:covered): {base_query}")
        try:
            resp = requests.get("https://api.scryfall.com/cards/search", params={'q': base_query})
            if resp.status_code == 200:
                results = resp.json().get('data', [])
                if results:
                    return results[0]
        except Exception as e:
            print(f"   Warning: Fallback query 2 failed: {e}", file=sys.stderr)
    
    # Fallback 3: Strip ALL filters
    print(f"   Warning: Query found no matches. Stripping ALL set filters and retrying a broader Scryfall search.", file=sys.stderr)
    simple_query = f'!"{card_name}"'
    if set_code:
        simple_query += f" set:{set_code}"
    if collector_number:
        simple_query += f" cn:{collector_number}"
    if section.lower() in ['token', 'tokens']:
        simple_query += " t:token"
    
    print(f"   Scryfall fallback query (no filters): {simple_query}")
    try:
        resp = requests.get("https://api.scryfall.com/cards/search", params={'q': simple_query})
        if resp.status_code == 200:
            results = resp.json().get('data', [])
            if results:
                return results[0]
    except Exception as e:
        print(f"   Warning: Final fallback query failed: {e}", file=sys.stderr)
    
    return None

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
                    resp = requests.get(svg_url, timeout=10)
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
