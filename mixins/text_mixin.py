import time
import sys
import re
import math
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

class TextMixin:
    def _apply_flavor_font_mod(self):
        """
        Specifically handles inserting a font size tag after a {flavor} tag
        in the 'Rules' text box.
        """
        if self.flavor_font is None:
            return

        print("   Checking for flavor text font modification...")
        try:
            self.text_tab.click()
            
            field_button_selector = "//h4[text()='Rules Text']"
            text_editor_id = "text-editor"

            field_button = self.wait.until(EC.element_to_be_clickable((By.XPATH, field_button_selector)))
            field_button.click()
            
            time.sleep(0.5)

            text_input = self.wait.until(EC.presence_of_element_located((By.ID, text_editor_id)))
            current_text = text_input.get_attribute('value')

            # Only proceed if the {flavor} tag exists
            if '{flavor}' in current_text:
                font_tag = f"{{fontsize{self.flavor_font}}}"
                # Replace the first occurrence of {flavor} with itself plus the new tag
                new_text = current_text.replace('{flavor}', f'{{flavor}}{font_tag}', 1)

                self.driver.execute_script("arguments[0].value = arguments[1];", text_input, new_text)
                self.driver.execute_script("arguments[0].dispatchEvent(new Event('input'))", text_input)
                print(f"      Found {{flavor}} tag. Injected font size tag.")
                
                time.sleep(self.render_delay)
            else:
                print("      No {flavor} tag found. Skipping.")

        except Exception as e:
            print(f"      An error occurred while applying flavor text mods: {e}", file=sys.stderr)

    def _apply_text_mods(self, field_name, font_size=None, shadow=None, kerning=None, left=None, bold=False, up=None, down=None):
        """
        Generic method to apply modifications to a specific text field (e.g., Title, Type).
        """
        # If no modifications are specified for this field, do nothing.
        if all(arg is None for arg in [font_size, shadow, kerning, left, up, down]) and not bold:
            return

        print(f"   Applying text modifications to '{field_name}'...")
        try:
            self.text_tab.click()
            
            field_button_selector = f"//h4[text()='{field_name}']"
            text_editor_id = "text-editor"

            field_button = self.wait.until(EC.element_to_be_clickable((By.XPATH, field_button_selector)))
            field_button.click()
            
            # Brief pause to let the textarea populate
            time.sleep(0.5)

            text_input = self.wait.until(EC.presence_of_element_located((By.ID, text_editor_id)))
            current_text = text_input.get_attribute('value')

            # Build the prefix tags
            tags = []
            if font_size is not None: tags.append(f"{{fontsize{font_size}}}")
            if shadow is not None: tags.append(f"{{shadow{shadow}}}")
            if kerning is not None: tags.append(f"{{kerning{kerning}}}")
            if left is not None: tags.append(f"{{left{left}}}")
            if up is not None: tags.append(f"{{up{up}}}")
            if down is not None: tags.append(f"{{down{down}}}")
            if bold: tags.append("{bold}")
            
            prefix = "".join(tags)
            suffix = "{/bold}" if bold else ""

            if current_text and current_text.strip():
                new_text = f"{prefix}{current_text}{suffix}"
                
                self.driver.execute_script("arguments[0].value = arguments[1];", text_input, new_text)
                self.driver.execute_script("arguments[0].dispatchEvent(new Event('input'))", text_input)
                print(f"      '{field_name}' changed from '{current_text}' to '{new_text}'.")

            # Wait for the change to render on a canvas
            time.sleep(self.render_delay)

        except Exception as e:
            print(f"      An error occurred while applying mods to '{field_name}': {e}", file=sys.stderr)

    def _set_rules_text(self, new_text: str):
        """
        Sets the 'Rules Text' to the provided new_text.
        """
        print(f"   Setting Rules Text to: '{new_text}'")
        try:
            self.text_tab.click()
            
            field_button_selector = "//h4[text()='Rules Text']"
            text_editor_id = "text-editor"

            field_button = self.wait.until(EC.element_to_be_clickable((By.XPATH, field_button_selector)))
            field_button.click()
            
            time.sleep(0.5)

            text_input = self.wait.until(EC.presence_of_element_located((By.ID, text_editor_id)))
            
            self.driver.execute_script("arguments[0].value = arguments[1];", text_input, new_text)
            self.driver.execute_script("arguments[0].dispatchEvent(new Event('input'))", text_input)
            
            time.sleep(self.render_delay)
        except Exception as e:
            print(f"      An error occurred while setting Rules Text: {e}", file=sys.stderr)

    DEFAULT_RULES_BOUNDS_Y = 1707
    DEFAULT_RULES_BOUNDS_HEIGHT = 767

    def apply_rules_text_bounds_mods(self):
        """
        Modifies the Y position and height of the rules text box by opening the
        'Edit Bounds' dialog and adjusting the values.
        Uses default constants to ensure idempotency (avoids cumulative updates).
        """
        if self.rules_bounds_y is None and self.rules_bounds_height is None:
            print("   [Debug] Skipping rules bounds mods: both Y and Height are None.")
            return

        print(f"   Applying rules text bounds modifications (Y delta={self.rules_bounds_y}, Height delta={self.rules_bounds_height})...")
        try:
            # 1. Navigate to the Text tab and select Rules Text
            self.text_tab.click()
            
            field_button_selector = "//h4[text()='Rules Text']"
            field_button = self.wait.until(EC.element_to_be_clickable((By.XPATH, field_button_selector)))
            field_button.click()
            
            time.sleep(0.5)

            # 2. Click the 'Edit Bounds' button.
            edit_bounds_button_selector = "//button[contains(text(), 'Edit Bounds')]"
            edit_bounds_button = self.wait.until(EC.element_to_be_clickable((By.XPATH, edit_bounds_button_selector)))
            edit_bounds_button.click()

            # 2. Wait for the textbox editor modal to appear.
            textbox_editor_selector = "div#textbox-editor.opened"
            self.wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, textbox_editor_selector)))
            # print("      'Edit Bounds' dialog opened.")

            # 3. Modify the 'Y' value if provided.
            if self.rules_bounds_y is not None:
                y_input = self.driver.find_element(By.ID, 'textbox-editor-y')
                current_y = int(y_input.get_attribute('value') or 0)
                
                # Calculate target based on known default to ensure idempotency
                target_y = self.DEFAULT_RULES_BOUNDS_Y + self.rules_bounds_y
                
                if current_y == target_y:
                    print(f"      Rules Bounds Y already at target {target_y}. Skipping.")
                else:
                    # Use send_keys to ensure events are triggered and hit Enter
                    y_input.clear()
                    y_input.send_keys(str(target_y))
                    y_input.send_keys(Keys.RETURN)
                    print(f"      Adjusted Rules Bounds Y from {current_y} to {target_y} (delta: {self.rules_bounds_y}).")

            # 4. Modify the 'Height' value if provided.
            if self.rules_bounds_height is not None:
                height_input = self.driver.find_element(By.ID, 'textbox-editor-height')
                current_height = int(height_input.get_attribute('value') or 0)
                
                # Calculate target based on known default
                target_height = self.DEFAULT_RULES_BOUNDS_HEIGHT + self.rules_bounds_height
                
                if current_height == target_height:
                    print(f"      Rules Bounds Height already at target {target_height}. Skipping.")
                else:
                    # Use send_keys to ensure events are triggered and hit Enter
                    height_input.clear()
                    height_input.send_keys(str(target_height))
                    height_input.send_keys(Keys.RETURN)
                    print(f"      Adjusted Rules Bounds Height from {current_height} to {target_height} (delta: {self.rules_bounds_height}).")

            # Wait for a fraction of a second before closing
            time.sleep(0.5)

            # 5. Close the textbox editor.
            close_button_selector = "h2.textbox-editor-close"
            close_button = self.driver.find_element(By.CSS_SELECTOR, close_button_selector)
            close_button.click()
            print("      Closed 'Edit Bounds' dialog.")

            # 6. Wait for the changes to render.
            time.sleep(self.render_delay)

        except (TimeoutException, NoSuchElementException) as e:
            print(f"      An error occurred while modifying rules text bounds: {e}", file=sys.stderr)
        except Exception as e:
            print(f"      An unexpected error occurred in _apply_rules_text_bounds_mods: {e}", file=sys.stderr)

    def apply_hide_reminder_text(self):
        """
        Clicks the 'Hide reminder text' checkbox if the flag is enabled.
        """
        if not self.hide_reminder_text:
            print("   [Debug] Skipping hide reminder text: flag is False.")
            return

        print("   Applying hide reminder text setting...")
        try:
            # 1. Navigate to the Text tab and select Rules Text
            self.text_tab.click()
            
            field_button_selector = "//h4[text()='Rules Text']"
            field_button = self.wait.until(EC.element_to_be_clickable((By.XPATH, field_button_selector)))
            field_button.click()
            
            time.sleep(0.5)  # Wait for tab to fully load

            # 2. Find the checkbox
            checkbox = self.wait.until(EC.presence_of_element_located((By.ID, 'hide-reminder-text')))
            
            # 3. Check if it's already checked using JavaScript
            is_checked = self.driver.execute_script("return arguments[0].checked;", checkbox)
            
            # 4. Click if not already checked - use JavaScript since the checkbox is styled
            if not is_checked:
                # Use JavaScript to click and trigger the onchange event
                self.driver.execute_script("""
                    arguments[0].checked = true;
                    arguments[0].dispatchEvent(new Event('change'));
                """, checkbox)
                print("      'Hide reminder text' checkbox enabled.")
                
                # 5. Wait for rendering
                time.sleep(0.5)
            else:
                print("      'Hide reminder text' checkbox already enabled.")

        except (TimeoutException, NoSuchElementException) as e:
            print(f"      An error occurred while applying hide reminder text: {e}", file=sys.stderr)
        except Exception as e:
            print(f"      An unexpected error occurred in _apply_hide_reminder_text: {e}", file=sys.stderr)


    def _process_all_text_modifications(self):
        """
        Orchestrator for all text modifications to prevent race conditions.
        Returns True if a modified was successfully made.
        """
        print(f"   [Debug] Entering _process_all_text_modifications. auto_fit_type={getattr(self, 'auto_fit_type', 'MISSING')}")
        
        # --- UPDATED: Check for new parameters ---
        # --- UPDATED: Check for new parameters ---
        has_mods_to_apply = any([
            self.title_font_size, self.title_shadow, self.title_kerning, self.title_left, self.title_up,
            self.type_font_size, self.type_shadow, self.type_kerning, self.type_left,
            self.pt_font_size, self.pt_shadow, self.pt_kerning, self.pt_bold, self.pt_up,
            self.flavor_font, self.rules_down, getattr(self, 'auto_fit_type', False)
        ])
        if not has_mods_to_apply:
            return False

        self.text_tab.click()
        
        any_text_mod_made = False
        if self._apply_text_mods("Title", self.title_font_size, self.title_shadow, self.title_kerning, self.title_left, up=self.title_up): any_text_mod_made = True
        
        # --- Type Line Logic with Character Count Auto-Fit ---
        final_type_fs = self.type_font_size
        
        is_auto_fit = getattr(self, 'auto_fit_type', False)
        print(f"   [Debug] Auto-Fit Check: Enabled={is_auto_fit}")
        
        if is_auto_fit:
            try:
                # Navigate to Type line to measure text
                self.text_tab.click()
                field_button_selector = "//h4[text()='Type']"
                field_button = self.wait.until(EC.element_to_be_clickable((By.XPATH, field_button_selector)))
                field_button.click()
                time.sleep(0.5)
                
                text_input = self.wait.until(EC.presence_of_element_located((By.ID, "text-editor")))
                current_type_text = text_input.get_attribute('value')
                print(f"   [Debug] Read Type Text: '{current_type_text}'")
                
                if current_type_text:
                    # Strip existing tags to get raw character count
                    clean_text = re.sub(r'\{[^}]+\}', '', current_type_text)
                    char_count = len(clean_text)
                    
                    # Get current settings (default to 0 if None)
                    k = self.type_kerning if self.type_kerning is not None else 0
                    f = self.type_font_size if self.type_font_size is not None else 0
                    
                    # Calculate Threshold: 34 - k - floor(f * 0.3)
                    threshold = 34 - k - math.floor(f * 0.3)
                    
                    # Calculate Excess
                    excess = max(0, char_count - threshold)
                    
                    if excess > 0:
                        # Step 1: Reduce Kerning (down to min 1)
                        available_k_drop = max(0, k - 1)
                        k_drop = min(excess, available_k_drop)
                        
                        final_k = k - k_drop
                        remaining_excess = excess - k_drop
                        
                        # Step 2: Reduce Font Size
                        f_drop = math.ceil(remaining_excess * 2.5)
                        final_f = f - f_drop
                        
                        # Apply changes
                        if final_k != k:
                            self.type_kerning = final_k
                            print(f"   [Auto-Fit] Length {char_count} (Excess {excess}). Reduced Kerning from {k} to {final_k}.")
                            
                        if final_f != f:
                            final_type_fs = final_f
                            print(f"   [Auto-Fit] Length {char_count} (Excess {excess}). Reduced Font Size from {f} to {final_f}.")
                    else:
                        # We need to prepend this tag to the text.
                        # Since _apply_text_mods replaces the whole text, we can't easily prepend 
                        # without modifying _apply_text_mods or doing it manually here.
                        
                        # Actually, _apply_text_mods takes `font_size`.
                        # If we pass `remaining_boost` (e.g. -2) as `font_size`, 
                        # it will create `{fontsize-2}`.
                        # This works perfectly!
                        final_type_fs = remaining_boost
                        
            except Exception as e:
                print(f"      Error during Type Auto-Fit: {e}", file=sys.stderr)

        if self._apply_text_mods("Type", final_type_fs, self.type_shadow, self.type_kerning, self.type_left): any_text_mod_made = True
