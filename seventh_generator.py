import json
import os
import re
import sys
from unittest.mock import MagicMock
sys.modules['gradio_client'] = MagicMock()

import requests
from pathlib import Path
from automator_utils import generate_safe_filename

# Add parent directory to path to import mixins
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from mixins.image_mixin import ImageMixin
from mixins.collector_mixin import CollectorMixin

# Frame Mappings
COLOR_MAP = {
    'W': 'w', 'U': 'u', 'B': 'b', 'R': 'r', 'G': 'g',
    'M': 'm', 'A': 'a', 'L': 'l', 'C': 'c'
}

LAND_COLOR_MAP = {
    'W': 'wl', 'U': 'ul', 'B': 'bl', 'R': 'rl', 'G': 'gl'
}

class SeventhGenerator(ImageMixin, CollectorMixin):
    def __init__(self, image_server_url="http://mtgproxy:4242", download_dir="downloads", upload_secret=None):
        self.image_server_url = image_server_url
        self.download_dir = download_dir
        self.upload_secret = upload_secret
        self.driver = None # Not needed for generation
        self.upscale_art = True # Corrected name
        self.ilaria_url = None # Initialize ilaria_url
        self.upscaler_model = "realesrgan-x2plus"
        self.upscaler_factor = 4
        self.art_path = "art"
        
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

    def generate_card(self, card_name, set_code=None, collector_number=None):
        # ... (fetching data) ...
        # 1. Get Scryfall Data
        print(f"Fetching data for {card_name}...")
        query = f'!"{card_name}"'
        if set_code: query += f" set:{set_code}"
        if collector_number: query += f" cn:{collector_number}"
        
        try:
            resp = requests.get("https://api.scryfall.com/cards/search", params={'q': query})
            resp.raise_for_status()
            data = resp.json()['data'][0]
        except Exception as e:
            print(f"Error fetching {card_name}: {e}")
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
        set_symbol_url = f"{self.image_server_url}/img/setSymbols/official/{data['set']}-{rarity_code}.svg"
        
        # 5. Text Processing
        title = data['name']
        type_line = data['type_line']
        
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
            
        # 6. Construct JSON
        card_json = {
            "key": f"{data['name']} ({data['set'].upper()} #{data['collector_number']})",
            "data": {
                "width": 2010,
                "height": 2814,
                "frames": frames,
                "artSource": final_art_url,
                "artX": 0.116, # Default center-ish
                "artY": 0.099,
                "artZoom": 0.67,
                "setSymbolSource": set_symbol_url,
                "setSymbolX": 0.852,
                "setSymbolY": 0.555,
                "setSymbolZoom": 0.132,
                "text": {
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
                    },
                    "mana": {
                        "name": "Mana Cost",
                        "text": mana_cost,
                        "x": 0.1067, "y": 0.0539, "width": 0.8174, "height": 0.034,
                        "oneLine": True, "size": 0.044, "align": "right",
                        "manaCost": True
                    }
                },
                "infoYear": data.get('released_at', '')[:4],
                "infoNumber": data['collector_number'],
                "infoSet": data['set'].upper(),
                "infoArtist": data.get('artist', ''),
                # Autofit logic needed?
                "artBounds": {"x": 0.12, "y": 0.0991, "width": 0.7667, "height": 0.4429}
            }
        }
        
        # Apply Autofit if dimensions available
        if art_width and art_height:
            # Re-use autofit logic from land_generator
            # ... (Implement autofit here) ...
            pass
            
        return card_json

if __name__ == "__main__":
    generator = SeventhGenerator()
    # Test with one card
    card = generator.generate_card("Banishing Light", "BLB", "1")
    if card:
        print(json.dumps(card, indent=2))

