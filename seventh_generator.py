import json
import os
import re
import sys
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
        
    def determine_frame_layers(self, scryfall_data):
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
                
                layers.append((FRAME_NAMES['l'], 'regular/l.png', 'Pinline'))
                
                # Sample order: c2 (Right) then c1 (Full)
                # This seems counter-intuitive (Full covers Right), but matches the sample JSON.
                layers.append({
                    "name": FRAME_NAMES.get(code2, 'Land Frame'),
                    "src": f"/img/frames/seventh/regular/{code2}.png",
                    "masks": [
                        {"src": "/img/frames/seventh/regular/rules.svg", "name": "Rules"},
                        {"src": "/img/frames/maskRightHalf.png", "name": "Right Half"}
                    ]
                })
                
                layers.append((FRAME_NAMES.get(code1, 'Land Frame'), f'regular/{code1}.png', 'Rules'))
                
                layers.append((FRAME_NAMES['l'], 'regular/l.png', 'Frame'))
                layers.append((FRAME_NAMES['l'], 'regular/l.png', 'Textbox Pinline'))
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
            for mask in ['Pinline', 'Rules', 'Frame', 'Textbox Pinline', 'Border']:
                layers.append((FRAME_NAMES['a'], f'regular/a.png', mask))
                
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
        text = text.replace("'", "'")
        
        # Convert all newlines to {lns} (applies to both oracle and flavor text)
        text = text.replace('\n', '{lns}')
                
        return text

    def generate_card(self, card_name, section='deck', set_code=None, collector_number=None,
                     scryfall_filter=None, spells_include_set=None, spells_exclude_set=None,
                     basic_land_include_set=None, basic_land_exclude_set=None,
                     # Text modifications
                     title_font_size=None, title_shadow=None, title_kerning=None, title_left=None, title_up=None,
                     type_font_size=None, type_shadow=None, type_kerning=None, type_left=None,
                     pt_font_size=None, pt_shadow=None, pt_kerning=None, pt_up=None, pt_bold=False):
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
        frames = self.determine_frame_layers(data)
        
        # 4. Set Symbol
        rarity_map = {'common': 'c', 'uncommon': 'u', 'rare': 'r', 'mythic': 'm', 'special': 'r', 'bonus': 'm'}
        rarity_code = rarity_map.get(data['rarity'], 'c')
        set_symbol_url = f"/img/setSymbols/official/{data['set']}-{rarity_code}.svg"
        
        # 5. Text Processing
        title = data['name']
        type_line = data['type_line']
        
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
        
        # Apply formatting
        is_basic = 'Basic Land' in type_line
        
        full_text = self._format_text(oracle_text, is_basic_land=is_basic)
        if flavor_text:
            formatted_flavor = self._format_text(flavor_text, is_flavor=True)
            full_text += f"{{flavor}}{formatted_flavor}"
            
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
                print(f"   Autofit applied: X={autofit_result['artX']:.4f}, Y={autofit_result['artY']:.4f}, Zoom={autofit_result['artZoom']:.4f}")
        
        # Apply set symbol autofit
        from automator_utils import autofit_set_symbol
        
        set_symbol_result = autofit_set_symbol(set_symbol_url, card_json['data'], self.image_server_url)
        if set_symbol_result:
            card_json['data']['setSymbolX'] = set_symbol_result['setSymbolX']
            card_json['data']['setSymbolY'] = set_symbol_result['setSymbolY']
            card_json['data']['setSymbolZoom'] = set_symbol_result['setSymbolZoom']
            print(f"   Set symbol autofit: X={set_symbol_result['setSymbolX']:.4f}, Y={set_symbol_result['setSymbolY']:.4f}, Zoom={set_symbol_result['setSymbolZoom']:.4f}")
            
        return card_json

if __name__ == "__main__":
    generator = SeventhGenerator()
    # Test with one card
    card = generator.generate_card("Banishing Light", "BLB", "1")
    if card:
        print(json.dumps(card, indent=2))

