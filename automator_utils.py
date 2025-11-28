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
