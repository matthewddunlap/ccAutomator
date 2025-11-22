import json
import re
import sys

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

    def apply_edits(self, 
                    title_kerning=None, title_font_size=None, title_shadow=None, title_left=None,
                    type_kerning=None, type_font_size=None, type_shadow=None, type_left=None,
                    pt_kerning=None, pt_font_size=None, pt_shadow=None, pt_bold=False, pt_up=None,
                    flavor_font=None, rules_down=None,
                    white_border=False, black_border=False):
        
        if not isinstance(self.data, list):
            print("Error: JSON root is not a list. Expected a list of card objects.", file=sys.stderr)
            return

        count = 0
        for card in self.data:
            card_data = card.get('data', {})
            text_dict = card_data.get('text', {})
            frames_list = card_data.get('frames', [])
            
            # --- Border Edits ---
            if white_border:
                # Check if already has white border (heuristic: check first frame name)
                if not (frames_list and frames_list[0].get('name') == 'White Border'):
                    # Construct White Border Frame Object
                    # We assume the mask src is standard for 7th edition / regular as seen in the example.
                    # If this varies by frame, this might be brittle, but it matches the user's request based on the file.
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
                
                t_obj['text'] = new_text

            # --- Type Edits ---
            if 'type' in text_dict:
                t_obj = text_dict['type']
                original_text = t_obj.get('text', '')
                new_text = original_text
                
                if type_kerning is not None:
                    new_text = self._update_tag(new_text, 'kerning', type_kerning)
                if type_font_size is not None:
                    new_text = self._update_tag(new_text, 'fontsize', type_font_size)
                if type_shadow is not None:
                    new_text = self._update_tag(new_text, 'shadow', type_shadow)
                if type_left is not None:
                    new_text = self._update_tag(new_text, 'left', type_left)
                
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
                    # Check if wrapped in {bold}...{/bold}
                    # This is a bit simplistic, assuming the whole string should be bold if flag is set
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
                        # Update fontsize tag at the start of flavor text
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
