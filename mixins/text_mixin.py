import time
import sys
import re
import math
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
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
                # Apply the flavor fontsize with REPLACE semantics to the part
                # after {flavor}: a re-run overwrites the previously injected
                # {fontsize} instead of stacking a second one after {flavor}
                # (the old str.replace did that on every run).
                from automator_utils import apply_text_tags
                pre, flavor_part = current_text.split('{flavor}', 1)
                new_text = f"{pre}{{flavor}}{apply_text_tags(flavor_part, fontsize=self.flavor_font)}"

                if new_text == current_text:
                    print("      {flavor} already has the requested font size. Skipping.")
                else:
                    self.driver.execute_script("arguments[0].value = arguments[1];", text_input, new_text)
                self.driver.execute_script("arguments[0].dispatchEvent(new Event('input'))", text_input)
                self.driver.execute_script("arguments[0].dispatchEvent(new Event('change'))", text_input)
                # self.driver.execute_script("textEdited()")
                print(f"      Found {{flavor}} tag. Injected font size tag.")
                
                self._wait_for_render()
            else:
                print("      No {flavor} tag found. Skipping.")

        except Exception as e:
            print(f"      An error occurred while applying flavor text mods: {e}", file=sys.stderr)

    def _apply_text_mods(self, field_name, font_size=None, shadow=None, kerning=None, left=None, bold=False, up=None, down=None):
        """
        Generic method to apply modifications to a specific text field (e.g., Title, Type).

        Tags are applied with REPLACE semantics (shared apply_text_tags helper):
        an existing {fontsize}/{shadow}/... tag of the same kind is updated in
        place, a missing one is prepended, and duplicated stale tags converge
        to one.  So a re-run with CHANGED values overwrites the old tags
        instead of skipping (stale value survives) or prepending a second tag
        set (silent wrong output), and a re-run with the SAME values is a
        no-op that leaves the field untouched.
        """
        from automator_utils import apply_text_tags

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

                if current_text and current_text.strip():
                    # Apply with REPLACE semantics (see apply_text_tags): an
                    # existing tag of the same kind is updated in place, a
                    # missing one is prepended, duplicated stale tags converge
                    # to one.  The old guard `if prefix in current_text:
                    # return` either skipped a re-run with CHANGED values
                    # (stale tag survived) or prepended a full second tag set
                    # (silent wrong output); it also false-positived on
                    # substrings ({fontsize1} inside {fontsize10}).
                    new_text = apply_text_tags(
                        current_text,
                        fontsize=font_size, shadow=shadow, kerning=kerning,
                        left=left, up=up, down=down, bold=bold)

                    if new_text == current_text:
                        # Already exactly as requested (e.g. same values
                        # re-applied) -- no DOM write, no re-render.
                        print(f"      '{field_name}' already has the requested modifications. Skipping.")
                        return

                    # print(f"      [Debug] Executing JS to update text...")
                    self.driver.execute_script("arguments[0].value = arguments[1];", text_input, new_text)
                    self.driver.execute_script("arguments[0].dispatchEvent(new Event('input'))", text_input)
                    self.driver.execute_script("arguments[0].dispatchEvent(new Event('change'))", text_input)
                    # self.driver.execute_script("textEdited()")
                    print(f"      '{field_name}' changed from '{current_text}' to '{new_text}'.")

                # Wait for the change to render on a canvas
                self._wait_for_render()
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
            self._wait_for_render()

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
            
            self._wait_for_render()
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
            self._wait_for_render()

        except (TimeoutException, NoSuchElementException) as e:
            # A failed close (e.g. the button wasn't there) is NOT fatal; the
            # finally below still guarantees the overlay is dismissed.
            print(f"      An error occurred while modifying rules text bounds: {e}", file=sys.stderr)
            self._wait_for_render()
        except Exception as e:
            print(f"      An unexpected error occurred in _apply_rules_text_bounds_mods: {e}", file=sys.stderr)
        finally:
            # #textbox-editor.opened is added only by the 'Edit Bounds' click and
            # removed only by its close button (Card Conjurer's creator.js).  If any
            # step above threw before the close ran, the overlay would stay open and
            # intercept the NEXT field's click.  Guarantee it is dismissed.
            self._close_textbox_editor()

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
        # Defensive: dismiss any #textbox-editor overlay left open by a previous
        # card / failed step.  The overlay is a full-card layer that intercepts
        # clicks on the underlying P/T <h4>, so a stale overlay here would make
        # the field click below raise "element click intercepted".
        self._close_textbox_editor()
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
        self._close_textbox_editor()
        self._wait_for_render()

    def _close_textbox_editor(self):
        """Force-close the '#textbox-editor' 'Edit Bounds' overlay (idempotent).

        The app toggles this overlay purely via a class on <div id='textbox-editor'>:
        the 'Edit Bounds' button ADDS 'opened' and the close <h2> (h2.textbox-editor-
        close) does ``parentElement.classList.remove("opened")`` (creator.js:3323 / the
        h2's inline onclick).  An open overlay is a full-card layer that intercepts
        clicks on the underlying <h4>/'Save Card' button.  We therefore close by
        removing the 'opened' class directly via JS (no focus/interception
        dependency), exactly mirroring the app's own close button, instead of a raw
        element.click().  Never raises; safe when already closed."""
        try:
            self.driver.execute_script("""
                var el = document.querySelector('#textbox-editor');
                if (el) el.classList.remove('opened');
            """)
            self._wait_for_render()
        except Exception:
            pass

    def _close_pt_dialog(self):
        """Close the P/T 'Edit Bounds' overlay (kept as an alias over the shared
        JS-based close so an open overlay never remains and intercepts clicks)."""
        self._close_textbox_editor()

    def _pt_state_init(self):
        """Ensure the P/T box state attributes exist (lazy, so bare TextMixin
        test objects that never ran CardConjurerAutomator.__init__ still work)."""
        if not hasattr(self, "_pt_base"):
            self._pt_base = None
        if not hasattr(self, "_pt_current"):
            self._pt_current = None

    def _reset_pt_box_state(self):
        """Drop the cached P/T home geometry and the box state.  Called when the
        frame changes: a different frame can have a different default P/T box, so
        the cached values are stale and the next card re-reads them."""
        self._pt_state_init()
        self._pt_base = None
        self._pt_current = None

    def _set_pt_box(self, width, x):
        """Set the P/T box to (width, x) in dialog units via the 'Edit Bounds'
        dialog, then record the result in the box state (self._pt_current).

        Opens the dialog itself (fresh; the defensive close inside
        _open_pt_dialog means a lingering overlay can never intercept the click)
        and closes it via _set_pt_dialog, so callers leave no overlay behind.
        Raises on failure -- callers decide how best-effort to be."""
        self._open_pt_dialog()
        self._set_pt_dialog(int(width), int(x))
        self._pt_current = (int(width), int(x))
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

        NOTE: when --auto-fit-pt is on it OWNS the box width/x.  Its "home"
        geometry already includes --pt-bounds-width/--pt-bounds-x and is applied
        (or restored) exactly once whenever a card's geometry changes, so bumping
        width/x here as well would double-apply (and re-bump on every card).  In
        that mode only the y/height deltas are applied by this method.
        """
        auto_fit_on = bool(getattr(self, "auto_fit_pt", False))
        if auto_fit_on:
            if self.pt_bounds_y is None and self.pt_bounds_height is None:
                return
        elif (self.pt_bounds_x is None and self.pt_bounds_y is None
              and self.pt_bounds_width is None and self.pt_bounds_height is None):
            return

        print(f"   Applying P/T bounds modifications (x={self.pt_bounds_x}, "
              f"y={self.pt_bounds_y}, w={self.pt_bounds_width}, "
              f"h={self.pt_bounds_height})...")
        # Defensive: a prior card may have left the #textbox-editor overlay open
        # ("Edit Bounds"); an open overlay intercepts the P/T <h4> click below.
        self._close_textbox_editor()
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
                if auto_fit_on and id in ("textbox-editor-x", "textbox-editor-width"):
                    # width/x are owned by the stateful auto-fit: its home
                    # geometry already includes these deltas (applied exactly
                    # once per state change), so bumping them here would
                    # double-apply.
                    print(f"      P/T {id.split('-')[-1]} delta skipped: applied by --auto-fit-pt home geometry.")
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

            self._close_textbox_editor()
        except (TimeoutException, NoSuchElementException) as e:
            print(f"      While modifying P/T bounds: {e}", file=sys.stderr)
        except Exception as e:
            print(f"      An unexpected error modifying P/T bounds: {e}", file=sys.stderr)
        finally:
            # A throw above (before the close) would otherwise leave
            # #textbox-editor.opened, which intercepts the next field's click.
            self._close_textbox_editor()

    def apply_auto_fit_pt(self, margin_px=12.0):
        """Opt-in P/T box auto-fit -- STATEFUL across the cards of a session.

        Widen the P/T box (holding its right edge) so a WIDE P/T (e.g. 12/12,
        50/50) is NOT scale-fitted down at a large {fontsize}; leave narrow P/Ts
        (3/4, 8/8, 2/1) in the frame's default box.  PURE MATH against
        pt_calib.json (calibrated once offline by pt_calibrate.py) -- no magenta,
        no binary search, no re-render.  Mirrors autofit_type()/autofit_title().

        WHY STATE: CardConjurer CARRIES the P/T box geometry over to
        subsequently loaded cards -- a box widened for one card (12/12) would
        otherwise leak onto the next card's narrower P/T (4/4 after 12/12),
        floating it left of the frame edge.  The box is therefore owned by this
        state machine for the whole session:

          * _pt_base     -- the frame's DEFAULT box (width, x) in dialog units,
                            read live ONCE per frame (before anything has
                            touched the box, so it is the true default) and
                            cached.  Invalidated on a frame change.
          * _pt_current  -- the geometry the box was last set to; None means
                            "at the frame default" (the session starts there).

        Per card the box is moved ONLY when this card's target geometry (home,
        or a widened box) differs from the current one:

          * narrow card, box at home        -> no dialog at all (fast path)
          * wide card, box at home          -> one set (widen)
          * narrow card after a wide card   -> one set (restore to home)
          * consecutive cards, same target  -> no dialog at all

        so a mixed deck pays at most one dialog round-trip per geometry CHANGE,
        never one per card.  A set failure is logged with a warning and does NOT
        fail the card (best effort).
        """
        from automator_utils import autofit_pt as _af_pt
        self._pt_state_init()

        # Defensive: a prior card may have left the #textbox-editor ('Edit Bounds')
        # overlay open (creator.js removes 'opened' ONLY via the close <h2>, so an
        # open one lingers and is a full-card layer that intercepts the P/T <h4>
        # click below -- this is exactly the "element click intercepted" on a wide
        # P/T).  Dismiss it before any interaction.
        self._close_textbox_editor()

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

        # (2) The frame's default box (dialog units), read live ONCE per frame.
        #     This read happens before anything else has set the box this frame,
        #     so the values are the true default (a widened box is never cached
        #     as the default).
        if self._pt_base is None:
            try:
                base = self._open_pt_dialog()
            except Exception as e:
                print(f"   [Auto-Fit-PT] could not read the P/T box geometry: {e}; skipping.",
                      file=sys.stderr)
                return
            finally:
                self._close_pt_dialog()
            if not base or base[0] <= 0:
                print("   [Auto-Fit-PT] no P/T box geometry; skipping.", file=sys.stderr)
                return
            self._pt_base = (int(base[0]), int(base[1]))
            print(f"   [Auto-Fit-PT] cached frame-default P/T box: "
                  f"width={self._pt_base[0]}du x={self._pt_base[1]}du.")

        # (3) HOME = frame default + manual --pt-bounds-width/x (owned by this
        #     state machine, applied exactly once per state change -- never
        #     re-bumped per card).
        home = (self._pt_base[0] + (getattr(self, "pt_bounds_width", None) or 0),
                self._pt_base[1] + (getattr(self, "pt_bounds_x", None) or 0))

        # (4) Pure math: how wide (du) the box must be so the P/T renders at
        #     its natural user-fontsize size.
        new_du, target_px, natural_px, widen = _af_pt(
            pt_text,
            font_size=getattr(self, 'pt_font_size', None),
            kerning=getattr(self, 'pt_kerning', None),
            base_box_du=home[0],
            margin_px=margin_px,
        )
        target = (new_du, home[1] - (new_du - home[0])) if widen else home  # hold the right edge

        # (5) Move the box ONLY if it is not already exactly where this card
        #     needs it.  (A never-set box sits at the frame default.)
        current = self._pt_current if self._pt_current is not None else self._pt_base
        if current == target:
            print(f"   [Auto-Fit-PT] '{pt_text}': box already at "
                  f"{target[0]}du x={target[1]}du; no change.")
            return

        if widen:
            try:
                self._set_pt_box(target[0], target[1])
            except Exception as e:
                # Best effort: a failed set must not fail the card.  The state
                # is then unknown; the next card re-decides from what it reads.
                print(f"   [Auto-Fit-PT] WARNING: widening the P/T box to {target[0]}du "
                      f"failed: {e} -- the card proceeds with the current box.",
                      file=sys.stderr)
                self._pt_current = None
                return
            print(f"   [Auto-Fit-PT] '{pt_text}': natural {natural_px:.0f}px "
                  f"> home box {home[0]}du; widening to {target[0]}du x={target[1]}du "
                  f"(right edge held).")
        else:
            # A previous wide card left the box widened (CardConjurer carries the
            # geometry across cards); put it back to home before this card is
            # saved/captured.  restore_pt_box() is itself best-effort.
            self.restore_pt_box()

    def restore_pt_box(self):
        """Best-effort restore of the P/T box to its HOME geometry (the cached
        frame default plus any --pt-bounds-width/x), using the same
        'Edit Bounds' dialog path the auto-fit uses (_open_pt_dialog /
        _set_pt_dialog / _close_textbox_editor).

        No-op (with a log line) when the state tracker already shows the box at
        home, so repeated cards never pay a dialog round-trip.  A failure is
        logged with a warning and does NOT fail the card; the state is then
        assumed to be home.  Returns True if the box is (now believed to be) at
        home.
        """
        self._pt_state_init()
        if self._pt_current is None and not (
                getattr(self, "pt_bounds_width", None) or getattr(self, "pt_bounds_x", None)):
            print("   [Auto-Fit-PT] P/T box already at home; nothing to restore.")
            return True
        if self._pt_base is None:
            print("   [Auto-Fit-PT] WARNING: no cached P/T home geometry; assuming the "
                  "box is at home.", file=sys.stderr)
            self._pt_current = None
            return False
        home = (self._pt_base[0] + (getattr(self, "pt_bounds_width", None) or 0),
                self._pt_base[1] + (getattr(self, "pt_bounds_x", None) or 0))
        was = self._pt_current
        try:
            self._set_pt_box(home[0], home[1])
        except Exception as e:
            print(f"   [Auto-Fit-PT] WARNING: restoring the P/T box to home "
                  f"({home[0]}du/{home[1]}du) failed: {e} -- assuming home; the card proceeds.",
                  file=sys.stderr)
            self._pt_current = None
            return False
        print(f"   [Auto-Fit-PT] P/T box restored to home {home[0]}du x={home[1]}du"
              + (f" (was {was[0]}du x={was[1]}du)." if was else "."))
        return True

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
            self._wait_for_render()

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
        Applies the Title, Type, and Power/Toughness text mods (the live
        per-card path's set of fields).
        Returns True if any modification was made, False otherwise
        (previously the docstring claimed a return that was never there).
        """
        print(f"   [Debug] Entering _process_all_text_modifications. auto_fit_type={getattr(self, 'auto_fit_type', 'MISSING')}, auto_fit_title={getattr(self, 'auto_fit_title', 'MISSING')}")

        # --- UPDATED: Check for new parameters ---
        has_mods_to_apply = any([
            self.title_font_size, self.title_shadow, self.title_kerning, self.title_left, self.title_up,
            self.type_font_size, self.type_shadow, self.type_kerning, self.type_left,
            # pt_left was missing from this gate while the body (below) applies
            # it -- a lone --pt-left run would have exited before doing anything.
            self.pt_font_size, self.pt_shadow, self.pt_kerning, self.pt_bold, self.pt_up, self.pt_left,
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

        # --- P/T text tags ---
        # The "has mods" gate above has always included the pt_* args, but the
        # body never applied them -- a --pt-* run here did nothing.  Apply them
        # now, exactly like the live per-card path (automator.py P/T block).
        # Safe on re-runs: apply_text_tags replaces in place, so re-applying
        # the same values is a no-op instead of a duplicate tag set.
        if self._apply_text_mods("Power/Toughness", self.pt_font_size, self.pt_shadow,
                                 self.pt_kerning, bold=self.pt_bold, up=self.pt_up, left=self.pt_left):
            any_text_mod_made = True

        return any_text_mod_made
