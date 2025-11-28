
import json
import os
import sys
from scryfall_utils import ScryfallAPI
from mixins.image_mixin import ImageMixin

# Land type configuration
LAND_CONFIG = {
    'Plains': {'frame': 'W', 'symbol': 'W'},
    'Island': {'frame': 'U', 'symbol': 'U'},
    'Swamp': {'frame': 'B', 'symbol': 'b'},
    'Mountain': {'frame': 'R', 'symbol': 'R'},
    'Forest': {'frame': 'G', 'symbol': 'g'},
    'Wastes': {'frame': 'C', 'symbol': 'C'}
}

BASIC_LANDS = list(LAND_CONFIG.keys())

class LandImageProcessor(ImageMixin):
    """
    Helper class to use ImageMixin logic without a full CardConjurerAutomator instance.
    """
    def __init__(self, image_server_url, image_server_path, art_path, 
                 upscale_art, ilaria_url, upscaler_model, upscaler_factor, 
                 upload_path, upload_secret, download_dir):
        self.image_server_url = image_server_url
        self.image_server_path = image_server_path
        self.art_path = art_path
        self.upscale_art = upscale_art
        self.ilaria_url = ilaria_url
        self.upscaler_model = upscaler_model
        self.upscaler_factor = upscaler_factor
        self.upload_path = upload_path
        self.upload_secret = upload_secret
        self.download_dir = download_dir
        
        # Mock driver and wait since we won't use methods that need them
        self.driver = None
        self.wait = None
        self.app_url = None # Not needed for _prepare_art_asset

def generate_fullart_lands(land_types, template_path, output_path, image_server_url, 
                           include_sets=None, exclude_sets=None, set_selection='earliest',
                           scryfall_filter=None,
                           # Image processing args
                           image_server_path=None, art_path='/local_art/art/',
                           upscale_art=False, ilaria_url=None, upscaler_model='RealESRGAN_x2plus', upscaler_factor=4,
                           upload_path=None, upload_secret=None, download_dir='.',
                           white_border=False):
    """
    Generate full-art basic lands using template and Scryfall data.
    """
    print(f"Loading template from {template_path}...")
    with open(template_path, 'r') as f:
        templates = json.load(f)
    
    # Create a mapping of land type to template
    template_map = {}
    for card in templates:
        title = card['data']['text']['title']['text']
        if title in LAND_CONFIG:
            template_map[title] = card
    
    scryfall = ScryfallAPI()
    
    # Initialize image processor
    processor = LandImageProcessor(
        image_server_url=image_server_url,
        image_server_path=image_server_path,
        art_path=art_path,
        upscale_art=upscale_art,
        ilaria_url=ilaria_url,
        upscaler_model=upscaler_model,
        upscaler_factor=upscaler_factor,
        upload_path=upload_path,
        upload_secret=upload_secret,
        download_dir=download_dir
    )
    
    generated_cards = []
    
    for land_type in land_types:
        if land_type not in LAND_CONFIG:
            print(f"Warning: Unknown land type '{land_type}', skipping...")
            continue
        
        if land_type not in template_map:
            print(f"Warning: No template found for '{land_type}', skipping...")
            continue
        
        print(f"Searching for full-art {land_type}s...")
        
        # Build Scryfall query
        query_parts = [f'!"{land_type}"', 'type:land', 'type:basic', 'is:fullart', 'unique:prints']
        if scryfall_filter:
            query_parts.append(scryfall_filter)
        
        query = ' '.join(query_parts)
        cards = scryfall.search_cards(query)
        
        if not cards:
            print(f"No full-art {land_type}s found matching query: {query}")
            continue
        
        print(f"Found {len(cards)} prints for {land_type}.")
        
        # Apply set filtering
        if include_sets:
            include_lower = [s.lower() for s in include_sets]
            cards = [c for c in cards if c.get('set', '').lower() in include_lower]
            print(f"After include filter: {len(cards)} prints")
        
        if exclude_sets:
            exclude_lower = [s.lower() for s in exclude_sets]
            cards = [c for c in cards if c.get('set', '').lower() not in exclude_lower]
            print(f"After exclude filter: {len(cards)} prints")
        
        if not cards:
            print(f"No {land_type}s remaining after filtering")
            continue
        
        # Apply selection logic
        selected_cards = []
        if set_selection == 'all':
            selected_cards = cards
        elif set_selection == 'latest':
            # Sort by release date descending
            sorted_cards = sorted(cards, key=lambda c: c.get('released_at', ''), reverse=True)
            selected_cards = [sorted_cards[0]] if sorted_cards else []
        elif set_selection == 'earliest':
            # Sort by release date ascending
            sorted_cards = sorted(cards, key=lambda c: c.get('released_at', ''))
            selected_cards = [sorted_cards[0]] if sorted_cards else []
        elif set_selection == 'random':
            import random
            selected_cards = [random.choice(cards)] if cards else []
        
        print(f"Selected {len(selected_cards)} {land_type}(s) based on '{set_selection}' mode")
        
        # Generate cards from selected prints
        for card in selected_cards:
            # Clone template
            new_card = json.loads(json.dumps(template_map[land_type]))
            
            # Extract data
            set_code = card.get('set', 'unk').upper()
            collector_number = card.get('collector_number', '0')
            artist = card.get('artist', 'Unknown')
            
            # Process Art Asset (Download -> Upload -> Upscale -> Upload)
            print(f"Processing art for {land_type} ({set_code} #{collector_number})...")
            final_art_url, _, art_width, art_height = processor._prepare_art_asset(
                card_name=land_type,
                set_code=set_code,
                collector_number=collector_number,
                scryfall_data=card
            )
            
            if not final_art_url:
                print(f"Warning: Failed to prepare art for {land_type} ({set_code} #{collector_number}). Using fallback.")
                if 'image_uris' in card and 'art_crop' in card['image_uris']:
                    final_art_url = card['image_uris']['art_crop']
                else:
                    final_art_url = ""

            # Update Card Data
            new_card['key'] = f"{land_type} ({set_code} #{collector_number})"
            new_card['data']['artSource'] = final_art_url
            
            # --- Python-based Autofit Logic ---
            # Logic translated from Card Conjurer JS:
            # function autoFitArt() {
            #     document.querySelector('#art-rotate').value = 0;
            #     if (art.width / art.height > scaleWidth(card.artBounds.width) / scaleHeight(card.artBounds.height)) {
            #         document.querySelector('#art-y').value = Math.round(scaleY(card.artBounds.y) - scaleHeight(card.marginY));
            #         document.querySelector('#art-zoom').value = (scaleHeight(card.artBounds.height) / art.height * 100).toFixed(1);
            #         document.querySelector('#art-x').value = Math.round(scaleX(card.artBounds.x) - (document.querySelector('#art-zoom').value / 100 * art.width - scaleWidth(card.artBounds.width)) / 2 - scaleWidth(card.marginX));
            #     } else {
            #         document.querySelector('#art-x').value = Math.round(scaleX(card.artBounds.x) - scaleWidth(card.marginX));
            #         document.querySelector('#art-zoom').value = (scaleWidth(card.artBounds.width) / art.width * 100).toFixed(1);
            #         document.querySelector('#art-y').value = Math.round(scaleY(card.artBounds.y) - (document.querySelector('#art-zoom').value / 100 * art.height - scaleHeight(card.artBounds.height)) / 2 - scaleHeight(card.marginY));
            #     }
            # }
            
            if art_width and art_height and 'artBounds' in new_card['data']:
                try:
                    # Card dimensions from template
                    card_width = new_card['data'].get('width', 1500) # Default if missing
                    card_height = new_card['data'].get('height', 2100)
                    
                    # Bounds (normalized 0-1)
                    bounds = new_card['data']['artBounds']
                    bounds_x = bounds.get('x', 0)
                    bounds_y = bounds.get('y', 0)
                    bounds_w = bounds.get('width', 1)
                    bounds_h = bounds.get('height', 1)
                    
                    # Margins (normalized?) - Usually 0 in templates, but let's check
                    # In JS scaleWidth(val) usually implies val * cardWidth if val is normalized.
                    # Assuming bounds are normalized.
                    
                    # Scale functions (assuming normalized inputs)
                    def scale_x(val): return val * card_width
                    def scale_y(val): return val * card_height
                    def scale_w(val): return val * card_width
                    def scale_h(val): return val * card_height
                    
                    margin_x = new_card['data'].get('marginX', 0)
                    margin_y = new_card['data'].get('marginY', 0)
                    
                    # Calculate aspect ratios
                    art_ratio = art_width / art_height
                    bounds_ratio = scale_w(bounds_w) / scale_h(bounds_h)
                    
                    new_zoom = 0
                    new_x = 0
                    new_y = 0
                    
                    if art_ratio > bounds_ratio:
                        # Art is wider than bounds -> Fit to Height
                        new_y = round(scale_y(bounds_y) - scale_h(margin_y))
                        new_zoom = (scale_h(bounds_h) / art_height) # Keep as float for calculation
                        
                        # Calculate X to center
                        # x = bounds_x - (scaled_art_width - bounds_width) / 2 - margin_x
                        scaled_art_width = new_zoom * art_width
                        new_x = round(scale_x(bounds_x) - (scaled_art_width - scale_w(bounds_w)) / 2 - scale_w(margin_x))
                    else:
                        # Art is taller/narrower -> Fit to Width
                        new_x = round(scale_x(bounds_x) - scale_w(margin_x))
                        new_zoom = (scale_w(bounds_w) / art_width)
                        
                        # Calculate Y to center
                        scaled_art_height = new_zoom * art_height
                        new_y = round(scale_y(bounds_y) - (scaled_art_height - scale_h(bounds_h)) / 2 - scale_h(margin_y))
                    
                    # Update card data
                    # Note: Card Conjurer JSON expects:
                    # artX, artY (pixels? or normalized? Template has 0.044... which is normalized)
                    # artZoom (percentage? Template has 2.928)
                    
                    # WAIT! The template values:
                    # "artX":0.044278606965174126
                    # "artY":0.09772565742714996
                    # "artZoom":2.928
                    
                    # If the template uses normalized values for artX/artY, then my calculation above (returning pixels) is wrong for the JSON.
                    # BUT the JS code sets document.querySelector('#art-x').value = Math.round(...)
                    # The UI inputs are usually in pixels.
                    # When saving, Card Conjurer converts these back to normalized values?
                    # Or does the JSON store what the UI inputs have?
                    
                    # Let's check the template again.
                    # "width": 2010, "height": 2814
                    # "artX": 0.044... -> 0.044 * 2010 = ~88 pixels.
                    # "artBounds.x": 0.116 -> 0.116 * 2010 = ~233 pixels.
                    
                    # If I put PIXELS into the JSON, will Card Conjurer understand it?
                    # The JSON usually stores values that the `load()` function can read.
                    # If I look at `dummy_test.cardconjurer`:
                    # "artX": 0.116...
                    
                    # It seems the JSON stores NORMALIZED values (0-1) for X/Y.
                    # But the JS logic calculates PIXELS for the UI inputs.
                    
                    # So I need to convert the calculated pixels back to normalized values.
                    # artX_normalized = new_x / card_width
                    # artY_normalized = new_y / card_height
                    
                    # And artZoom?
                    # JS: document.querySelector('#art-zoom').value = (scaleHeight(card.artBounds.height) / art.height * 100).toFixed(1);
                    # This sets the zoom INPUT (percentage).
                    # The JSON "artZoom" value: 2.928.
                    # If zoom input is 100%, artZoom in JSON is usually 1.0? Or is it related to the image size?
                    # Actually, `artZoom` in JSON is often the scale factor directly (e.g. 2.928 means 292.8%?).
                    # Let's assume JSON artZoom = new_zoom (factor, e.g. 0.5 for 50%).
                    # The JS sets the input to `... * 100`. So the input is percentage.
                    # So for JSON, I should use `new_zoom` (the raw factor).
                    
                    new_card['data']['artX'] = new_x / card_width
                    new_card['data']['artY'] = new_y / card_height
                    new_card['data']['artZoom'] = new_zoom
                    new_card['data']['artRotate'] = 0
                    
                    print(f"   Autofit applied: X={new_card['data']['artX']:.4f}, Y={new_card['data']['artY']:.4f}, Zoom={new_card['data']['artZoom']:.4f}")
                    
                except Exception as e:
                    print(f"   Warning: Python autofit failed: {e}")
            else:
                print("   Warning: Skipping autofit (missing dimensions or bounds)")
            # ---------------------------------------
            
            # Set symbol to blank image
            blank_url = f"{image_server_url.rstrip('/')}/img/blank.png"
            new_card['data']['setSymbolSource'] = blank_url
            new_card['data']['watermarkSource'] = blank_url
            
            # Update Info
            new_card['data']['infoSet'] = set_code
            new_card['data']['infoNumber'] = collector_number
            new_card['data']['infoArtist'] = artist
            new_card['data']['infoYear'] = card.get('released_at', '')[:4]
            
            # Apply White Border if requested
            if white_border:
                print(f"Applying white border to {new_card['key']}...")
                # Ensure image server URL doesn't have trailing slash for clean concatenation
                base_url = image_server_url.rstrip('/')
                white_border_frame = {
                    "name": "White Border",
                    "src": f"{base_url}/img/frames/white.png",
                    "masks": [
                        {
                            "src": f"{base_url}/img/frames/seventh/regular/border.svg",
                            "name": "Border"
                        }
                    ],
                    "noDefaultMask": True
                }
                # Insert at the BEGINNING of the frames list to draw on TOP
                # (Card Conjurer renders frames from Index 0 = Top to Index N = Bottom)
                new_card['data']['frames'].insert(0, white_border_frame)
            
            generated_cards.append(new_card)
            print(f"Generated: {new_card['key']}")
    
    if not generated_cards:
        print("Warning: No cards were generated!")
        return
    
    print(f"Saving {len(generated_cards)} cards to {output_path}...")
    with open(output_path, 'w') as f:
        json.dump(generated_cards, f, indent=2)
    print("Done.")
