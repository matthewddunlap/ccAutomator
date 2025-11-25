
import json
import os
import re
import sys
import math

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

    def apply_edits(self, white_border=False, black_border=False,
                    pt_font_size=None, pt_kerning=None, pt_up=None, pt_bold=False, pt_shadow=None,
                    title_font_size=None, title_shadow=None, title_kerning=None, title_left=None, title_up=None,
                    type_font_size=None, type_shadow=None, type_kerning=None, type_left=None,
                    flavor_font=None, rules_down=None, auto_fit_type=False):
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
            
            elif black_border:
                # Remove white border if present
                if frames_list and frames_list[0].get('name') == 'White Border':
                    frames_list.pop(0)

            # --- Title Edits ---
            if 'title' in text_dict:
                t_obj = text_dict['title']
                original_text = t_obj.get('text', '')
                new_text = original_text
                
                if title_kerning is not None:
                    new_text = self._update_tag(new_text, 'kerning', title_kerning)
                if title_font_size is not None:
                    new_text = self._update_tag(new_text, 'fontsize', title_font_size)
                if title_shadow is not None:
                    new_text = self._update_tag(new_text, 'shadow', title_shadow)
                if title_left is not None:
                    new_text = self._update_tag(new_text, 'left', title_left)
                if title_up is not None:
                    new_text = self._update_tag(new_text, 'up', title_up)
                
                t_obj['text'] = new_text

            # --- Type Edits ---
            if 'type' in text_dict:
                t_obj = text_dict['type']
                original_text = t_obj.get('text', '')
                new_text = original_text
                
                # --- Auto-Fit Logic ---
                final_type_fs_tag = ""
                final_type_kerning_tag = ""
                
                if auto_fit_type:
                    # Strip existing tags to get raw character count
                    clean_text = re.sub(r'\{[^}]+\}', '', original_text)
                    char_count = len(clean_text)
                    
                    # Get current settings (default to 0 if None)
                    k = type_kerning if type_kerning is not None else 0
                    f = type_font_size if type_font_size is not None else 0
                    
                    # Calculate Threshold: 34 - k - floor(f * 0.3)
                    threshold = 34 - k - math.floor(f * 0.3)
                    
                    # Calculate Excess
                    excess = max(0, char_count - threshold)
                    
                    if excess > 0:
                        # Step 1: Reduce Kerning (down to min 1)
                        # We can drop kerning by at most (k - 1). If k <= 1, available drop is 0.
                        available_k_drop = max(0, k - 1)
                        k_drop = min(excess, available_k_drop)
                        
                        final_k = k - k_drop
                        remaining_excess = excess - k_drop
                        
                        # Step 2: Reduce Font Size
                        # Each remaining excess char costs 2.5 font points
                        f_drop = math.ceil(remaining_excess * 2.5)
                        final_f = f - f_drop
                        
                        # Prepare tags
                        # Only apply if different from original
                        if final_k != k:
                            final_type_kerning_tag = final_k
                            print(f"   [Auto-Fit] Length {char_count} (Excess {excess}). Reduced Kerning from {k} to {final_k}.")
                            
                        if final_f != f:
                            final_type_fs_tag = final_f
                            print(f"   [Auto-Fit] Length {char_count} (Excess {excess}). Reduced Font Size from {f} to {final_f}.")
                    else:
                        # No excess, no changes needed beyond standard args
                        pass

                # Apply Kerning
                # If auto-fit calculated a kerning, use it. Otherwise use the standard arg.
                effective_kerning = final_type_kerning_tag if (auto_fit_type and final_type_kerning_tag != "") else type_kerning
                
                if effective_kerning is not None:
                    new_text = self._update_tag(new_text, 'kerning', effective_kerning)
                
                # Apply Shadow
                if type_shadow is not None:
                    new_text = self._update_tag(new_text, 'shadow', type_shadow)
                
                # Apply Left
                if type_left is not None:
                    new_text = self._update_tag(new_text, 'left', type_left)

                # Apply Font Size
                # If auto-fit calculated a size, use it. Otherwise use the standard arg.
                effective_fs = final_type_fs_tag if (auto_fit_type and final_type_fs_tag != "") else type_font_size
                
                if effective_fs is not None:
                    new_text = self._update_tag(new_text, 'fontsize', effective_fs)
                
                t_obj['text'] = new_text

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
                if pt_bold:
                    if '{bold}' not in new_text:
                        new_text = f"{{bold}}{new_text}{{/bold}}"
                
                t_obj['text'] = new_text

            # --- Rules/Flavor Edits ---
            if 'rules' in text_dict:
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
                
                t_obj['text'] = new_text
            
            count += 1
            
        print(f"Applied edits to {count} cards.")

    def _update_tag(self, text, tag_name, value):
        """
        Updates or inserts a tag in the text.
        Example: tag_name='kerning', value=2 -> updates {kerningX} to {kerning2} or prepends {kerning2}.
        """
        # Pattern to match {tagnameNUMBER} or {tagname-NUMBER}
        # We assume tags are like {kerning5}, {fontsize30}, {down-10}
        pattern = fr'\{{{tag_name}-?\d+\}}'
        new_tag = f"{{{tag_name}{value}}}"
        
        if re.search(pattern, text):
            # Replace existing tag
            return re.sub(pattern, new_tag, text, count=1)
        else:
            # Prepend tag
            return f"{new_tag}{text}"
