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

        # Set 'All Art Version' on initialization by clicking its label
        try:
            import_save_tab = self.wait.until(EC.element_to_be_clickable((By.XPATH, '//*[@id="creator-menu-tabs"]/h3[7]')))
            import_save_tab.click()
            
            # Locate the checkbox input element first to check its state
            all_art_checkbox_input = self.wait.until(EC.presence_of_element_located((By.ID, 'importAllPrints')))
            
            if not all_art_checkbox_input.is_selected():
                # Find the parent <label> of the checkbox and click it
                label_for_checkbox = self.driver.find_element(By.XPATH, "//label[.//input[@id='importAllPrints']]")
                label_for_checkbox.click()
                print("Set 'All Art Version' checkbox to ON.")

        except (TimeoutException, NoSuchElementException) as e:
            print(f"Error setting 'All Art Version' on init: {e}", file=sys.stderr)
            raise

        self.current_canvas_hash = None
        self.STABILIZE_TIMEOUT = 10
        self.STABILITY_CHECKS = 3
        self.STABILITY_INTERVAL = 0.3

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

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

    def _wait_for_canvas_stabilization(self, initial_hash):
        start_time = time.time()
        last_hash, stable_count = None, 0
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
            if current_hash == initial_hash:
                time.sleep(self.STABILITY_INTERVAL)
                continue
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

    def _import_and_stabilize(self, card_name):
            """
            Private method to import a card, find an exact name match, select its 
            last available print, and wait for the canvas to stabilize.
            """
            from selenium.webdriver.common.keys import Keys
    
            try:
                import_save_tab = self.wait.until(EC.element_to_be_clickable((By.XPATH, '//*[@id="creator-menu-tabs"]/h3[7]')))
                import_save_tab.click()
    
                import_input = self.wait.until(EC.presence_of_element_located((By.ID, 'import-name')))
                import_input.clear()
    
                dropdown_locator = (By.ID, 'import-index')
                try:
                    first_option = self.driver.find_element(*dropdown_locator).find_element(By.TAG_NAME, 'option')
                except NoSuchElementException:
                    first_option = None
    
                import_input.send_keys(card_name)
                import_input.send_keys(Keys.RETURN)
                print(f"Searching for '{card_name}'...")
    
                if first_option:
                    self.wait.until(EC.staleness_of(first_option))
    
                self.wait.until(
                    lambda driver: len(driver.find_element(*dropdown_locator).find_elements(By.TAG_NAME, 'option')) > 0
                )
    
                # --- START OF NEW FILTERING LOGIC ---
                dropdown = Select(self.driver.find_element(*dropdown_locator))
                
                exact_matches = []
                for option in dropdown.options:
                    option_text = option.text
                    # Perform a case-insensitive exact match on the card name part
                    if option_text.lower().startswith(card_name.lower()):
                        # Check what comes after the name to ensure it's not a different card
                        # e.g. "Sol Ring" vs "Sol Ring Fragment"
                        end_of_name_index = len(card_name)
                        if len(option_text) == end_of_name_index or option_text[end_of_name_index:end_of_name_index+2] == ' (':
                            match_data = {
                                'index': option.get_attribute('value'),
                                'text': option_text,
                                'set_name': None,
                                'collector_number': None
                            }
                            # Use regex to extract set and collector number if they exist
                            set_info = re.search(r'\(([^#]+?)\s*#([^)]+)\)', option_text)
                            if set_info:
                                match_data['set_name'] = set_info.group(1).strip()
                                match_data['collector_number'] = set_info.group(2).strip()
                            
                            exact_matches.append(match_data)
    
                if not exact_matches:
                    print(f"Error: No exact match found for '{card_name}'. Skipping.", file=sys.stderr)
                    return False
    
                # Select the last valid print from our filtered list
                target_print = exact_matches[-1]
                print(f"Found {len(exact_matches)} exact match(es). Selecting last: '{target_print['text']}'")
                dropdown.select_by_value(target_print['index'])
                # --- END OF NEW FILTERING LOGIC ---
    
                print("Waiting for canvas to stabilize...")
                new_hash = self._wait_for_canvas_stabilization(self.current_canvas_hash)
                if not new_hash or new_hash == self.current_canvas_hash:
                    print(f"Error: Canvas did not change or stabilize for '{card_name}'.", file=sys.stderr)
                    self.current_canvas_hash = new_hash
                    return False
                
                self.current_canvas_hash = new_hash
                return True
            except TimeoutException:
                print(f"Error: Timed out waiting for print list for '{card_name}'.", file=sys.stderr)
                return False
            except Exception as e:
                print(f"An unexpected error occurred importing '{card_name}': {e}", file=sys.stderr)
                return False

    def set_frame(self, frame_value):
        try:
            art_tab = self.wait.until(EC.element_to_be_clickable((By.XPATH, '//*[@id="creator-menu-tabs"]/h3[3]')))
            art_tab.click()
            frame_dropdown = self.wait.until(EC.presence_of_element_located((By.ID, 'autoFrame')))
            Select(frame_dropdown).select_by_value(frame_value)
            print(f"Successfully set frame by value to '{frame_value}'.")
            print("Waiting for frame to apply...")
            self.current_canvas_hash = self._wait_for_canvas_stabilization(self.current_canvas_hash)
        except (TimeoutException, NoSuchElementException) as e:
            print(f"Error setting frame: {e}", file=sys.stderr)
            raise

    def prime_renderer(self, card_names):
        """Loads a series of cards to prime the renderer without saving."""
        print(f"\n--- Starting Renderer Priming with {len(card_names)} cards ---")
        for i, card_name in enumerate(card_names, 1):
            print(f"Priming card {i}/{len(card_names)}: '{card_name}'")
            self._import_and_stabilize(card_name)
        print("--- Renderer Priming Complete ---")

    def import_and_save_card(self, card_name):
        """Imports a card, waits for stabilization, and saves the content."""
        if not self._import_and_stabilize(card_name):
            return

        data_url = self._get_canvas_data_url()
        if not data_url or not data_url.startswith('data:image/png;base64,'):
            print(f"Error: Could not perform final canvas capture for '{card_name}'.", file=sys.stderr)
            return

        try:
            img_data = base64.b64decode(data_url.split(',', 1)[1])
            safe_filename = re.sub(r'[^a-zA-Z0-9_]', '_', card_name)
            output_path = os.path.join(self.download_dir, f"{safe_filename}.png")
            with open(output_path, 'wb') as f:
                f.write(img_data)
            print(f"Saved canvas to '{output_path}'.")
        except Exception as e:
            print(f"An error occurred saving the image for '{card_name}': {e}", file=sys.stderr)

    def close(self):
        if self.driver:
            self.driver.quit()
