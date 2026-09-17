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
                self.driver.execute_script("arguments[0].dispatchEvent(new Event('change'))", text_input)
                # self.driver.execute_script("textEdited()")
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
        max_retries = 3
        for attempt in range(max_retries):
            try:
                # print(f"      [Debug] Attempt {attempt+1}: Clicking text tab...")
                # Re-find the tab to avoid stale element issues
                text_tab = self.wait.until(EC.element_to_be_clickable((By.XPATH, "//h3[text()='Text']")))
                text_tab.click()
                
                field_button_selector = f"//h4[text()='{field_name}']"
                text_editor_id = "text-editor"

                # print(f"      [Debug] Waiting for field button '{field_name}'...")
                # Use presence first, then scroll, then click. This is more robust than element_to_be_clickable alone.
                field_button = self.wait.until(EC.presence_of_element_located((By.XPATH, field_button_selector)))
                
                # Scroll into view to ensure it's clickable
                self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", field_button)
                time.sleep(0.2) # Small pause after scroll
                
                field_button.click()
                
                # Brief pause to let the textarea populate
                time.sleep(0.5)

                # print(f"      [Debug] Waiting for text editor...")
                # Use visibility instead of presence to ensure it's actually shown
                text_input = self.wait.until(EC.visibility_of_element_located((By.ID, text_editor_id)))
                current_text = text_input.get_attribute('value')
                # print(f"      [Debug] Current text: '{current_text}'")

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
                    # Check if already applied to avoid double application on retry
                    if prefix in current_text:
                         print(f"      '{field_name}' already has modifications. Skipping.")
                         return

                    new_text = f"{prefix}{current_text}{suffix}"
                    
                    # print(f"      [Debug] Executing JS to update text...")
                    self.driver.execute_script("arguments[0].value = arguments[1];", text_input, new_text)
                    self.driver.execute_script("arguments[0].dispatchEvent(new Event('input'))", text_input)
                    self.driver.execute_script("arguments[0].dispatchEvent(new Event('change'))", text_input)
                    # self.driver.execute_script("textEdited()")
                    print(f"      '{field_name}' changed from '{current_text}' to '{new_text}'.")

                # Wait for the change to render on a canvas
                time.sleep(self.render_delay)
                return # Success, exit loop

            except Exception as e:
                import traceback
                tb = traceback.format_exc()
                print(f"      Attempt {attempt+1}/{max_retries} failed for '{field_name}': {e}", file=sys.stderr)
                
                # DEBUG: List all available h4 elements to see what's actually there
                try:
                    h4s = self.driver.find_elements(By.XPATH, "//h4")
                    available_fields = [h.text for h in h4s]
                    print(f"      [Debug] Available text fields: {available_fields}", file=sys.stderr)
                except:
                    pass

                # print(f"      Traceback: {tb}", file=sys.stderr)
                if attempt == max_retries - 1:
                    print(f"      An error occurred while applying mods to '{field_name}' after {max_retries} attempts.", file=sys.stderr)
                time.sleep(1) # Wait before retrying

    def set_flavor_text(self, flavor_text: str):
        """
        Sets the flavor text in the Rules Text box. 
        Replaces existing flavor text if {flavor} is present, otherwise appends it.
        """
        if not flavor_text:
            return

        print(f"   Setting Flavor Text to: '{flavor_text[:50]}...'")
        try:
            self.text_tab.click()
            
            field_button_selector = "//h4[text()='Rules Text']"
            text_editor_id = "text-editor"

            field_button = self.wait.until(EC.element_to_be_clickable((By.XPATH, field_button_selector)))
            field_button.click()
            
            time.sleep(0.5)

            text_input = self.wait.until(EC.presence_of_element_located((By.ID, text_editor_id)))
            current_text = text_input.get_attribute('value') or ""

            # Check for existing {flavor} tag
            if '{flavor}' in current_text:
                # Keep everything before {flavor}, replace everything after
                base_text = current_text.split('{flavor}')[0]
                new_text = f"{base_text}{{flavor}}{flavor_text}"
            else:
                # Append {flavor} and new text
                separator = "\n" if current_text.strip() else ""
                new_text = f"{current_text.strip()}{separator}{{flavor}}{flavor_text}"

            self.driver.execute_script("arguments[0].value = arguments[1];", text_input, new_text)
            self.driver.execute_script("arguments[0].dispatchEvent(new Event('input'))", text_input)
            self.driver.execute_script("arguments[0].dispatchEvent(new Event('change'))", text_input)
            
            print("      Flavor text updated.")
            time.sleep(self.render_delay)

        except Exception as e:
            print(f"      An error occurred while setting Flavor Text: {e}", file=sys.stderr)

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
            self.driver.execute_script("arguments[0].dispatchEvent(new Event('change'))", text_input)
            # self.driver.execute_script("textEdited()")
            
            time.sleep(self.render_delay)
        except Exception as e:
            print(f"      An error occurred while setting Rules Text: {e}", file=sys.stderr)

    def apply_rules_text_bounds_mods(self):
        """
        Modifies the Y position, Height, X position, and Width of the rules text box
        by opening the 'Edit Bounds' dialog and adjusting the values relative to the
        current values found in the UI.
        
        Note: This applies a relative delta. If called multiple times without resetting
        the frame, the changes will be cumulative.
        """
        if self.rules_bounds_y is None and self.rules_bounds_height is None and self.rules_bounds_x is None and self.rules_bounds_width is None:
            print("   [Debug] Skipping rules bounds mods: all bounds args are None.")
            return

        print(f"   Applying rules text bounds modifications (Y delta={self.rules_bounds_y}, Height delta={self.rules_bounds_height}, X delta={self.rules_bounds_x}, Width delta={self.rules_bounds_width})...")
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
                
                # Calculate target relative to CURRENT value
                target_y = current_y + self.rules_bounds_y
                
                # Use send_keys to ensure events are triggered and hit Enter
                y_input.clear()
                y_input.send_keys(str(target_y))
                y_input.send_keys(Keys.RETURN)
                print(f"      Adjusted Rules Bounds Y from {current_y} to {target_y} (delta: {self.rules_bounds_y}).")

            # 4. Modify the 'Height' value if provided.
            if self.rules_bounds_height is not None:
                height_input = self.driver.find_element(By.ID, 'textbox-editor-height')
                current_height = int(height_input.get_attribute('value') or 0)
                
                # Calculate target relative to CURRENT value
                target_height = current_height + self.rules_bounds_height
                
                # Use send_keys to ensure events are triggered and hit Enter
                height_input.clear()
                height_input.send_keys(str(target_height))
                height_input.send_keys(Keys.RETURN)
                print(f"      Adjusted Rules Bounds Height from {current_height} to {target_height} (delta: {self.rules_bounds_height}).")

            # 5. Modify the 'X' value if provided.
            if self.rules_bounds_x is not None:
                x_input = self.driver.find_element(By.ID, 'textbox-editor-x')
                current_x = int(x_input.get_attribute('value') or 0)
                
                # Calculate target relative to CURRENT value
                target_x = current_x + self.rules_bounds_x
                
                x_input.clear()
                x_input.send_keys(str(target_x))
                x_input.send_keys(Keys.RETURN)
                print(f"      Adjusted Rules Bounds X from {current_x} to {target_x} (delta: {self.rules_bounds_x}).")

            # 6. Modify the 'Width' value if provided.
            if self.rules_bounds_width is not None:
                width_input = self.driver.find_element(By.ID, 'textbox-editor-width')
                current_width = int(width_input.get_attribute('value') or 0)
                
                # Calculate target relative to CURRENT value
                target_width = current_width + self.rules_bounds_width
                
                width_input.clear()
                width_input.send_keys(str(target_width))
                width_input.send_keys(Keys.RETURN)
                print(f"      Adjusted Rules Bounds Width from {current_width} to {target_width} (delta: {self.rules_bounds_width}).")

            # Wait for a fraction of a second before closing
            time.sleep(0.5)

            # 7. Close the textbox editor.
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

    def _pt_geo(self):
        """{w,h,x,y,width,height,text} for the P/T -- canvas px for w/h, the app's
        normalised [0,1] units for the box -- or None if there is no card P/T box.
        """
        return self.driver.execute_script("""
            var cv = (typeof cardCanvas!=='undefined' && cardCanvas) ? cardCanvas : document.querySelector('canvas');
            if (!cv || !cv.width) return null;
            if (typeof card==='undefined' || !card || !card.text || !card.text.pt) return null;
            var t = card.text.pt;
            return {w: cv.width, h: cv.height, x: t.x, y: t.y,
                    width: t.width, height: t.height, text: t.text};
        """)

    def _open_pt_dialog(self):
        """Open the P/T 'Edit Bounds' dialog and return its current (w, x) integer
        values (the dialog's own units)."""
        d = self.driver
        d.find_element(By.XPATH, "//h3[text()='Text']").click(); time.sleep(0.2)
        d.find_element(By.XPATH, "//h4[text()='Power/Toughness']").click(); time.sleep(0.3)
        d.find_element(By.XPATH, "//button[contains(text(), 'Edit Bounds')]").click()
        self.wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, "div#textbox-editor.opened")))
        gw = int(d.find_element(By.ID, "textbox-editor-width").get_attribute('value') or 0)
        gx = int(d.find_element(By.ID, "textbox-editor-x").get_attribute('value') or 0)
        return gw, gx

    def _set_pt_dialog(self, width, x):
        """Set the P/T box width and x (dialog units) and close the dialog.
        Assumes the dialog is already open."""
        d = self.driver
        def setv(id, val):
            inp = d.find_element(By.ID, id)
            inp.clear(); inp.send_keys(str(int(val))); inp.send_keys(Keys.RETURN); time.sleep(0.3)
        setv("textbox-editor-width", width)
        setv("textbox-editor-x", x)
        d.find_element(By.CSS_SELECTOR, "h2.textbox-editor-close").click()
        time.sleep(self.render_delay)

    def _set_pt_box_abs(self, base_gw, base_gx, new_w):
        """Open the P/T 'Edit Bounds' dialog, set width to `new_w` (dialog units,
        relative to the ORIGINAL width `base_gw`) and shift x left by exactly the
        added width so the box's RIGHT edge stays put (no room to grow right -- it
        is at the card edge), then close it.  Absolute against base_gw, so repeated
        calls never compound and the right edge is always held."""
        if base_gw <= 0:
            return False
        self._open_pt_dialog()                          # ensure it's open/visible
        new_w = max(int(new_w), base_gw)                # only ever widen
        added = new_w - base_gw
        new_x = base_gx - added                         # hold the right edge
        if new_x < 0:
            new_w = base_gw + base_gx; new_x = 0        # cap: never off-card
        self._set_pt_dialog(new_w, new_x)
        return True

    def apply_pt_bounds_mods(self):
        """
        Modifies the X / Y / Width / Height of the Power/Toughness box by opening
        the 'Edit Bounds' dialog and adjusting each provided value by the relative
        delta in self.pt_bounds_x / _y / _width / _height (only the ones provided
        are touched).  Mirrors apply_rules_text_bounds_mods() exactly.

        The P/T box's right edge is at the card edge, so to WIDEN it pass a
        positive width AND a negative x of the same size.  --auto-fit-pt (see
        apply_auto_fit_pt()) does this calculation for you; use the manual deltas to
        override.
        """
        if (self.pt_bounds_x is None and self.pt_bounds_y is None
                and self.pt_bounds_width is None and self.pt_bounds_height is None):
            return

        print(f"   Applying P/T bounds modifications (x={self.pt_bounds_x}, "
              f"y={self.pt_bounds_y}, w={self.pt_bounds_width}, "
              f"h={self.pt_bounds_height})...")
        try:
            self.text_tab.click()
            field_button_selector = "//h4[text()='Power/Toughness']"
            field_button = self.wait.until(EC.element_to_be_clickable((By.XPATH, field_button_selector)))
            field_button.click()
            time.sleep(0.4)

            self.wait.until(EC.element_to_be_clickable(
                (By.XPATH, "//button[contains(text(), 'Edit Bounds')"))).click()
            self.wait.until(EC.visibility_of_element_located(
                (By.CSS_SELECTOR, "div#textbox-editor.opened")))

            def bump(id, delta):
                if delta is None:
                    return
                inp = self.driver.find_element(By.ID, id)
                cur = int(inp.get_attribute('value') or 0)
                tgt = cur + delta
                # width grows toward the LEFT (right edge fixed); x follows the
                # right edge so it shifts left by the same added width.
                inp.clear(); inp.send_keys(str(tgt)); inp.send_keys(Keys.RETURN)
                print(f"      P/T {id.split('-')[-1]}: {cur} -> {tgt} (delta {delta})")
                time.sleep(0.3)

            # Independent deltas (exactly like --rules-bounds-*).  The P/T box's
            # right edge is at the card edge, so to WIDEN it you typically pass a
            # positive width AND a negative x of the same size.
            bump("textbox-editor-x", self.pt_bounds_x)
            bump("textbox-editor-y", self.pt_bounds_y)
            bump("textbox-editor-width", self.pt_bounds_width)
            bump("textbox-editor-height", self.pt_bounds_height)

            self.driver.find_element(By.CSS_SELECTOR, "h2.textbox-editor-close").click()
            time.sleep(self.render_delay)
        except (TimeoutException, NoSuchElementException) as e:
            print(f"      While modifying P/T bounds: {e}", file=sys.stderr)
        except Exception as e:
            print(f"      An unexpected error modifying P/T bounds: {e}", file=sys.stderr)

    def apply_auto_fit_pt(self, margin_px=12.0):
        """Opt-in P/T box auto-fit: widen the P/T box (holding its right edge)
        so a WIDE P/T (e.g. 12/12, 50/50) is NOT scale-fitted down at a large
        {fontsize}.  Narrow P/Ts (3/4, 8/8, 2/1) that already fit the base box
        are returned untouched.

        PURE MATH -- reads pt_calib.json (calibrated once offline by
        pt_calibrate.py), reads the card's P/T text + the user's {fontsize}/
        {kerning} tags, and computes the required dialog-unit width.  Then sets
        it once.  No magenta, no binary search, no re-render (unlike the earlier
        pixel-hunt implementation).  Mirrors autofit_type()/autofit_title()
        which are themselves pure-math against their glyph tables.
        """
        from automator_utils import autofit_pt as _af_pt

        # (1) Read the P/T text from the live card (already has the user's
        #     {fontsize/#shadow/#kerning} tags applied by _apply_text_mods).
        d = self.driver
        d.find_element(By.XPATH, "//h3[text()='Text']").click(); time.sleep(0.2)
        d.find_element(By.XPATH, "//h4[text()='Power/Toughness']").click(); time.sleep(0.3)
        raw = d.find_element(By.ID, "text-editor").get_attribute("value") or ""
        import re as _re
        pt_text = _re.sub(r'\{[^}]+\}', '', raw).strip()
        if not pt_text:
            print("   [Auto-Fit-PT] no P/T text on the card; skipping.")
            return

        # (2) Read the base box (dialog units).
        base = self._open_pt_dialog()
        if not base:
            print("   [Auto-Fit-PT] no P/T 'Edit Bounds' dialog; skipping.")
            return
        base_gw, base_gx = base

        # (3) Pure math: how wide (du) must the box be so the P/T renders at
        #     its natural user-fontsize size?
        new_du, target_px, natural_px, widen = _af_pt(
            pt_text,
            font_size=getattr(self, 'pt_font_size', None),
            kerning=getattr(self, 'pt_kerning', None),
            base_box_du=base_gw,
        )

        if widen:
            self._set_pt_box_abs(base_gw, base_gx, new_du)
            print(f"   [Auto-Fit-PT] '{pt_text}': natural {natural_px:.0f}px "
                  f"> base-box {base_gw}du; widening to {new_du}du "
                  f"(target {target_px:.0f}px, right edge held).")
        else:
            print(f"   [Auto-Fit-PT] '{pt_text}': natural {natural_px:.0f}px "
                  f"<= base box {base_gw}du; left alone.")

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

    def clear_mana_cost(self):
        """
        Clears the Mana Cost field.
        """
        print("   Clearing Mana Cost...")
        try:
            self.text_tab.click()
            
            field_button_selector = "//h4[text()='Mana Cost']"
            text_editor_id = "text-editor"

            field_button = self.wait.until(EC.element_to_be_clickable((By.XPATH, field_button_selector)))
            field_button.click()
            
            time.sleep(0.5)

            text_input = self.wait.until(EC.presence_of_element_located((By.ID, text_editor_id)))
            
            self.driver.execute_script("arguments[0].value = '';", text_input)
            self.driver.execute_script("arguments[0].dispatchEvent(new Event('input'))", text_input)
            self.driver.execute_script("arguments[0].dispatchEvent(new Event('change'))", text_input)
            
            print("      Mana Cost cleared.")
            time.sleep(self.render_delay)

        except Exception as e:
            print(f"      An error occurred while clearing Mana Cost: {e}", file=sys.stderr)


    def _read_field_value(self, field_name):
        """
        Reads the current value of a named text field (e.g. 'Title', 'Mana Cost')
        from the Card Conjurer text editor without modifying it.
        Returns the string (possibly with tags) or None on failure.
        """
        try:
            field_button = self.wait.until(EC.element_to_be_clickable((By.XPATH, f"//h4[text()='{field_name}']")))
            field_button.click()
            time.sleep(0.3)
            text_input = self.wait.until(EC.element_to_be_clickable((By.ID, "text-editor")))
            return text_input.get_attribute('value')
        except Exception:
            return None

    def _read_title_and_mana_from_ui(self):
        """
        Reads the current Title text and Mana Cost text from the UI.
        Returns (clean_title, mana_cost) for auto-fit estimation.
        """
        import re as _re
        title_raw = self._read_field_value('Title')
        mana_raw = self._read_field_value('Mana Cost')
        clean_title = _re.sub(r'\{[^}]+\}', '', title_raw or '').strip()
        return clean_title, (mana_raw or '')

    def _process_all_text_modifications(self):
        """
        Orchestrator for all text modifications to prevent race conditions.
        Returns True if a modified was successfully made.
        """
        print(f"   [Debug] Entering _process_all_text_modifications. auto_fit_type={getattr(self, 'auto_fit_type', 'MISSING')}, auto_fit_title={getattr(self, 'auto_fit_title', 'MISSING')}")

        # --- UPDATED: Check for new parameters ---
        has_mods_to_apply = any([
            self.title_font_size, self.title_shadow, self.title_kerning, self.title_left, self.title_up,
            self.type_font_size, self.type_shadow, self.type_kerning, self.type_left,
            self.pt_font_size, self.pt_shadow, self.pt_kerning, self.pt_bold, self.pt_up,
            self.flavor_font, self.rules_down, getattr(self, 'auto_fit_type', False),
            getattr(self, 'auto_fit_title', False)
        ])
        if not has_mods_to_apply:
            return False

        self.text_tab.click()

        any_text_mod_made = False

        # --- Title Auto-Fit (weighted width vs mana cost) ---
        # Compute effective kerning / fontsize for the Title before _apply_text_mods
        # injects the tags, so the shrunken values are written verbatim.
        eff_title_kerning = self.title_kerning
        eff_title_fs = self.title_font_size
        if getattr(self, 'auto_fit_title', False):
            try:
                clean_name, mana_cost = self._read_title_and_mana_from_ui()
                if clean_name:
                    from automator_utils import autofit_title
                    k0 = eff_title_kerning if eff_title_kerning is not None else 0
                    f0 = eff_title_fs if eff_title_fs is not None else 0
                    eff_title_kerning, eff_title_fs = autofit_title(
                        clean_name, mana_cost, k0, f0,
                        self.title_left if self.title_left else 0,
                        min_kerning=getattr(self, 'min_kerning', None),
                        gap=getattr(self, 'title_gap', None))
            except Exception as e:
                print(f"      Error during Title Auto-Fit: {e}", file=sys.stderr)

        if self._apply_text_mods("Title", eff_title_fs, self.title_shadow, eff_title_kerning, self.title_left, up=self.title_up): any_text_mod_made = True
        
        # --- Type Line Auto-Fit (calibrated width model vs set symbol) ---
        final_type_fs = self.type_font_size
        final_type_kerning = self.type_kerning

        is_auto_fit = getattr(self, 'auto_fit_type', False)
        print(f"   [Debug] Auto-Fit Check: Enabled={is_auto_fit}")

        if is_auto_fit:
            try:
                # Navigate to Type line to read the current type text.
                self.text_tab.click()
                field_button_selector = "//h4[text()='Type']"
                field_button = self.wait.until(EC.element_to_be_clickable((By.XPATH, field_button_selector)))
                field_button.click()
                time.sleep(0.5)

                text_input = self.wait.until(EC.presence_of_element_located((By.ID, "text-editor")))
                current_type_text = text_input.get_attribute('value')
                print(f"   [Debug] Read Type Text: '{current_type_text}'")

                if current_type_text:
                    from automator_utils import autofit_type, estimate_set_symbol_left
                    clean_text = re.sub(r'\{[^}]+\}', '', current_type_text).strip()
                    # Reserve room for the symbol on the right of the row using
                    # THIS card's live symbol edge (loaded from the project file)
                    # when known, otherwise the conservative constant.  Gap = --type-gap.
                    sl = None
                    has_symbol = True
                    try:
                        geom = self.get_symbol_geometry()
                        if geom:
                            sl = estimate_set_symbol_left(
                                float(geom['x']) if geom.get('x') is not None else None,
                                float(geom['zoom']) if geom.get('zoom') is not None else None)
                            has_symbol = bool(geom.get('source') or sl is not None)
                    except Exception:
                        has_symbol = True
                    final_type_kerning, final_type_fs = autofit_type(
                        clean_text,
                        self.type_kerning if self.type_kerning is not None else 0,
                        self.type_font_size if self.type_font_size is not None else 0,
                        self.type_left if self.type_left else 0,
                        has_set_symbol=has_symbol,
                        set_symbol_left=sl,
                        gap=getattr(self, 'type_gap', None),
                        min_kerning=getattr(self, 'min_kerning', None))
            except Exception as e:
                print(f"      Error during Type Auto-Fit: {e}", file=sys.stderr)

        if self._apply_text_mods("Type", final_type_fs, self.type_shadow, final_type_kerning, self.type_left): any_text_mod_made = True
