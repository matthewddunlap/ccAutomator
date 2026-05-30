import time
import hashlib
import sys
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select
from selenium.common.exceptions import TimeoutException, NoSuchElementException

class CanvasMixin:
    STABILIZE_TIMEOUT = 20
    STABILITY_INTERVAL = 0.1
    STABILITY_CHECKS = 3
    def _get_canvas_data_url(self):
        # Use a cached selector if available to speed up subsequent calls
        if hasattr(self, '_cached_canvas_selector'):
            js_script = f"""
                const canvas = document.querySelector('{self._cached_canvas_selector}');
                if (canvas && canvas.width > 0 && canvas.height > 0) {{
                    try {{ return canvas.toDataURL('image/png'); }} catch (e) {{ return 'error: ' + e.message; }}
                }}
                return null;
            """
            return self.driver.execute_script(js_script)

        # Fallback: Find the valid selector and cache it
        js_script = """
            const selectors = ['#mainCanvas', '#card-canvas', '#canvas', 'canvas'];
            for (let selector of selectors) {
                const canvas = document.querySelector(selector);
                if (canvas && canvas.width > 0 && canvas.height > 0) {
                    return { selector: selector, dataUrl: canvas.toDataURL('image/png') };
                }
            }
            return null;
        """
        result = self.driver.execute_script(js_script)
        if result and isinstance(result, dict):
            self._cached_canvas_selector = result['selector']
            return result['dataUrl']
        return None

    def _get_canvas_hash(self):
        """
        Computes a hash of the canvas content directly in the browser.
        Returns a tuple (hash_string, selector_used) or (None, None).
        """
        # Use a cached selector if available
        selector_part = ""
        if hasattr(self, '_cached_canvas_selector'):
             selector_part = f"const canvas = document.querySelector('{self._cached_canvas_selector}');"
             # If we have a cached selector, we assume it's correct. 
             # If it fails (e.g. page reload), we might need to invalidate it, but for now assume persistence.
        else:
             selector_part = """
                const selectors = ['#mainCanvas', '#card-canvas', '#canvas', 'canvas'];
                let canvas = null;
                let usedSelector = null;
                for (let selector of selectors) {
                    canvas = document.querySelector(selector);
                    if (canvas && canvas.width > 0 && canvas.height > 0) {
                        usedSelector = selector;
                        break; 
                    }
                }
             """

        js_script = f"""
            {selector_part}
            if (canvas && canvas.width > 0 && canvas.height > 0) {{
                try {{
                    var dataUrl = canvas.toDataURL('image/png');
                    var hash = 0, i, chr;
                    if (dataUrl.length === 0) return null;
                    for (i = 0; i < dataUrl.length; i++) {{
                        chr   = dataUrl.charCodeAt(i);
                        hash  = ((hash << 5) - hash) + chr;
                        hash |= 0; // Convert to 32bit integer
                    }}
                    // Return object with hash and selector (if we found a new one)
                    return {{ 'hash': hash.toString(), 'selector': (typeof usedSelector !== 'undefined' ? usedSelector : null) }};
                }} catch (e) {{ return {{ 'error': e.message }}; }}
            }}
            return null;
        """
        result = self.driver.execute_script(js_script)
        
        if result and isinstance(result, dict):
            if 'error' in result:
                if getattr(self, 'debug', False):
                    print(f"   [Debug] Canvas JS Error: {result['error']}")
                return None, None
            
            # Cache the selector if we got one back and haven't cached it yet
            if result.get('selector') and not hasattr(self, '_cached_canvas_selector'):
                self._cached_canvas_selector = result['selector']
                if getattr(self, 'debug', False):
                    print(f"   [Debug] Cached canvas selector: {self._cached_canvas_selector}")
            
            return result.get('hash'), self._cached_canvas_selector if hasattr(self, '_cached_canvas_selector') else result.get('selector')
            
        return None, None

    def _wait_for_canvas_stabilization(self, initial_hash, wait_for_change=True):
        start_time = time.time()
        last_hash, stable_count = None, 0
        
        # If we don't have an initial hash but are asked to wait for change, 
        # we must get one.
        if initial_hash is None and wait_for_change:
            initial_hash, _ = self._get_canvas_hash()
                
        while time.time() - start_time < self.STABILIZE_TIMEOUT:
            current_hash, _ = self._get_canvas_hash()
            
            if not current_hash:
                if getattr(self, 'debug', False):
                    elapsed = time.time() - start_time
                    print(f"   [Debug] Wait: {elapsed:.2f}s | Hash: None (Canvas not ready)")
                time.sleep(self.STABILITY_INTERVAL); continue
            
            # If waiting for change, ensure we have moved away from initial state
            if wait_for_change and initial_hash and current_hash == initial_hash:
                time.sleep(self.STABILITY_INTERVAL); continue
                
            # Stability Check
            if current_hash == last_hash: 
                stable_count += 1
            else: 
                last_hash = current_hash; stable_count = 1
                
            if stable_count >= self.STABILITY_CHECKS:
                return current_hash
            
            if getattr(self, 'debug', False):
                elapsed = time.time() - start_time
                print(f"   [Debug] Wait: {elapsed:.2f}s | Hash: {current_hash} | Stable: {stable_count} | Change: {wait_for_change}")
            
            time.sleep(self.STABILITY_INTERVAL)
        
        if wait_for_change:
            print("Warning: Timeout waiting for canvas to stabilize (change detected: False).", file=sys.stderr)
        else:
            print("Warning: Timeout waiting for canvas to stabilize (steady state).", file=sys.stderr)
        return None

    def set_frame(self, frame_value, wait=True):
        try:
            art_tab = self.wait.until(EC.element_to_be_clickable((By.XPATH, '//*[@id="creator-menu-tabs"]/h3[3]')))
            art_tab.click()
            frame_dropdown = self.wait.until(EC.presence_of_element_located((By.ID, 'autoFrame')))
            
            select = Select(frame_dropdown)
            current_val = select.first_selected_option.get_attribute("value")
            
            if current_val == frame_value:
                print(f"   Frame already set to '{frame_value}'. Skipping update.")
                return

            select.select_by_value(frame_value)
            print(f"Successfully set frame by value to '{frame_value}'.")
            
            if wait:
                print("Waiting for frame to apply...")
                self.current_canvas_hash = self._wait_for_canvas_stabilization(self.current_canvas_hash, wait_for_change=False)
        except (TimeoutException, NoSuchElementException) as e:
            print(f"Error setting frame: {e}", file=sys.stderr)
            raise

    def apply_white_border(self):
        """
        Applies the white border by finding the correct thumbnail and double-clicking
        it using a more robust JavaScript-based approach.
        """
        print("Applying white border...")
        try:
            # 1. Navigate to the Frame tab
            frame_tab = self.wait.until(EC.element_to_be_clickable((By.XPATH, "//h3[text()='Frame']")))
            frame_tab.click()

            # 2. Define the reliable selector for the white border thumbnail
            white_border_selector = "//div[@id='frame-picker']//img[contains(@src, '/whiteThumb.png')]"
            
            print("Searching for the white border thumbnail...")
            
            # 3. Wait for the element to be clickable, not just present. This is a stronger check.
            white_border_thumb = self.wait.until(
                EC.element_to_be_clickable((By.XPATH, white_border_selector))
            )

            # 4. Use JavaScript to scroll the element into view. This prevents issues where the element is off-screen.
            print("Scrolling thumbnail into view...")
            self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", white_border_thumb)
            time.sleep(0.5) # A brief pause to ensure scrolling is complete

            # 5. Use two consecutive JavaScript clicks to simulate a double-click.
            #    This is often more reliable than ActionChains for triggering JS event listeners.
            print("Found thumbnail. Attempting double JavaScript click...")
            self.driver.execute_script("arguments[0].click();", white_border_thumb)
            self.driver.execute_script("arguments[0].click();", white_border_thumb)

            # --- THE FIX: Use a fixed delay, not stabilization ---
            print(f"   Waiting {self.render_delay}s for border to render...")
            time.sleep(self.render_delay)
            print("   White border applied.")

        except Exception as e:
            print(f"An unexpected error occurred while applying the white border: {e}", file=sys.stderr)
            raise

    def apply_mask(self, frame_suffix, mask_names, right_half=False):
        """
        Applies specific masks from a given frame group.
        1. Single-clicks the frame (by suffix) to load its masks.
        2. Double-clicks each mask in the mask picker matching the mask_names.
        3. If right_half is True, also clicks the 'Right Half' button for each mask.
        """
        print(f"   Applying masks {mask_names} from frame '{frame_suffix}' (Right Half: {right_half})...")
        try:
            # 1. Find the frame thumbnail
            thumb_selector = f"//div[@id='frame-picker']//img[contains(@src, '/{frame_suffix}')]"
            thumb = self.wait.until(EC.element_to_be_clickable((By.XPATH, thumb_selector)))
            
            # 2. Single Click to load masks (do NOT double click)
            self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", thumb)
            time.sleep(0.5)
            self.driver.execute_script("arguments[0].click();", thumb)
            time.sleep(0.5) # Wait for mask picker to populate
            
            # 3. Apply each mask
            for mask_name in mask_names:
                # Map mask names to src substrings (Thumbnails are .png)
                mask_src_map = {
                    'Pinline': 'pinlineThumb.png',
                    'Rules': 'rulesThumb.png',
                    'Textbox Pinline': 'trimThumb.png',
                    'Right Half': 'maskRightHalf.png',
                    'Frame': 'frameThumb.png',
                    'Border': 'borderThumb.png'
                }
                
                target_src = mask_src_map.get(mask_name, mask_name.lower())
                
                # Find mask in picker
                mask_selector = f"//div[@id='mask-picker']//img[contains(@src, '{target_src}')]"
                mask_thumb = self.wait.until(EC.element_to_be_clickable((By.XPATH, mask_selector)))
                
                self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", mask_thumb)

                if right_half:
                    # Single click to select, then click "Right Half" button
                    self.driver.execute_script("arguments[0].click();", mask_thumb)
                    time.sleep(0.2)
                    right_half_btn = self.wait.until(EC.element_to_be_clickable((By.ID, "addToRightHalf")))
                    self.driver.execute_script("arguments[0].click();", right_half_btn)
                    print(f"      Applied mask: {mask_name} (Right Half)")
                else:
                    # Double click to apply normally (Left Half / Full)
                    self.driver.execute_script("arguments[0].click();", mask_thumb)
                    self.driver.execute_script("arguments[0].click();", mask_thumb)
                    print(f"      Applied mask: {mask_name}")
                
                time.sleep(0.2)
                
        except Exception as e:
            print(f"   Error applying masks: {e}", file=sys.stderr)

    def set_frame_color(self, colors, type_line=None, mana_cost=None):
        """
        Sets the frame color based on the card's colors and type line.
        Prioritizes 'Artifact' and 'Land' type lines to use specialized base frames.
        For Colored Artifacts and Lands, applies masks from colored Land frames.
        """
        print(f"   Setting frame color for colors: {colors}, type_line: {type_line}...")
        
        target_thumb_suffix = "cThumb.png" # Default to colorless
        is_colored_artifact = False
        is_colored_land = False
        
        # 1. Navigate to the Frame tab
        frame_tab = self.wait.until(EC.element_to_be_clickable((By.XPATH, "//h3[text()='Frame']")))
        frame_tab.click()

        if type_line and "Artifact" in type_line:
            target_thumb_suffix = "aThumb.png"
            if colors:
                is_colored_artifact = True
        elif type_line and "Land" in type_line:
            target_thumb_suffix = "lThumb.png"
            if colors:
                is_colored_land = True
        elif not colors:
            # Colorless non-artifact (e.g. Eldrazi)
            target_thumb_suffix = "cThumb.png"
        elif len(colors) > 1:
            target_thumb_suffix = "mThumb.png"
        else:
            # Single color mapping for spells
            color_map = {
                'W': 'wThumb.png',
                'U': 'uThumb.png',
                'B': 'bThumb.png',
                'R': 'rThumb.png',
                'G': 'gThumb.png'
            }
            target_thumb_suffix = color_map.get(colors[0], "cThumb.png")

        try:
            # 1. Find the thumbnail (Base Frame)
            thumb_selector = f"//div[@id='frame-picker']//img[contains(@src, '/{target_thumb_suffix}')]"
            thumb = self.wait.until(EC.element_to_be_clickable((By.XPATH, thumb_selector)))
            
            # 2. Scroll and Click
            self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", thumb)
            time.sleep(0.5)
            
            # Double click to be safe (Sets the Base Frame)
            self.driver.execute_script("arguments[0].click();", thumb)
            self.driver.execute_script("arguments[0].click();", thumb)
            
            print(f"   Applied base frame using '{target_thumb_suffix}'.")
            
            # 3. Handle Colored Artifacts and Lands (Apply Masks AFTER Base Frame)
            if is_colored_artifact or is_colored_land:
                print(f"   [Colored {'Land' if is_colored_land else 'Artifact'}] Applying colored masks for {colors}...")
                
                # Helper to map color char to Land frame suffix
                def get_land_suffix(color_char):
                    return {
                        'W': 'wlThumb.png',
                        'U': 'ulThumb.png',
                        'B': 'blThumb.png',
                        'R': 'rlThumb.png',
                        'G': 'glThumb.png'
                    }.get(color_char, "cThumb.png")

                # Masks to apply
                # Lands want Pinline, Textbox Pinline, AND Rules (border)
                # Artifacts usually only want Pinlines
                target_masks = ['Pinline', 'Textbox Pinline']
                if is_colored_land:
                    target_masks.append('Rules')
                    print(f"      Including 'Rules' mask for colored Land.")

                # Parse mana_cost or colors to determine color order
                ordered_colors = []
                if mana_cost:
                    # Extract all letters from mana cost (e.g. {1}{B}{R} -> BR)
                    cost_colors = [c for c in mana_cost if c in 'WUBRG']
                    # Deduplicate while preserving order
                    seen = set()
                    ordered_colors = [x for x in cost_colors if not (x in seen or seen.add(x))]
                
                # Fallback if mana_cost didn't give us info (common for lands)
                if not ordered_colors:
                    ordered_colors = colors

                if len(ordered_colors) == 1:
                    # Single Color
                    mask_source_suffix = get_land_suffix(ordered_colors[0])
                    self.apply_mask(mask_source_suffix, target_masks)
                
                elif len(ordered_colors) == 2:
                    # Dual Color (Split Masks)
                    color1 = ordered_colors[0]
                    color2 = ordered_colors[1]
                    
                    print(f"   [Dual {'Land' if is_colored_land else 'Artifact'}] Split Masks: {color1} (Left) / {color2} (Right)")
                    
                    # Apply Left Half (Normal)
                    suffix1 = get_land_suffix(color1)
                    self.apply_mask(suffix1, target_masks, right_half=False)
                    
                    # Apply Right Half
                    suffix2 = get_land_suffix(color2)
                    self.apply_mask(suffix2, target_masks, right_half=True)
                    
                else:
                    # 3+ Colors (Gold)
                    print(f"   [Multi {'Land' if is_colored_land else 'Artifact'}] 3+ Colors: Using Gold Land Frame as mask source")
                    self.apply_mask("lThumb.png", target_masks)
            
            time.sleep(self.render_delay)
            
        except Exception as e:
            print(f"   Error setting frame color: {e}", file=sys.stderr)
            # Debug: print available thumbs
            try:
                images = self.driver.find_elements(By.XPATH, "//div[@id='frame-picker']//img")
                srcs = [img.get_attribute('src') for img in images]
                print(f"      Available thumbnails: {srcs}", file=sys.stderr)
            except:
                pass
