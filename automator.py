import time
import re
import os
import base64
import sys
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

import time
import re
import os
import base64
import sys
import hashlib
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

class CardConjurerAutomator:
    """
    A class to automate interactions with the Card Conjurer web application.
    """
    def __init__(self, url, download_dir='.', headless=True):
        """
        Initializes the WebDriver and navigates to the URL.
        """
        self.download_dir = download_dir
        if not os.path.exists(self.download_dir):
            os.makedirs(self.download_dir)

        chrome_options = Options()
        if headless:
            chrome_options.add_argument("--headless")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--window-size=1200,900")

        self.driver = webdriver.Chrome(options=chrome_options)
        self.driver.get(url)
        self.wait = WebDriverWait(self.driver, 15)
        self.wait.until(EC.presence_of_element_located((By.ID, 'creator-menu-tabs')))

        # State tracking for canvas stabilization
        self.current_canvas_hash = None
        # Constants for stabilization logic
        self.STABILIZE_TIMEOUT = 10  # seconds
        self.STABILITY_CHECKS = 3
        self.STABILITY_INTERVAL = 0.3  # seconds

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def _get_canvas_data_url(self):
        """Executes JS to get the canvas data URL. Tries multiple selectors."""
        js_script = """
            const selectors = ['#mainCanvas', '#card-canvas', '#canvas', 'canvas'];
            for (let selector of selectors) {
                const canvas = document.querySelector(selector);
                if (canvas && canvas.width > 0 && canvas.height > 0) {
                    try {
                        return canvas.toDataURL('image/png');
                    } catch (e) {
                        return 'error: ' + e.message;
                    }
                }
            }
            return null;
        """
        return self.driver.execute_script(js_script)

    def _wait_for_canvas_stabilization(self, initial_hash):
        """Waits for the canvas to change from an initial state and then stabilize."""
        start_time = time.time()
        last_hash = None
        stable_count = 0
        
        # First, get a valid hash for the current canvas
        if initial_hash is None:
            data_url = self._get_canvas_data_url()
            if data_url and data_url.startswith('data:image/png;base64,'):
                initial_hash = hashlib.md5(data_url.encode('utf-8')).hexdigest()

        while time.time() - start_time < self.STABILIZE_TIMEOUT:
            data_url = self._get_canvas_data_url()
            
            if not data_url or not data_url.startswith('data:image/png;base64,'):
                time.sleep(self.STABILITY_INTERVAL)
                continue

            current_hash = hashlib.md5(data_url.encode('utf-8')).hexdigest()

            # Wait until the canvas is different from the initial state
            if current_hash == initial_hash:
                time.sleep(self.STABILITY_INTERVAL)
                continue

            # Now wait for the new state to stabilize
            if current_hash == last_hash:
                stable_count += 1
            else:
                last_hash = current_hash
                stable_count = 1
            
            if stable_count >= self.STABILITY_CHECKS:
                print(f"Canvas stabilized with new hash: {current_hash[:10]}...")
                return current_hash
            
            time.sleep(self.STABILITY_INTERVAL)

        print("Warning: Timeout waiting for canvas to stabilize.", file=sys.stderr)
        return None

    def set_frame(self, frame_value):
        """
        Selects the specified card frame by its value attribute.
        """
        try:
            art_tab = self.wait.until(EC.element_to_be_clickable((By.XPATH, '//*[@id="creator-menu-tabs"]/h3[3]')))
            art_tab.click()

            frame_dropdown = self.wait.until(EC.presence_of_element_located((By.ID, 'autoFrame')))
            select = Select(frame_dropdown)
            select.select_by_value(frame_value)
            print(f"Successfully set frame by value to '{frame_value}'.")
            
            # After setting frame, wait for it to apply and update the hash
            print("Waiting for frame to apply...")
            self.current_canvas_hash = self._wait_for_canvas_stabilization(self.current_canvas_hash)

        except TimeoutException:
            print("Error: Could not find the 'Art' tab or the frame selection dropdown.", file=sys.stderr)
            raise
        except NoSuchElementException:
            print(f"Error: Frame with value '{frame_value}' not found in the dropdown.", file=sys.stderr)
            raise

    def import_and_save_card(self, card_name):
        """
        Imports a card, waits for the canvas to stabilize, and saves the content.
        """
        try:
            import_save_tab = self.wait.until(EC.element_to_be_clickable((By.XPATH, '//*[@id="creator-menu-tabs"]/h3[7]')))
            import_save_tab.click()

            import_input = self.wait.until(EC.presence_of_element_located((By.ID, 'import-name')))
            import_input.clear()
            import_input.send_keys(card_name)

            import_button = self.wait.until(EC.element_to_be_clickable((By.ID, 'import-index')))
            import_button.click()
            print(f"Importing card: '{card_name}' and waiting for canvas to stabilize...")

            new_hash = self._wait_for_canvas_stabilization(self.current_canvas_hash)

            if not new_hash or new_hash == self.current_canvas_hash:
                print(f"Error: Canvas did not change or stabilize for '{card_name}'.", file=sys.stderr)
                self.current_canvas_hash = new_hash # Update hash to avoid getting stuck
                return

            self.current_canvas_hash = new_hash
            
            # Perform one final capture after stabilization
            data_url = self._get_canvas_data_url()
            if not data_url or not data_url.startswith('data:image/png;base64,'):
                print(f"Error: Could not perform final canvas capture for '{card_name}'.", file=sys.stderr)
                return

            img_data = base64.b64decode(data_url.split(',', 1)[1])
            safe_filename = re.sub(r'[^a-zA-Z0-9_]', '_', card_name)
            output_path = os.path.join(self.download_dir, f"{safe_filename}.png")

            with open(output_path, 'wb') as f:
                f.write(img_data)
            print(f"Saved canvas to '{output_path}'.")

        except TimeoutException:
            print(f"Error: Timed out while trying to import or save '{card_name}'.", file=sys.stderr)
        except Exception as e:
            print(f"An unexpected error occurred for card '{card_name}': {e}", file=sys.stderr)

    def close(self):
        if self.driver:
            self.driver.quit()
