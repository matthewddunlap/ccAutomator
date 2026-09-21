
import json
import os
import re
import sys
import math

from automator_utils import autofit_title, autofit_type, apply_text_tags

# Basic land types
BASIC_LANDS = ['Plains', 'Island', 'Swamp', 'Mountain', 'Forest', 'Wastes']

class CcFileEditor:
    """
    Edits an existing .cardconjurer project file (JSON) by modifying text fields
    based on provided parameters.
    """
    def __init__(self, filepath):
        self.filepath = filepath
        self.data = None
        self.load()

    def load(self):
        try:
            with open(self.filepath, 'r', encoding='utf-8') as f:
                self.data = json.load(f)
        except FileNotFoundError:
            print(f"Error: File not found at '{self.filepath}'", file=sys.stderr)
            sys.exit(1)
        except json.JSONDecodeError:
            print(f"Error: Failed to decode JSON from '{self.filepath}'", file=sys.stderr)
            sys.exit(1)

    def save(self, output_path):
        try:
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, indent=2)
            print(f"Saved edited project file to '{output_path}'")
        except Exception as e:
            print(f"Error saving file to '{output_path}': {e}", file=sys.stderr)
    
    def is_basic_land(self, card_name):
        """
        Check if a card is a basic land by name.
        Strips formatting tags before checking.
        """
        clean_name = re.sub(r'\{[^}]+\}', '', card_name).strip()
        return clean_name in BASIC_LANDS

    def apply_edits(self, white_border=False, black_border=False,
                    pt_font_size=None, pt_kerning=None, pt_up=None, pt_left=None, pt_bold=False, pt_shadow=None,
                    title_font_size=None, title_shadow=None, title_kerning=None, title_left=None, title_up=None,
                    type_font_size=None, type_shadow=None, type_kerning=None, type_left=None,
                    flavor_font=None, rules_down=None, auto_fit_type=False, auto_fit_title=False):
        """
        Applies the specified edits to all cards in the project.
        """
        if not self.data:
            return

        # Assuming self.data is now the root object, and cards are under a 'cards' key
        # If self.data is still a list of cards, this needs adjustment.
        cards = self.data.get('cards', []) if isinstance(self.data, dict) else self.data
        if not isinstance(cards, list):
            print("Error: JSON root is not a list of cards or does not contain a 'cards' key with a list. Expected a list of card objects.", file=sys.stderr)
            return

        print(f"Applied edits to {len(cards)} cards.")
        
        count = 0
        for card in cards:
            data = card.get('data', {})
            text_dict = data.get('text', {})
            frames_list = data.get('frames', [])
            
            # Try to get a card name for logging
            card_name = "Unknown Card"
            if 'title' in text_dict:
                card_name = text_dict['title'].get('text', 'Unknown Card')
            
            # Clean up card name (remove tags) for cleaner logging
            clean_card_name = re.sub(r'\{[^}]+\}', '', card_name)
            
            # --- Border Edits ---
            if white_border:
                # Check if already has white border (heuristic: check first frame name)
                if not (frames_list and frames_list[0].get('name') == 'White Border'):
                    # Construct White Border Frame Object
                    white_border_frame = {
                        "name": "White Border",
                        "src": "/img/frames/white.png",
                        "masks": [
                            {
                                "src": "/img/frames/seventh/regular/border.svg",
                                "name": "Border"
                            }
                        ],
                        "noDefaultMask": True
                    }
                    frames_list.insert(0, white_border_frame)
                    print(f"   [{clean_card_name}] Applied White Border.")
            
            elif black_border:
                # Remove white border if present
                if frames_list and frames_list[0].get('name') == 'White Border':
                    frames_list.pop(0)
                    print(f"   [{clean_card_name}] Removed White Border (Reverted to Black).")

            # --- Title Edits ---
            if 'title' in text_dict:
                t_obj = text_dict['title']
                original_text = t_obj.get('text', '')
                new_text = original_text

                # --- Title Auto-Fit: compute this card's effective values ---
                k0 = title_kerning if title_kerning is not None else 0
                f0 = title_font_size if title_font_size is not None else 0
                new_k, new_f = k0, f0
                if auto_fit_title:
                    clean_name = re.sub(r'\{[^}]+\}', '', original_text).strip()
                    mana_cost = text_dict.get('mana', {}).get('text', '') if 'mana' in text_dict else ''
                    new_k, new_f = autofit_title(clean_name, mana_cost, k0, f0,
                                                 title_left if title_left else 0)

                # Write a tag when the user specified one, or when auto-fit
                # changed the value (so we never emit a no-op {kerning0}/{fontsize0}).
                if title_kerning is not None or new_k != k0:
                    new_text = self._update_tag(new_text, 'kerning', new_k)
                if title_font_size is not None or new_f != f0:
                    new_text = self._update_tag(new_text, 'fontsize', new_f)
                if title_shadow is not None:
                    new_text = self._update_tag(new_text, 'shadow', title_shadow)
                if title_left is not None:
                    new_text = self._update_tag(new_text, 'left', title_left)
                if title_up is not None:
                    new_text = self._update_tag(new_text, 'up', title_up)
                
                if new_text != original_text:
                    t_obj['text'] = new_text
                    print(f"   [{clean_card_name}] Updated Title: '{original_text}' -> '{new_text}'")

            # --- Type Edits ---
            if 'type' in text_dict:
                t_obj = text_dict['type']
                original_text = t_obj.get('text', '')
                new_text = original_text

                # --- Auto-Fit Type: compute this card's effective values ---
                # Reserve room for the set symbol that sits on the right of the
                # row (when this card carries one), so a long type line never
                # runs into it.
                has_set_symbol = bool(data.get('setSymbolSource'))
                # If the card carries a symbol, reserve room starting from its
                # actual left edge (varies per set/zoom) instead of the constant.
                set_symbol_left = estimate_set_symbol_left(
                    data.get('setSymbolX'), data.get('setSymbolZoom')) if has_set_symbol else None
                k0 = type_kerning if type_kerning is not None else 0
                f0 = type_font_size if type_font_size is not None else 0
                new_k, new_f = k0, f0
                if auto_fit_type:
                    clean_text = re.sub(r'\{[^}]+\}', '', original_text).strip()
                    new_k, new_f = autofit_type(
                        clean_text, k0, f0,
                        type_left if type_left else 0,
                        has_set_symbol=has_set_symbol,
                        set_symbol_left=set_symbol_left)

                # Write a tag when the user specified one, or when auto-fit
                # changed the value (so we never emit a no-op {kerning0}/{fontsize0}).
                if type_kerning is not None or new_k != k0:
                    new_text = self._update_tag(new_text, 'kerning', new_k)
                if type_font_size is not None or new_f != f0:
                    new_text = self._update_tag(new_text, 'fontsize', new_f)
                if type_shadow is not None:
                    new_text = self._update_tag(new_text, 'shadow', type_shadow)
                if type_left is not None:
                    new_text = self._update_tag(new_text, 'left', type_left)

                if new_text != original_text:
                    t_obj['text'] = new_text
                    print(f"   [{clean_card_name}] Updated Type Line: '{original_text}' -> '{new_text}'")

            # --- PT Edits ---
            if 'pt' in text_dict:
                t_obj = text_dict['pt']
                original_text = t_obj.get('text', '')
                new_text = original_text
                
                if pt_kerning is not None:
                    new_text = self._update_tag(new_text, 'kerning', pt_kerning)
                if pt_font_size is not None:
                    new_text = self._update_tag(new_text, 'fontsize', pt_font_size)
                if pt_shadow is not None:
                    new_text = self._update_tag(new_text, 'shadow', pt_shadow)
                if pt_up is not None:
                    new_text = self._update_tag(new_text, 'up', pt_up)
                if pt_left is not None:
                    new_text = self._update_tag(new_text, 'left', pt_left)
                if pt_bold:
                    if '{bold}' not in new_text:
                        new_text = f"{{bold}}{new_text}{{/bold}}"
                
                if new_text != original_text:
                    t_obj['text'] = new_text
                    print(f"   [{clean_card_name}] Updated Power/Toughness: '{original_text}' -> '{new_text}'")

            # --- Rules/Flavor Edits ---
            if 'rules' in text_dict:
                # Check if this is a basic land - skip rules modifications if so
                if self.is_basic_land(card_name):
                    print(f"   [{clean_card_name}] Skipping rules modifications for basic land")
                else:
                    t_obj = text_dict['rules']
                    original_text = t_obj.get('text', '')
                    new_text = original_text
                    
                    # Rules Down (Global for rules text)
                    if rules_down is not None:
                        new_text = self._update_tag(new_text, 'down', rules_down)
                    
                    # Flavor Font
                    if flavor_font is not None and '{flavor}' in new_text:
                        parts = new_text.split('{flavor}', 1)
                        if len(parts) == 2:
                            pre_flavor = parts[0]
                            flavor_text = parts[1]
                            flavor_text = self._update_tag(flavor_text, 'fontsize', flavor_font)
                            new_text = f"{pre_flavor}{{flavor}}{flavor_text}"
                    
                    if new_text != original_text:
                        t_obj['text'] = new_text
                        print(f"   [{clean_card_name}] Updated Rules/Flavor Text: '{original_text}' -> '{new_text}'")
            
            count += 1
            
        print(f"Applied edits to {count} cards.")

    def _update_tag(self, text, tag_name, value):
        """
        Updates or inserts a tag in the text.
        Example: tag_name='kerning', value=2 -> updates {kerningX} to {kerning2} or prepends {kerning2}.

        Delegates to the shared apply_text_tags helper so this JSON path and
        the live Selenium path apply tags identically (replace in place,
        converge duplicates, decimal-aware values).
        """
        return apply_text_tags(text, **{tag_name: value})
