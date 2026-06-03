import json
import os
import re
import sys
import math
from unittest.mock import MagicMock
sys.modules['gradio_client'] = MagicMock()

import requests
from pathlib import Path
from automator_utils import (
    generate_safe_filename,
    get_image_mime_type_and_extension,
    DEFAULT_UPSCALER_MODEL,
    scryfall_query_with_fallback
)
# Add parent directory to path to import mixins
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from mixins.image_mixin import ImageMixin
from mixins.collector_mixin import CollectorMixin

# Color Maps
COLOR_MAP = {
    'W': 'w', 'U': 'u', 'B': 'b', 'R': 'r', 'G': 'g',
    'M': 'm', 'C': 'c', 'A': 'a', 'L': 'l'
}

LAND_COLOR_MAP = {
    'W': 'wl', 'U': 'ul', 'B': 'bl', 'R': 'rl', 'G': 'gl'
}

class SeventhGenerator(ImageMixin, CollectorMixin):
    def __init__(self, image_server_url="http://mtgproxy:4242", download_dir="downloads", 
                 upload_secret=None, art_path="/local_art/art/", upscaler_model=DEFAULT_UPSCALER_MODEL):
        self.image_server_url = image_server_url
        self.download_dir = download_dir
        self.upload_secret = upload_secret
        self.driver = None # Not needed for generation
        self.upscale_art = True # Corrected name
        self.ilaria_url = None # Initialize ilaria_url
        self.upscaler_model = upscaler_model
        self.upscaler_factor = 4
        self.art_path = art_path
        self.app_url = None  # No Selenium app URL in JSON mode, prevents art URL trimming
        
    def determine_frame_layers(self, scryfall_data, white_border=False):
        layers = []
        
        # Extract attributes
        colors = scryfall_data.get('colors', [])
        if not colors and 'card_faces' in scryfall_data:
            colors = scryfall_data['card_faces'][0].get('colors', [])
            
        type_line = scryfall_data.get('type_line', '')
        is_land = 'Land' in type_line
        is_artifact = 'Artifact' in type_line and not is_land
        
        # Frame Name Mapping
        FRAME_NAMES = {
            'w': 'White Frame', 'u': 'Blue Frame', 'b': 'Black Frame', 'r': 'Red Frame', 'g': 'Green Frame',
            'm': 'Multicolored Frame', 'a': 'Artifact Frame', 'l': 'Land Frame', 'c': 'Colorless Frame',
            'wl': 'White Land Frame', 'ul': 'Blue Land Frame', 'bl': 'Black Land Frame',
            'rl': 'Red Land Frame', 'gl': 'Green Land Frame'
        }

        # Determine Base Code
        if is_land:
            # Land Logic
            # For lands, we ignore colorless 'C' when determining frame color
            produced_mana = scryfall_data.get('produced_mana', [])
            colored_mana = [c for c in produced_mana if c in ['W', 'U', 'B', 'R', 'G']]
            # Ensure WUBRG order
            wubrg_order = {'W': 0, 'U': 1, 'B': 2, 'R': 3, 'G': 4}
            colored_mana.sort(key=lambda x: wubrg_order.get(x, 99))
            
            if len(colored_mana) == 0:
                # Colorless Land
                pinline = 'l'; rules = 'l'; frame = 'l'; textbox = 'l'; border = 'l'
                layers = [
                    (FRAME_NAMES['l'], f'regular/{pinline}.png', 'Pinline'),
                    (FRAME_NAMES['l'], f'regular/{rules}.png', 'Rules'),
                    (FRAME_NAMES['l'], f'regular/{frame}.png', 'Frame'),
                    (FRAME_NAMES['l'], f'regular/{textbox}.png', 'Textbox Pinline'),
                    (FRAME_NAMES['l'], f'regular/{border}.png', 'Border')
                ]
                
            elif len(colored_mana) == 1:
                # Single Color Land
                c = colored_mana[0]
                code = LAND_COLOR_MAP.get(c, 'l')
                layers = [
                    (FRAME_NAMES.get(code, 'Land Frame'), f'regular/{code}.png', 'Pinline'),
                    (FRAME_NAMES.get(code, 'Land Frame'), f'regular/{code}.png', 'Rules'),
                    (FRAME_NAMES['l'], 'regular/l.png', 'Frame'),
                    (FRAME_NAMES.get(code, 'Land Frame'), f'regular/{code}.png', 'Textbox Pinline'),
                    (FRAME_NAMES['l'], 'regular/l.png', 'Border')
                ]
                
            elif len(colored_mana) == 2:
                # Dual Land
                c1 = colored_mana[0]
                c2 = colored_mana[1]
                code1 = LAND_COLOR_MAP.get(c1, 'l')
                code2 = LAND_COLOR_MAP.get(c2, 'l')
                
                # Split Pinlines
                layers.append({
                    "name": FRAME_NAMES.get(code2, 'Land Frame'),
                    "src": f"/img/frames/seventh/regular/{code2}.png",
                    "masks": [
                        {"src": "/img/frames/seventh/regular/pinline.svg", "name": "Pinline"},
                        {"src": "/img/frames/maskRightHalf.png", "name": "Right Half"}
                    ]
                })
                layers.append((FRAME_NAMES.get(code1, 'Land Frame'), f'regular/{code1}.png', 'Pinline'))

                # Split Rules Box
                layers.append({
                    "name": FRAME_NAMES.get(code2, 'Land Frame'),
                    "src": f"/img/frames/seventh/regular/{code2}.png",
                    "masks": [
                        {"src": "/img/frames/seventh/regular/rules.svg", "name": "Rules"},
                        {"src": "/img/frames/maskRightHalf.png", "name": "Right Half"}
                    ]
                })
                layers.append((FRAME_NAMES.get(code1, 'Land Frame'), f'regular/{code1}.png', 'Rules'))

                # Split Textbox Pinline (Trim)
                layers.append({
                    "name": FRAME_NAMES.get(code2, 'Land Frame'),
                    "src": f"/img/frames/seventh/regular/{code2}.png",
                    "masks": [
                        {"src": "/img/frames/seventh/regular/trim.svg", "name": "Textbox Pinline"},
                        {"src": "/img/frames/maskRightHalf.png", "name": "Right Half"}
                    ]
                })
                layers.append((FRAME_NAMES.get(code1, 'Land Frame'), f'regular/{code1}.png', 'Textbox Pinline'))
                
                layers.append((FRAME_NAMES['l'], 'regular/l.png', 'Frame'))
                layers.append((FRAME_NAMES['l'], 'regular/l.png', 'Border'))
                
            else:
                # 3+ colors -> Generic Land
                layers = [
                    (FRAME_NAMES['l'], 'regular/l.png', 'Pinline'),
                    (FRAME_NAMES['l'], 'regular/l.png', 'Rules'),
                    (FRAME_NAMES['l'], 'regular/l.png', 'Frame'),
                    (FRAME_NAMES['l'], 'regular/l.png', 'Textbox Pinline'),
                    (FRAME_NAMES['l'], 'regular/l.png', 'Border')
                ]

        elif is_artifact:
            # Artifact Logic
            # Check for colors to support Colored Artifacts
            # Ensure WUBRG order for colors
            wubrg_order = {'W': 0, 'U': 1, 'B': 2, 'R': 3, 'G': 4}
            
            # Use colors if present, otherwise fallback to color_identity
            target_colors = colors
            if not target_colors:
                target_colors = scryfall_data.get('color_identity', [])
                
            sorted_colors = sorted([c for c in target_colors if c in wubrg_order], key=lambda x: wubrg_order.get(x, 99))
            
            if not sorted_colors:
                # Colorless Artifact (Standard)
                code = 'a'
                layers = [
                    (FRAME_NAMES.get(code, 'Artifact Frame'), f'regular/{code}.png', 'Pinline'),
                    (FRAME_NAMES.get(code, 'Artifact Frame'), f'regular/{code}.png', 'Rules'),
                    (FRAME_NAMES.get(code, 'Artifact Frame'), f'regular/{code}.png', 'Frame'),
                    (FRAME_NAMES.get(code, 'Artifact Frame'), f'regular/{code}.png', 'Textbox Pinline'),
                    (FRAME_NAMES.get(code, 'Artifact Frame'), f'regular/{code}.png', 'Border')
                ]
            elif len(sorted_colors) == 1:
                # Single Color Artifact
                # Base: Artifact (a)
                # Rules/Pinline: Colored Land (xl)
                c = sorted_colors[0]
                code = LAND_COLOR_MAP.get(c, 'l') # e.g., 'rl' for Red
                base_code = 'a'
                
                layers = [
                    (FRAME_NAMES.get(code, 'Land Frame'), f'regular/{code}.png', 'Pinline'),
                    (FRAME_NAMES.get(code, 'Land Frame'), f'regular/{code}.png', 'Rules'),
                    (FRAME_NAMES.get(base_code, 'Artifact Frame'), f'regular/{base_code}.png', 'Frame'),
                    (FRAME_NAMES.get(code, 'Land Frame'), f'regular/{code}.png', 'Textbox Pinline'),
                    (FRAME_NAMES.get(base_code, 'Artifact Frame'), f'regular/{base_code}.png', 'Border')
                ]
            elif len(sorted_colors) == 2:
                # Dual Color Artifact
                # Base: Artifact (a)
                # Rules: Split (Right Color + Left Color)
                # Pinline: Artifact (a) - matching Bayou example which used 'l' (generic)
                c1 = sorted_colors[0]
                c2 = sorted_colors[1]
                code1 = LAND_COLOR_MAP.get(c1, 'l')
                code2 = LAND_COLOR_MAP.get(c2, 'l')
                base_code = 'a'
                
                layers.append((FRAME_NAMES.get(base_code, 'Artifact Frame'), f'regular/{base_code}.png', 'Pinline'))
                
                # Split Rules Box
                layers.append({
                    "name": FRAME_NAMES.get(code2, 'Land Frame'),
                    "src": f"/img/frames/seventh/regular/{code2}.png",
                    "masks": [
                        {"src": "/img/frames/seventh/regular/rules.svg", "name": "Rules"},
                        {"src": "/img/frames/maskRightHalf.png", "name": "Right Half"}
                    ]
                })
                
                layers.append((FRAME_NAMES.get(code1, 'Land Frame'), f'regular/{code1}.png', 'Rules'))
                
                layers.append((FRAME_NAMES.get(base_code, 'Artifact Frame'), f'regular/{base_code}.png', 'Frame'))
                layers.append((FRAME_NAMES.get(base_code, 'Artifact Frame'), f'regular/{base_code}.png', 'Textbox Pinline'))
                layers.append((FRAME_NAMES.get(base_code, 'Artifact Frame'), f'regular/{base_code}.png', 'Border'))
                
            else:
                # 3+ Colors Artifact
                # Treat as Standard Artifact (matching City of Brass example which used 'l')
                code = 'a'
                layers = [
                    (FRAME_NAMES.get(code, 'Artifact Frame'), f'regular/{code}.png', 'Pinline'),
                    (FRAME_NAMES.get(code, 'Artifact Frame'), f'regular/{code}.png', 'Rules'),
                    (FRAME_NAMES.get(code, 'Artifact Frame'), f'regular/{code}.png', 'Frame'),
                    (FRAME_NAMES.get(code, 'Artifact Frame'), f'regular/{code}.png', 'Textbox Pinline'),
                    (FRAME_NAMES.get(code, 'Artifact Frame'), f'regular/{code}.png', 'Border')
                ]
                
        else:
            # Regular Card
            if len(colors) == 0:
                code = 'a' # Colorless non-land usually Artifact, but if Eldrazi? 7th didn't have. Use 'a' or 'c'.
            elif len(colors) == 1:
                code = COLOR_MAP[colors[0]]
            else:
                code = 'm' # Multicolor
                
            for mask in ['Pinline', 'Rules', 'Frame', 'Textbox Pinline', 'Border']:
                layers.append((FRAME_NAMES.get(code, f'{code.upper()} Frame'), f'regular/{code}.png', mask))

        # Apply White Border if requested
        if white_border:
            wb_layer = {
                "name": "White Border",
                "src": "/img/frames/white.png",
                "masks": [{"src": "/img/frames/seventh/regular/border.svg", "name": "Border"}],
                "noDefaultMask": True
            }
            layers.insert(0, wb_layer)

        # Convert to final JSON structure
        final_frames = []
        for item in layers:
            if isinstance(item, dict):
                final_frames.append(item)
            else:
                name, src, mask_name = item
                mask_file = ""
                if mask_name == "Pinline": mask_file = "pinline.svg"
                elif mask_name == "Rules": mask_file = "rules.svg"
                elif mask_name == "Frame": mask_file = "frame.svg"
                elif mask_name == "Textbox Pinline": mask_file = "trim.svg"
                elif mask_name == "Border": mask_file = "border.svg"
                
                final_frames.append({
                    "name": name,
                    "src": f"/img/frames/seventh/{src}",
                    "masks": [{"src": f"/img/frames/seventh/regular/{mask_file}", "name": mask_name}]
                })
                
        return final_frames

    def _format_text(self, text, is_flavor=False, is_basic_land=False):
        if not text:
            return ""
            
        # Italicize Reminder Text (text in parentheses)
        # This covers basic lands and keyword abilities
        text = re.sub(r'(\([^\)]+\))', r'{i}\1{/i}', text)
            
        # Smart Quotes
        # Open quotes: Start of string or preceded by space/bracket
        text = re.sub(r'(^|[\s(\[{])"', r'\1“', text)
        # Close quotes: Everything else
        text = text.replace('"', '”')
        
        # Smart Apostrophe
        text = text.replace("'", "’")
        
        # Convert all newlines to {lns} (applies to both oracle and flavor text)
        # text = text.replace('\n', '{lns}')
                
        return text

    def generate_card(self, card_name, section='deck', set_code=None, collector_number=None,
                     scryfall_filter=None, spells_include_set=None, spells_exclude_set=None,
                     basic_land_include_set=None, basic_land_exclude_set=None,
                     # Text modifications
                     title_font_size=None, title_shadow=None, title_kerning=None, title_left=None, title_up=None,
                     type_font_size=None, type_shadow=None, type_kerning=None, type_left=None,
                     pt_font_size=None, pt_shadow=None, pt_kerning=None, pt_up=None, pt_left=None, pt_bold=False,
                     flavor_font_size=None,
                     white_border=False, auto_fit_type=False,
                     image_server_url=None):
        """
        Generates a single card JSON object.
        """
        # 1. Get Scryfall Data with fallback logic
        print(f"Fetching data for {card_name}...")
        
        data = scryfall_query_with_fallback(
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
        
        if not data:
            print(f"Error: Could not find '{card_name}' on Scryfall after all fallback attempts", file=sys.stderr)
            return None
            
        # 2. Prepare Art
        print(f"Processing art for {card_name}...")
        final_art_url, _, art_width, art_height = self._prepare_art_asset(
            card_name=card_name,
            set_code=data['set'],
            collector_number=data['collector_number'],
            scryfall_data=data
        )
        
        # 3. Determine Frames
        # We need to map colors/type to frame images.
        # We can use the logic from analyze_seventh_frames.py or similar.
        
        frames = self.determine_frame_layers(data, white_border=white_border)
        
        # 4. Set Symbol
        rarity_map = {'common': 'c', 'uncommon': 'u', 'rare': 'r', 'mythic': 'm', 'special': 'r', 'bonus': 'm'}
        rarity_code = rarity_map.get(data['rarity'], 'c')
        # 4. Set Symbol
        # Use absolute URL if image_server_url is available
        if image_server_url:
            base_url = f"{image_server_url}/img/setSymbols/official/{data['set']}-{rarity_code}"
            svg_url = f"{base_url}.svg"
            png_url = f"{base_url}.png"
            
            set_symbol_url = svg_url
            
            # Check if SVG exists, if not try PNG
            try:
                # Use a short timeout for the check
                resp = requests.head(svg_url, timeout=2)
                if resp.status_code == 404:
                    # SVG not found, try PNG
                    resp_png = requests.head(png_url, timeout=2)
                    if resp_png.status_code == 200:
                        set_symbol_url = png_url
                        # print(f"   [Info] SVG not found, using PNG for set symbol: {png_url}")
            except Exception as e:
                # On network error, default to SVG
                pass
        else:
            set_symbol_url = f"/img/setSymbols/official/{data['set']}-{rarity_code}.svg"
            
        # Fix SVG if it has percentage dimensions (returns Data URI if fixed, else original URL)
        # If it's a PNG, fetch_and_fix_svg_source will return the URL as is (because lxml parse fails)
        from automator_utils import fetch_and_fix_svg_source
        set_symbol_url = fetch_and_fix_svg_source(set_symbol_url)
        
        # 5. Text Processing
        title = data['name']
        type_line = data['type_line']
        
        # Auto-Fit Type Logic
        if auto_fit_type:
            char_count = len(type_line)
            
            k = type_kerning if type_kerning is not None else 0
            f = type_font_size if type_font_size is not None else 0
            
            # Threshold calculation from TextMixin
            threshold = 34 - k - math.floor(f * 0.3)
            excess = max(0, char_count - threshold)
            
            if excess > 0:
                available_k_drop = max(0, k - 1)
                k_drop = min(excess, available_k_drop)
                
                type_kerning = k - k_drop
                remaining_excess = excess - k_drop
                
                f_drop = math.ceil(remaining_excess * 2.5)
                type_font_size = f - f_drop
                
                print(f"   [Auto-Fit] Length {char_count} (Excess {excess}). Adjusted Type: Kerning {k}->{type_kerning}, Size {f}->{type_font_size}")
        
        # Apply Title Mods
        title_mods = ""
        if title_font_size: title_mods += f"{{fontsize{title_font_size}}}"
        if title_shadow: title_mods += f"{{shadow{title_shadow}}}"
        if title_kerning: title_mods += f"{{kerning{title_kerning}}}"
        if title_left: title_mods += f"{{left{title_left}}}"
        if title_up: title_mods += f"{{up{title_up}}}"
        if title_mods:
            title = f"{title_mods}{title}"
            
        # Apply Type Mods
        type_mods = ""
        if type_font_size: type_mods += f"{{fontsize{type_font_size}}}"
        if type_shadow: type_mods += f"{{shadow{type_shadow}}}"
        if type_kerning: type_mods += f"{{kerning{type_kerning}}}"
        if type_left: type_mods += f"{{left{type_left}}}"
        if type_mods:
            type_line = f"{type_mods}{type_line}"
        
        oracle_text = data.get('oracle_text', '')
        flavor_text = data.get('flavor_text', '')
        
        # --- Land Rules Text Handling (Large Symbols) ---
        is_basic_land = 'Basic' in type_line and 'Land' in type_line
        is_land = 'Land' in type_line
        produced_mana = data.get('produced_mana', [])
        colored_mana_produced = [m for m in produced_mana if m in 'WUBRG']
        
        full_text = ""
        is_big_symbol_land = False
        
        if is_basic_land:
            # Basic Land Logic (Large Symbols)
            mana_symbol = ''
            card_name_upper = card_name.upper()
            if 'PLAINS' in card_name_upper: mana_symbol = '{w}'
            elif 'ISLAND' in card_name_upper: mana_symbol = '{u}'
            elif 'SWAMP' in card_name_upper: mana_symbol = '{b}'
            elif 'MOUNTAIN' in card_name_upper: mana_symbol = '{r}'
            elif 'FOREST' in card_name_upper: mana_symbol = '{g}'
            
            if mana_symbol:
                full_text = f"{{down80}}{{fontsize64pt}}{{center}}{mana_symbol}"
                is_big_symbol_land = True
            else:
                full_text = self._format_text(oracle_text, is_basic_land=True)
        elif is_land and len(colored_mana_produced) == 2:
            # Dual Land Logic (Large Symbols + Preservation of conditional text)
            # Sort colors to WUBRG order for consistency
            color_order = {'W': 0, 'U': 1, 'B': 2, 'R': 3, 'G': 4}
            colored_mana_produced.sort(key=lambda x: color_order.get(x, 99))
            symbols = " ".join([f"{{{c.upper()}}}" for c in colored_mana_produced])
            
            # Split oracle text into lines
            lines = [line.strip() for line in oracle_text.split('\n') if line.strip()]
            first_line = lines[0] if lines else ""
            
            # Pattern 1: Standard mana reminder on line 1 (Dual/Shock/Cycle)
            # Example: ({T}: Add {G} or {U}.)
            standard_match = re.match(r'^\({T}: Add \{[A-Z]\} or \{[A-Z]\}\.\)$', first_line)
            
            # Pattern 2: Pain land (Detect colorless and colored mana abilities)
            # Scryfall usually has Colorless on L1 and Colored + Damage on L2
            is_pain_land = False
            colorless_line = ""
            colored_line = ""
            other_lines = []
            
            for line in lines:
                if "{T}: Add {C}" in line:
                    colorless_line = line
                elif re.search(r'\{T\}: Add \{[A-Z]\} or \{[A-Z]\}\.', line):
                    colored_line = line
                else:
                    other_lines.append(line)
            
            if colorless_line and colored_line:
                is_pain_land = True

            if standard_match:
                is_big_symbol_land = True
                if len(lines) > 1:
                    # Multi-line (Shock/Cycle): 52pt symbols + 12pt remaining text
                    remaining_text = "\n".join(lines[1:])
                    formatted_remaining = self._format_text(remaining_text)
                    # Use {fontsize32pt}\n spacer to control gap between symbols and text
                    full_text = f"{{fontsize52pt}}{{center}}{symbols}{{fontsize32pt}}\n{{fontsize12pt}}{formatted_remaining}"
                    print(f"   [Dual Land] Applied split symbols (52pt) and text (12pt): {symbols}")
                else:
                    # Single-line (Bayou): 64pt symbols
                    full_text = f"{{down80}}{{fontsize64pt}}{{center}}{symbols}"
                    print(f"   [Dual Land] Applied large symbols (64pt): {symbols}")
            elif is_pain_land:
                is_big_symbol_land = True
                # Pain land special handling: Symbols -> Damage/Extra Text -> Colorless
                # Remove the colored mana ability from the colored line to get just the damage/extra text
                damage_part = re.sub(r'\{T\}: Add \{[A-Z]\} or \{[A-Z]\}\.\s*', '', colored_line)
                
                # Ensure card name is replaced with "This land" in damage part
                if damage_part and card_name in damage_part:
                    damage_part = damage_part.replace(card_name, "This land")
                
                remaining_parts = []
                if damage_part:
                    remaining_parts.append(damage_part)
                if colorless_line:
                    remaining_parts.append(colorless_line)
                remaining_parts.extend(other_lines)
                
                # Format each part and join with newline + font size reset for each line
                formatted_parts = [self._format_text(p) for p in remaining_parts]
                remaining_text = "\n{fontsize12pt}".join(formatted_parts)
                
                full_text = f"{{fontsize52pt}}{{center}}{symbols}{{fontsize32pt}}\n{{fontsize12pt}}{remaining_text}"
                print(f"   [Pain Land] Applied split symbols (52pt) and reordered text: {symbols}")
            else:
                # Fallback to regular formatting if no special land pattern matches
                full_text = self._format_text(oracle_text)
        else:
            full_text = self._format_text(oracle_text, is_basic_land=('Land' in type_line))

        if flavor_text and not is_big_symbol_land:
            formatted_flavor = self._format_text(flavor_text, is_flavor=True)
            flavor_mods = ""
            if flavor_font_size: flavor_mods += f"{{fontsize{flavor_font_size}}}"
            full_text += f"{{flavor}}{flavor_mods}{formatted_flavor}"
            
        # Mana Cost
        mana_cost = data.get('mana_cost', '')
        
        # P/T
        pt = ""
        if 'power' in data and 'toughness' in data:
            pt = f"{data['power']}/{data['toughness']}"
            
            # Apply P/T Mods
            pt_mods = ""
            if pt_bold: pt_mods += "{bold}"
            if pt_font_size: pt_mods += f"{{fontsize{pt_font_size}}}"
            if pt_shadow: pt_mods += f"{{shadow{pt_shadow}}}"
            if pt_kerning: pt_mods += f"{{kerning{pt_kerning}}}"
            if pt_up: pt_mods += f"{{up{pt_up}}}"
            if pt_left: pt_mods += f"{{left{pt_left}}}"
            
            if pt_mods:
                pt = f"{pt_mods}{pt}"
                if pt_bold: pt += "{/bold}"
            
        # 6. Construct JSON
        card_json = {
            "key": f"{data['name']} ({data['set'].upper()} #{data['collector_number']})",
            "data": {
                "width": 2010,
                "height": 2814,
                "marginX": 0,
                "marginY": 0,
                "frames": frames,
                "artSource": final_art_url,
                "artX": 0.116,
                "artY": 0.099,
                "artZoom": 0.67,
                "setSymbolSource": set_symbol_url,
                "setSymbolX": 0.852,
                "setSymbolY": 0.555,
                "setSymbolZoom": 0.132,
                "artRotate": 0,
                "watermarkSource": "",
                "watermarkX": 0.5,
                "watermarkY": 0.76,
                "watermarkZoom": 1,
                "watermarkOpacity": 0.15,
                "watermarkLeft": 0,
                "watermarkRight": 0,
                "margins": False,
                "onload": None,
                "hideBottomInfoBorder": False,
                "showsFlavorBar": False,
                "bottomInfoTranslate": {"x": 0, "y": 0},
                "bottomInfoRotate": 0,
                "bottomInfoZoom": 1,
                "bottomInfoColor": "white",
                "manaSymbols": [],
                "version": "seventh",
                "text": {
                    "mana": {
                        "name": "Mana Cost",
                        "text": mana_cost,
                        "x": 0.1067, "y": 0.0539, "width": 0.8174, "height": 0.034,
                        "oneLine": True, "size": 0.044, "align": "right",
                        "manaCost": True
                    },
                    "title": {
                        "name": "Title",
                        "text": title,
                        "x": 0.1134, "y": 0.0481, "width": 0.7734, "height": 0.041,
                        "oneLine": True, "font": "goudymedieval", "size": 0.041,
                        "color": "white", "shadowX": 0.002, "shadowY": 0.0015, "align": "left"
                    },
                    "type": {
                        "name": "Type",
                        "text": type_line,
                        "x": 0.1074, "y": 0.5486, "width": 0.7852, "height": 0.0543,
                        "oneLine": True, "size": 0.032,
                        "color": "white", "shadowX": 0.002, "shadowY": 0.0015, "align": "left"
                    },
                    "rules": {
                        "name": "Rules Text",
                        "text": full_text,
                        "x": 0.128, "y": 0.6112, "width": 0.744, "height": 0.2633,
                        "size": 0.0358, "align": "left"
                    },
                    "pt": {
                        "name": "Power/Toughness",
                        "text": pt,
                        "x": 0.8074, "y": 0.9043, "width": 0.1367, "height": 0.0429,
                        "size": 0.0429, "oneLine": True, "align": "center",
                        "color": "white", "shadowX": 0.002, "shadowY": 0.0015
                    }
                },
                "bottomInfo": {
                    "top": {
                        "text": "Illus. {elemidinfo-artist}",
                        "x": 0.1, "y": 0.9085714285714286, "width": 0.8, "height": 0.0267,
                        "oneLine": True, "size": 0.0267, "align": "center",
                        "shadowX": 0.0021, "shadowY": 0.0015, "color": "white"
                    },
                    "wizards": {
                        "name": "wizards",
                        "text": "™ & © {elemidinfo-year} Wizards of the Coast, Inc. {elemidinfo-number}",
                        "x": 0.1, "y": 0.9204761904761904, "width": 0.8, "height": 0.0172,
                        "oneLine": True, "size": 0.0172, "align": "center",
                        "shadowX": 0.0014, "shadowY": 0.001, "color": "white"
                    },
                    "bottom": {
                        "text": "NOT FOR SALE   CardConjurer.com",
                        "x": 0.1, "y": 0.9395238095238095, "width": 0.8, "height": 0.012380952380952381,
                        "oneLine": True, "size": 0.012380952380952381,
                        "align": "center",
                        "shadowX": 0.0014, "shadowY": 0.001, "color": "white"
                    }
                },
                "infoYear": data.get('released_at', '')[:4],
                "infoNumber": data['collector_number'],
                "infoRarity": rarity_code.upper(),
                "infoSet": data['set'].upper(),
                "infoLanguage": "EN",
                "infoArtist": data.get('artist', ''),
                "infoNote": "",
                "artBounds": {"x": 0.12, "y": 0.0991, "width": 0.7667, "height": 0.4429},
                "setSymbolBounds": {
                    "x": 0.9, "y": 0.5739, "width": 0.12, "height": 0.0372,
                    "vertical": "center", "horizontal": "right"
                },
                "watermarkBounds": {"x": 0.18, "y": 0.64, "width": 0.64, "height": 0.24}
            }
        }
        
        # Apply Autofit if dimensions available
        if art_width and art_height:
            from automator_utils import autofit_art_position
            
            autofit_result = autofit_art_position(art_width, art_height, card_json['data'])
            if autofit_result:
                card_json['data']['artX'] = autofit_result['artX']
                card_json['data']['artY'] = autofit_result['artY']
                card_json['data']['artZoom'] = autofit_result['artZoom']
                card_json['data']['artRotate'] = autofit_result['artRotate']
                print(f"   Art Autofit applied: X={autofit_result['artX']:.4f}, Y={autofit_result['artY']:.4f}, Zoom={autofit_result['artZoom']:.4f}")
        
        # Apply set symbol autofit
        from automator_utils import autofit_set_symbol
        
        set_symbol_result = autofit_set_symbol(set_symbol_url, card_json['data'], self.image_server_url)
        if set_symbol_result:
            card_json['data']['setSymbolX'] = set_symbol_result['setSymbolX']
            card_json['data']['setSymbolY'] = set_symbol_result['setSymbolY']
            card_json['data']['setSymbolZoom'] = set_symbol_result['setSymbolZoom']
            print(f"   Set symbol autofit: X={set_symbol_result['setSymbolX']:.4f}, Y={set_symbol_result['setSymbolY']:.4f}, Zoom={set_symbol_result['setSymbolZoom']:.4f}")
        else:
            display_url = set_symbol_url if len(set_symbol_url) < 100 else set_symbol_url[:97] + "..."
            print(f"   Warning: Set symbol autofit failed for {display_url}. Using defaults.", file=sys.stderr)
            
        return card_json

if __name__ == "__main__":
    generator = SeventhGenerator()
    # Test with one card
    card = generator.generate_card("Banishing Light", "BLB", "1")
    if card:
        print(json.dumps(card, indent=2))

