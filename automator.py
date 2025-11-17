import time
import re
import os
import base64
import sys
import hashlib
import random
import requests
from urllib.parse import urljoin
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

class CardConjurerAutomator:
    """
    A class to automate interactions with the Card Conjurer web application.
    """
    def __init__(self, url, download_dir='.', headless=True, include_sets=None,
                 exclude_sets=None, set_selection_strategy='earliest',
                 no_match_skip=False, render_delay=1.5, white_border=False,
                 pt_bold=False, pt_shadow=None, pt_font_size=None, pt_kerning=None,
                 title_font_size=None, title_shadow=None, title_kerning=None, title_left=None,
                 type_font_size=None, type_shadow=None, type_kerning=None, type_left=None, flavor_font=None,
                 image_server=None, image_server_path=None, autofit_art=False,
                 upload_path=None, upload_secret=None):
        """
        Initializes the WebDriver and stores the automation strategy.
        """
        self.download_dir = download_dir
        # Only create the directory if a path was actually provided
        if self.download_dir and not os.path.exists(self.download_dir):
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
        
        self.include_sets = {s.strip().lower() for s in include_sets.split(',')} if include_sets else set()
        self.exclude_sets = {s.strip().lower() for s in exclude_sets.split(',')} if exclude_sets else set()
        self.set_selection_strategy = set_selection_strategy
        self.no_match_skip = no_match_skip
        self.render_delay = render_delay
        self.apply_white_border_on_capture = white_border

        self.pt_bold = pt_bold
        self.pt_shadow = pt_shadow
        self.pt_font_size = pt_font_size
        self.pt_kerning = pt_kerning

        self.title_font_size = title_font_size
        self.title_shadow = title_shadow
        self.title_kerning = title_kerning
        self.title_left = title_left

        self.flavor_font = flavor_font

        self.type_font_size = type_font_size
        self.type_shadow = type_shadow
        self.type_kerning = type_kerning
        self.type_left = type_left

        self.app_url = url 
        self.image_server_url = image_server
        self.image_server_path = image_server_path if image_server_path else ''
        self.autofit_art = autofit_art
        self.upload_path = upload_path
        self.upload_secret = upload_secret # This can be None, which is fine
        
        self.current_canvas_hash = None
        self.STABILIZE_TIMEOUT = 10
        self.STABILITY_CHECKS = 3
        self.STABILITY_INTERVAL = 0.3

        self.import_save_tab = self.wait.until(EC.element_to_be_clickable((By.XPATH, '//*[@id="creator-menu-tabs"]/h3[7]')))
        self.text_tab = self.wait.until(EC.element_to_be_clickable((By.XPATH, "//h3[text()='Text']")))
        self.art_tab = self.wait.until(EC.element_to_be_clickable((By.XPATH, "//h3[text()='Art']")))
        
        try:
            import_save_tab = self.wait.until(EC.element_to_be_clickable((By.XPATH, '//*[@id="creator-menu-tabs"]/h3[7]')))
            import_save_tab.click()
            all_art_checkbox_input = self.wait.until(EC.presence_of_element_located((By.ID, 'importAllPrints')))
            if not all_art_checkbox_input.is_selected():
                label_for_checkbox = self.driver.find_element(By.XPATH, "//label[.//input[@id='importAllPrints']]")
                label_for_checkbox.click()
                print("Set 'All Art Version' checkbox to ON.")
        except (TimeoutException, NoSuchElementException) as e:
            print(f"Error setting 'All Art Version' on init: {e}", file=sys.stderr)
            raise

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
                time.sleep(self.STABILITY_INTERVAL); continue
            current_hash = hashlib.md5(data_url.encode('utf-8')).hexdigest()
            if current_hash == initial_hash:
                time.sleep(self.STABILITY_INTERVAL); continue
            if current_hash == last_hash: stable_count += 1
            else: last_hash = current_hash; stable_count = 1
            if stable_count >= self.STABILITY_CHECKS:
                print(f"Canvas stabilized with new hash: {current_hash[:10]}..."); return current_hash
            time.sleep(self.STABILITY_INTERVAL)
        print("Warning: Timeout waiting for canvas to stabilize.", file=sys.stderr); return None

    def _generate_safe_filename(self, card_name, set_name, collector_number):
        safe_card = re.sub(r'[^a-z0-9-]', '', card_name.lower().replace(' ', '-'))
        safe_set = re.sub(r'[^a-z0-9-]', '', set_name.lower().replace(' ', '-')) if set_name else 'unknown-set'
        safe_num = re.sub(r'[^a-z0-9-]', '', str(collector_number).lower()) if collector_number else 'no-num'
        return f"{safe_card}_{safe_set}_{safe_num}.png"

    def _get_and_filter_prints(self, card_name):
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
            self.wait.until(lambda d: len(d.find_element(*dropdown_locator).find_elements(By.TAG_NAME, 'option')) > 0)

            all_exact_matches = []
            dropdown = Select(self.driver.find_element(*dropdown_locator))
            for option in dropdown.options:
                option_text = option.text
                if option_text.lower().startswith(card_name.lower()):
                    end_of_name_index = len(card_name)
                    if len(option_text) == end_of_name_index or option_text[end_of_name_index:end_of_name_index+2] == ' (':
                        match_data = {'index': option.get_attribute('value'), 'text': option_text, 'set_name': None, 'collector_number': None}
                        set_info = re.search(r'\(([^#]+?)\s*#([^)]+)\)', option_text)
                        if set_info:
                            match_data['set_name'] = set_info.group(1).strip()
                            match_data['collector_number'] = set_info.group(2).strip()
                        all_exact_matches.append(match_data)
            
            if not all_exact_matches:
                print(f"Error: No exact match found for '{card_name}'. Skipping.", file=sys.stderr); return []

            # --- START OF CORRECTED FILTERING LOGIC ---
            
            # 1. Apply the blacklist first. This list is the "true" base for all further operations.
            prints_after_exclude = all_exact_matches
            if self.exclude_sets:
                prints_after_exclude = [p for p in all_exact_matches if not (p['set_name'] and p['set_name'].lower() in self.exclude_sets)]

            # 2. Apply the whitelist to the already-excluded list.
            final_filtered_prints = prints_after_exclude
            if self.include_sets:
                final_filtered_prints = [p for p in prints_after_exclude if p['set_name'] and p['set_name'].lower() in self.include_sets]

            # 3. Handle the results and fallback logic.
            # The fallback condition is: an include filter was active, but it produced an empty list.
            if not final_filtered_prints and self.include_sets:
                if self.no_match_skip:
                    print(f"Skipping '{card_name}': No prints matched the include/exclude filters.")
                    return []
                else:
                    print(f"Warning: No prints for '{card_name}' matched the include filter. Falling back to the post-exclusion list.")
                    # CORRECTED: Fall back to the list that has been filtered by exclude, not the original.
                    return prints_after_exclude
            
            return final_filtered_prints
            # --- END OF CORRECTED FILTERING LOGIC ---

#            filtered_prints = all_exact_matches
#            if self.exclude_sets:
#                filtered_prints = [p for p in filtered_prints if not (p['set_name'] and p['set_name'].lower() in self.exclude_sets)]
#            if self.include_sets:
#                filtered_prints = [p for p in filtered_prints if p['set_name'] and p['set_name'].lower() in self.include_sets]
#
#            if not filtered_prints and (self.include_sets or self.exclude_sets):
#                if self.no_match_skip:
#                    print(f"Skipping '{card_name}': No prints matched the include/exclude filters."); return []
#                else:
#                    print(f"Warning: No prints for '{card_name}' matched filters. Falling back to all prints."); return all_exact_matches
#            
#            return filtered_prints
        except TimeoutException:
            print(f"Error: Timed out for '{card_name}'. Card might not exist.", file=sys.stderr); return []
        except Exception as e:
            print(f"An unexpected error occurred for '{card_name}': {e}", file=sys.stderr); return []

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
                print(f"      Found {flavor} tag. Injected font size tag.")
                
                time.sleep(self.render_delay)
            else:
                print("      No {flavor} tag found. Skipping.")

        except Exception as e:
            print(f"      An error occurred while applying flavor text mods: {e}", file=sys.stderr)


    def _apply_text_mods(self, field_name, font_size=None, shadow=None, kerning=None, left=None, bold=False):
        """
        Generic method to apply modifications to a specific text field (e.g., Title, Type).
        """
        # If no modifications are specified for this field, do nothing.
        if all(arg is None for arg in [font_size, shadow, kerning, left]) and not bold:
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
            if bold: tags.append("{bold}")
            
            prefix = "".join(tags)
            suffix = "{/bold}" if bold else ""

            if current_text and current_text.strip():
                new_text = f"{prefix}{current_text}{suffix}"
                
                self.driver.execute_script("arguments[0].value = arguments[1];", text_input, new_text)
                self.driver.execute_script("arguments[0].dispatchEvent(new Event('input'))", text_input)
                print(f"      '{field_name}' changed from '{current_text}' to '{new_text}'.")

            # Wait for the change to render on the canvas
            time.sleep(self.render_delay)

        except Exception as e:
            print(f"      An error occurred while applying mods to '{field_name}': {e}", file=sys.stderr)


    # --- 3. ADD THE NEW _apply_custom_art METHOD ---
    def _apply_custom_art(self, card_name, set_name, collector_number):
        """
        Checks for custom art on a web server and, if found, applies it to the card.
        """
        if not self.image_server_url:
            return

        # Generate the expected filename for the art file
        image_filename = self._generate_safe_filename(card_name, set_name, collector_number)
        
        # Construct the full URL to check for the art's existence
        full_art_url = urljoin(urljoin(self.image_server_url, self.image_server_path), image_filename)

        try:
            # Use a HEAD request to efficiently check for the file's existence without downloading it
            response = requests.head(full_art_url, timeout=5)
            if response.status_code == 200:
                print(f"   Found custom art at: {full_art_url}")

                # Determine the final URL to paste based on the special trimming logic
                url_to_paste = ""
                if self.image_server_url in self.app_url and self.image_server_path.startswith('/local_art/'):
                    prefix_to_trim = '/local_art/'
                    trimmed_path = self.image_server_path[len(prefix_to_trim):]
                    url_to_paste = urljoin(trimmed_path, image_filename)
                    print(f"   Trimming URL for local server. Pasting: {url_to_paste}")
                else:
                    url_to_paste = full_art_url

                # Navigate to the art tab and paste the URL
                self.art_tab.click()

                # --- NEW: Handle Autofit Checkbox ---
                if self.autofit_art:
                    print("   Ensuring Autofit is enabled...")
                    try:
                        autofit_checkbox = self.wait.until(EC.presence_of_element_located((By.ID, 'art-update-autofit')))
                        if not autofit_checkbox.is_selected():
                            # Click the parent label, which is more reliable for custom checkboxes
                            label_for_autofit = self.driver.find_element(By.XPATH, "//label[.//input[@id='art-update-autofit']]")
                            label_for_autofit.click()
                            print("   'Autofit when setting art' checkbox enabled.")
                    except Exception as e:
                        print(f"   Warning: Could not set the autofit checkbox. {e}", file=sys.stderr)
                # --- END OF NEW LOGIC ---
                
                art_url_input_selector = "//h5[contains(text(), 'Choose/upload your art')]/following-sibling::div//input[@type='url']"
                art_url_input = self.wait.until(EC.presence_of_element_located((By.XPATH, art_url_input_selector)))
                
                art_url_input.clear()
                art_url_input.send_keys(url_to_paste)

                # Press Enter to submit the URL and trigger the art load.
                art_url_input.send_keys(Keys.RETURN)

                # Wait for the new art to load and the canvas to stabilize
                print("   Waiting for custom art to apply...")
                self.current_canvas_hash = self._wait_for_canvas_stabilization(self.current_canvas_hash)
            else:
                print(f"   Custom art not found at {full_art_url} (Status: {response.status_code}). Using default art.")

        except requests.exceptions.RequestException as e:
            print(f"   Network error checking for custom art '{full_art_url}': {e}", file=sys.stderr)

    # --- 2. ADD THE NEW _upload_image METHOD ---
    def _upload_image(self, image_data, filename):
        """
        Uploads the given image data to the configured server endpoint
        using the HTTP PUT method.
        """
        # --- THE FIX: Use requests.put and send raw data ---
        
        # 1. Construct the full, final URL for the file, including the filename.
        #    A PUT request needs the complete destination URL.
        full_upload_url = os.path.join(self.image_server_url, self.upload_path.lstrip('/'), filename)
        
        print(f"   Uploading to {full_upload_url} (using PUT)...")
        
        # 2. Set the Content-Type header so the server knows it's a PNG image.
        headers = {'Content-Type': 'image/png'}
        
        # 3. Add the optional security secret if provided.
        if self.upload_secret:
            headers['X-Upload-Secret'] = self.upload_secret

        try:
            # 4. Use requests.put() and send the image_data directly in the 'data' parameter.
            #    We also use raise_for_status() to automatically catch bad responses (like 403 Forbidden).
            response = requests.put(full_upload_url, data=image_data, headers=headers, timeout=60)
            response.raise_for_status()  # This will raise an HTTPError for 4xx or 5xx responses.

            # If raise_for_status() doesn't raise an error, the upload was successful.
            print(f"   Upload successful.")

        except requests.exceptions.HTTPError as e:
            # This catches specific HTTP errors like 403 Forbidden, 405 Method Not Allowed, 500 Server Error, etc.
            print(f"   Error: Upload failed with status {e.response.status_code}.", file=sys.stderr)
            print(f"   Server Response: {e.response.text}", file=sys.stderr)
        except requests.exceptions.RequestException as e:
            # This catches network-level errors (e.g., DNS failure, connection refused).
            print(f"   Error: A network error occurred during upload: {e}", file=sys.stderr)


    def process_and_capture_card(self, card_name, is_priming=False):
        candidate_prints = self._get_and_filter_prints(card_name)
        if not candidate_prints:
            return

        prints_to_capture = []
        if self.set_selection_strategy == 'all':
            prints_to_capture = candidate_prints
        else:
            if self.set_selection_strategy == 'latest': representative_print = candidate_prints[0]
            elif self.set_selection_strategy == 'random': representative_print = random.choice(candidate_prints)
            else: representative_print = candidate_prints[-1]
            
            target_set = representative_print['set_name']
            if not target_set:
                prints_to_capture = [representative_print]
            else:
                prints_to_capture = [p for p in candidate_prints if p['set_name'] == target_set]
        
        if is_priming:
            dropdown = Select(self.driver.find_element(By.ID, 'import-index'))
            dropdown.select_by_value(prints_to_capture[0]['index'])
            time.sleep(self.render_delay)
            return

        print(f"Preparing to capture {len(prints_to_capture)} print(s) for '{card_name}'.")
        dropdown = Select(self.driver.find_element(By.ID, 'import-index'))
        for i, print_data in enumerate(prints_to_capture, 1):
            print(f"-> Capturing {i}/{len(prints_to_capture)}: '{print_data['text']}'")
            self.import_save_tab.click()
            dropdown.select_by_value(print_data['index'])

            # --- NEW: APPLY CUSTOM ART RIGHT AFTER IMPORT ---
            self._apply_custom_art(card_name, print_data['set_name'], print_data['collector_number'])

            # Set a flag to see if we need an extra delay at the end
            mods_applied = False

            self._apply_text_mods(
                "Title", self.title_font_size, self.title_shadow, self.title_kerning, self.title_left)
            
            self._apply_text_mods(
                "Type", self.type_font_size, self.type_shadow, self.type_kerning, self.type_left)

            self._apply_text_mods(
                "Power/Toughness", self.pt_font_size, self.pt_shadow, self.pt_kerning, bold=self.pt_bold)

            self._apply_flavor_font_mod()

            if self.apply_white_border_on_capture:
                self.apply_white_border()
                mods_applied = True

            # If no modifications were made that include their own delays,
            # we must add the default render delay here.
            if not mods_applied:
                time.sleep(self.render_delay)

            data_url = self._get_canvas_data_url()
            if not data_url or not data_url.startswith('data:image/png;base64,'):
                print(f"   Error: Could not capture canvas.", file=sys.stderr); continue
            try:
                img_data = base64.b64decode(data_url.split(',', 1)[1])
                filename = self._generate_safe_filename(card_name, print_data['set_name'], print_data['collector_number'])
                # --- REVISED, CLEANER LOGIC ---
                if self.upload_path:
                    # Upload mode is active
                    self._upload_image(img_data, filename)
                else:
                    # Local save mode is active
                    output_path = os.path.join(self.download_dir, filename)
                    with open(output_path, 'wb') as f:
                        f.write(img_data)
                    print(f"   Saved locally to '{output_path}'.")
                # --- END OF REVISED LOGIC ---

            except Exception as e:
                print(f"   Error processing or saving/uploading image data: {e}", file=sys.stderr)

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

#            # 6. Wait for the canvas to stabilize to confirm the change
#            print("Waiting for white border to apply to the canvas...")
#            self.current_canvas_hash = self._wait_for_canvas_stabilization(self.current_canvas_hash)
#            
#            if self.current_canvas_hash is None:
#                 print("Warning: Canvas did not stabilize after applying white border. The change may not have registered.", file=sys.stderr)
#            else:
#                 print("Successfully applied white border.")
#
#        except TimeoutException:
#            print("Error: Timed out trying to find or apply the white border.", file=sys.stderr)
#            print("The thumbnail with src '/whiteThumb.png' may not be present for this frame.", file=sys.stderr)
#            raise
        except Exception as e:
            print(f"An unexpected error occurred while applying the white border: {e}", file=sys.stderr)
            raise

    def close(self):
        if self.driver:
            self.driver.quit()
