import re
import unicodedata
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple
import requests
from PIL import Image
import io

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
                    card_name = match.group(1).strip()
                    cards.append({'name': card_name, 'category': current_category})
                else:
                    # Assume the whole line is the card name if no number prefix
                    cards.append({'name': line, 'category': current_category})
                    
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
    Build Scryfall query string based on card section and filters.
    
    Different sections use different query modifiers:
    - 'token': adds 't:token'
    - 'deck': adds spell-specific filters
    - 'land': adds land-specific filters
    
    Args:
        card_name: Name of the card
        section: Section name ('deck', 'land', 'token', etc.)
        set_code: Optional set code
        collector_number: Optional collector number
        scryfall_filter: Additional Scryfall query filters
        spells_include_set: Whitelist of sets for spells
        spells_exclude_set: Blacklist of sets for spells
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
    
    # Add section-specific modifiers
    section_lower = section.lower()
    
    if section_lower == 'token' or section_lower == 'tokens':
        query += " t:token"
    
    # Add set filters based on section
    if section_lower == 'land':
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
    
    elif section_lower == 'deck':
        # Spell filters
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
