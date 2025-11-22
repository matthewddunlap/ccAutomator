import time
import hashlib
import sys
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select
from selenium.common.exceptions import TimeoutException, NoSuchElementException

class CanvasMixin:
    def _get_canvas_data_url(self):
        js_script = """
            const selectors = ['#mainCanvas', '#card-canvas', '#canvas', 'canvas'];
            for (let selector of selectors) {
                const canvas = document.querySelector(selector);
                if (canvas && canvas.width > 0 && canvas.height > 0) {
                    try { return canvas.toDataURL('image/png'); } catch (e) { return 'error: ' + e.message; }
                }
            }
            return null;
        """
        return self.driver.execute_script(js_script)

    def _wait_for_canvas_stabilization(self, initial_hash, wait_for_change=True):
        start_time = time.time()
        last_hash, stable_count = None, 0
        
        # If we don't have an initial hash but are asked to wait for change, 
        # we must get one.
        if initial_hash is None and wait_for_change:
            data_url = self._get_canvas_data_url()
            if data_url and data_url.startswith('data:image/png;base64,'):
                initial_hash = hashlib.md5(data_url.encode('utf-8')).hexdigest()
                
        while time.time() - start_time < self.STABILIZE_TIMEOUT:
            data_url = self._get_canvas_data_url()
            if not data_url or not data_url.startswith('data:image/png;base64,'):
                time.sleep(self.STABILITY_INTERVAL); continue
            
            current_hash = hashlib.md5(data_url.encode('utf-8')).hexdigest()
            
            # If waiting for change, ensure we have moved away from initial state
            if wait_for_change and initial_hash and current_hash == initial_hash:
                time.sleep(self.STABILITY_INTERVAL); continue
                
            # Stability Check
            if current_hash == last_hash: 
                stable_count += 1
            else: 
                last_hash = current_hash; stable_count = 1
                
            if stable_count >= self.STABILITY_CHECKS:
                # print(f"Canvas stabilized with new hash: {current_hash[:10]}...")
                return current_hash
            time.sleep(self.STABILITY_INTERVAL)
        
        if wait_for_change:
            print("Warning: Timeout waiting for canvas to stabilize (change detected: False).", file=sys.stderr)
        else:
            print("Warning: Timeout waiting for canvas to stabilize (steady state).", file=sys.stderr)
        return None

    def set_frame(self, frame_value):
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
            print("Waiting for frame to apply...")
            self.current_canvas_hash = self._wait_for_canvas_stabilization(self.current_canvas_hash, wait_for_change=True)
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
