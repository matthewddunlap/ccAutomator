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
from pathlib import Path
from gradio_client import Client, file as gradio_file
from PIL import Image
import io
import unicodedata
from typing import Optional

class CardConjurerAutomator:
    """
    A class to automate interactions with the Card Conjurer web application.
    """
    def __init__(self, url, download_dir='.', headless=True, include_sets=None,
                 exclude_sets=None, set_selection_strategy='earliest',
                 no_match_skip=False, render_delay=1.5, white_border=False,
                 pt_bold=False, pt_shadow=None, pt_font_size=None, pt_kerning=None, pt_up=None,
                 title_font_size=None, title_shadow=None, title_kerning=None, title_left=None,
                 type_font_size=None, type_shadow=None, type_kerning=None, type_left=None,
                 flavor_font=None, rules_down=None,
                 image_server=None, image_server_path=None, art_path='/localart/art', autofit_art=False,
                 upscale_art=False, ilaria_url=None, upscaler_model='4x-UltraSharp', upscaler_factor=4,
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
        self.pt_up = pt_up

        self.title_font_size = title_font_size
        self.title_shadow = title_shadow
        self.title_kerning = title_kerning
        self.title_left = title_left

        self.flavor_font = flavor_font
        self.rules_down = rules_down

        self.type_font_size = type_font_size
        self.type_shadow = type_shadow
        self.type_kerning = type_kerning
        self.type_left = type_left

        self.app_url = url
        self.image_server_url = image_server
        self.image_server_path = image_server_path if image_server_path else ''
        self.art_path = art_path
        self.autofit_art = autofit_art
        self.upscale_art = upscale_art
        self.ilaria_url = ilaria_url
        self.upscaler_model = upscaler_model
        self.upscaler_factor = upscaler_factor
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

    def _generate_safe_filename(self, value: str):
        if not isinstance(value, str): value = str(value)
        value = value.replace("'", "")
        value = unicodedata.normalize('NFKD', value).encode('ascii', 'ignore').decode('ascii')
        value = re.sub(r'[\s/:<>:"\\|?*&]+', '-', value)
        value = re.sub(r'-+', '-', value)
        value = value.strip('-')
        return value.lower()

    def _generate_final_filename(self, card_name, set_name, collector_number):
        safe_card = self._generate_safe_filename(card_name)
        safe_set = self._generate_safe_filename(set_name) if set_name else 'unknown-set'
        safe_num = self._generate_safe_filename(collector_number) if collector_number else 'no-num'
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

            # Wait for the change to render on the canvas
            time.sleep(self.render_delay)

        except Exception as e:
            print(f"      An error occurred while applying mods to '{field_name}': {e}", file=sys.stderr)


    # --- 3. ADD THE NEW _apply_custom_art METHOD ---
    def _apply_custom_art(self, card_name, set_name, collector_number, art_url_to_apply: str):
        """
        Applies custom art to the card in Card Conjurer.
        """
        if not art_url_to_apply:
            return

        url_to_paste = art_url_to_apply
        
        # If the image server and the app are on the same host, we might need to provide a relative path.
        if self.image_server_url and self.app_url:
            try:
                from urllib.parse import urlparse
                parsed_server_url = urlparse(self.image_server_url)
                parsed_app_url = urlparse(self.app_url)

                if parsed_server_url.netloc == parsed_app_url.netloc:
                    # The servers are on the same host, so we should use a relative path.
                    parsed_art_url = urlparse(art_url_to_apply)
                    path = parsed_art_url.path.lstrip('/')
                    
                    # Card Conjurer's local server has a special /local_art/ root
                    if path.startswith('local_art/'):
                        url_to_paste = path[len('local_art/'):]
                    else:
                        url_to_paste = path

                    print(f"   Trimming URL for same-host server. Pasting: {url_to_paste}")
            except ImportError:
                # Fallback if urlparse is not available (should not happen)
                pass

        print(f"   Applying custom art from: {url_to_paste}")

        try:
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

        except requests.exceptions.RequestException as e:
            print(f"   Network error checking for custom art '{art_url_to_apply}': {e}", file=sys.stderr)

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

    def _upload_art_asset(self, image_data, sub_dir, filename):
        """
        Uploads an art asset to the configured server endpoint.
        """
        if not self.image_server_url:
            print("   Error: --image-server is not set. Cannot upload art asset.", file=sys.stderr)
            return

        # Construct the full URL for the art asset
        full_upload_url = urljoin(self.image_server_url, os.path.join(self.art_path, sub_dir, filename))
        
        print(f"   Uploading art asset to {full_upload_url} (using PUT)...")
        
        headers = {'Content-Type': 'image/png'} # Assuming PNG for now, can be improved
        if self.upload_secret:
            headers['X-Upload-Secret'] = self.upload_secret

        try:
            response = requests.put(full_upload_url, data=image_data, headers=headers, timeout=60)
            response.raise_for_status()
            print(f"   Upload successful.")
        except requests.exceptions.HTTPError as e:
            print(f"   Error: Upload failed with status {e.response.status_code}.", file=sys.stderr)
            print(f"   Server Response: {e.response.text}", file=sys.stderr)
        except requests.exceptions.RequestException as e:
            print(f"   Error: A network error occurred during upload: {e}", file=sys.stderr)

    def _save_or_upload_image(self, img_bytes: bytes, sub_dir: str, filename: str):
        """
        Saves the image locally or uploads it to the image server, depending on configuration.
        """
        if not img_bytes:
            print(f"   Error: No image bytes provided for '{filename}' in '{sub_dir}'. Cannot save empty image.", file=sys.stderr)
            return

        if self.download_dir: # Local save mode
            try:
                # The art path is relative to the download dir
                local_save_dir = Path(self.download_dir) / self.art_path.strip('/') / sub_dir.strip('/')
                local_save_dir.mkdir(parents=True, exist_ok=True)
                local_file_path = local_save_dir / filename
                with open(local_file_path, 'wb') as f:
                    f.write(img_bytes)
                print(f"   Saved image locally to: {local_file_path}")
            except Exception as e:
                print(f"   Error: Local save error for '{filename}': {e}", file=sys.stderr)

        elif self.image_server_url: # Upload mode
            self._upload_art_asset(img_bytes, sub_dir, filename)
        else:
            print(f"   Warning: No output destination configured for '{filename}'. Image not saved/uploaded.", file=sys.stderr)

    def _fetch_image_bytes(self, url: str, purpose: str = "generic") -> Optional[bytes]:
        if not url: return None
        try:
            print(f"   Fetching image for {purpose} from: {url}")
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            # No api_delay_seconds for now, as we are not hitting Scryfall API directly for every image fetch
            return response.content
        except requests.RequestException as e:
            print(f"   Error: Failed to fetch image for {purpose} from {url}: {e}", file=sys.stderr)
            return None
            
    def _get_image_mime_type_and_extension(self, image_bytes: bytes) -> tuple[Optional[str], Optional[str]]:
        try:
            fmt = None
            try:
                img = Image.open(io.BytesIO(image_bytes))
                fmt = img.format
                img.close()
            except Exception:
                pass
            if fmt == "JPEG": return "image/jpeg", ".jpg"
            if fmt == "PNG": return "image/png", ".png"
            if fmt == "GIF": return "image/gif", ".gif"
            if fmt == "WEBP": return "image/webp", ".webp"
            if image_bytes.startswith(b'\xff\xd8\xff'): return "image/jpeg", ".jpg"
            if image_bytes.startswith(b'\x89PNG\r\n\x1a\n'): return "image/png", ".png"
            if image_bytes.startswith(b'GIF87a') or image_bytes.startswith(b'GIF89a'): return "image/gif", ".gif"
            if image_bytes.startswith(b'RIFF') and len(image_bytes) > 12 and image_bytes[8:12] == b'WEBP': return "image/webp", ".webp"
            return "application/octet-stream", ""
        except Exception as e:
            print(f"   Error determining image type: {e}", file=sys.stderr)
            return "application/octet-stream", ""

    def _check_if_file_exists_on_server(self, public_url: str) -> bool:
        if not public_url: return False
        try:
            r = requests.head(public_url, timeout=15, allow_redirects=True)
            if r.status_code == 200: print(f"   Exists: {public_url}"); return True
            if r.status_code == 404: print(f"   Not found: {public_url}"); return False
            print(f"   Warning: Status {r.status_code} checking {public_url}. Assuming not existent.", file=sys.stderr); return False
        except Exception as e: print(f"   Error checking {public_url}: {e}. Assuming not existent.", file=sys.stderr); return False

    def _upscale_image_with_ilaria(self, original_art_path_for_upscaler: str, filename: str, mime: Optional[str], outscale: int) -> Optional[bytes]:
        if not self.ilaria_url:
            print("   Error: Ilaria URL not set. Upscaling will be skipped.", file=sys.stderr)
            return None
        if not original_art_path_for_upscaler:
            print(f"   Error: No original art path for '{filename}'. Cannot upscale without a source image.", file=sys.stderr)
            return None

        img_bytes = None
        # If original_art_path_for_upscaler is a local path (e.g., from self.download_dir)
        if self.download_dir and original_art_path_for_upscaler.startswith(self.image_server_path.strip('/')):
            local_path = Path(self.download_dir) / original_art_path_for_upscaler
            print(f"   Upscaling: Reading original image from local path: {local_path}")
            try:
                with open(local_path, "rb") as f:
                    img_bytes = f.read()
            except FileNotFoundError:
                print(f"   Error: Upscaling failed: Original image not found at local path {local_path}", file=sys.stderr)
                return None
            except Exception as e:
                print(f"   Error: Upscaling failed: Could not read local file {local_path}: {e}", file=sys.stderr)
                return None
        else: # Assume it's a URL
            img_bytes = self._fetch_image_bytes(original_art_path_for_upscaler, "Upscaling with gradio_client")

        if not img_bytes:
            print(f"   Error: Failed to get image bytes from {original_art_path_for_upscaler}. Cannot upscale without image data.", file=sys.stderr)
            return None

        try:
            print(f"   Connecting to Ilaria Upscaler at {self.ilaria_url} via gradio_client.")
            client = Client(self.ilaria_url)

            # Create a temporary file for gradio_client
            temp_dir = Path('/tmp') # Using /tmp for temporary files
            temp_dir.mkdir(parents=True, exist_ok=True)
            temp_input_path = temp_dir / f"ilaria_input_{self._generate_safe_filename(filename)}"
            
            with open(temp_input_path, "wb") as f:
                f.write(img_bytes)

            print(f"   Upscaling {filename} using model '{self.upscaler_model}' via gradio_client.")
            result = client.predict(
                img=gradio_file(str(temp_input_path)), # Pass Path object or string
                model_name=self.upscaler_model,
                denoise_strength=0.5, # Hardcoded for now, can be made configurable
                face_enhance=False,   # Hardcoded for now, can be made configurable
                outscale=outscale,
                api_name="/realesrgan"
            )

            # Gradio client returns a path to the result file
            if isinstance(result, tuple):
                result_path = result[0]
            else:
                result_path = result

            print(f"   Upscaled image path: {result_path}")

            with open(result_path, "rb") as f:
                upscaled_bytes = f.read()
            
            # Clean up temporary files
            os.remove(temp_input_path)
            os.remove(result_path) # Gradio client creates a temp file, remove it

            return upscaled_bytes

        except Exception as e:
            print(f"   Error: Gradio upscaling error for '{filename}': {e}", file=sys.stderr)
            return None

    def _get_scryfall_art_crop_url(self, card_name: str, set_code: str, collector_number: str) -> Optional[str]:
        """
        Fetches the art_crop URL for a given card from the Scryfall API.
        """
        search_url = f"https://api.scryfall.com/cards/{set_code}/{collector_number}"
        print(f"   Fetching Scryfall data for '{card_name}' ({set_code}/{collector_number}) from: {search_url}")
        try:
            response = requests.get(search_url, timeout=10)
            response.raise_for_status()
            card_data = response.json()
            
            art_crop_url = ""
            if 'image_uris' in card_data and 'art_crop' in card_data['image_uris']:
                art_crop_url = card_data['image_uris']['art_crop']
            elif 'card_faces' in card_data and card_data['card_faces']:
                for face in card_data['card_faces']:
                    if 'image_uris' in face and 'art_crop' in face['image_uris']:
                        art_crop_url = face['image_uris']['art_crop']
                        break
            
            if art_crop_url:
                print(f"   Found art_crop URL: {art_crop_url}")
                return art_crop_url
            else:
                print(f"   Warning: No art_crop URL found for '{card_name}' ({set_code}/{collector_number}).", file=sys.stderr)
                return None
        except requests.exceptions.RequestException as e:
            print(f"   Error fetching Scryfall data for '{card_name}' ({set_code}/{collector_number}): {e}", file=sys.stderr)
            return None

    def _prepare_art_asset(self, card_name: str, set_code: str, collector_number: str) -> Optional[str]:
        """
        Prepares the art asset for a card, including fetching, upscaling, and saving/uploading.
        Returns the URL of the final art asset to be used in Card Conjurer.
        """
        print(f"   Preparing art asset for '{card_name}' ({set_code}/{collector_number})...")
        
        # 1. Get original art_crop URL from Scryfall
        art_crop_url = self._get_scryfall_art_crop_url(card_name, set_code, collector_number)
        if not art_crop_url:
            print(f"   Warning: Could not get Scryfall art_crop URL for '{card_name}'. Skipping art preparation.", file=sys.stderr)
            return None

        final_art_source_url = art_crop_url
        hosted_original_art_url: Optional[str] = None
        hosted_upscaled_art_url: Optional[str] = None
        original_art_bytes_for_pipeline: Optional[bytes] = None
        original_image_mime_type: Optional[str] = None
        
        _, initial_ext_guess = os.path.splitext(art_crop_url.split('?')[0])
        if not initial_ext_guess or initial_ext_guess.lower() not in ['.jpg', '.jpeg', '.png', '.gif', '.webp']:
            initial_ext_guess = ".jpg"
        original_image_actual_ext: str = initial_ext_guess.lower()
        
        sanitized_card_name = self._generate_safe_filename(card_name)
        set_code_sanitized = self._generate_safe_filename(set_code)
        collector_number_sanitized = self._generate_safe_filename(collector_number)

        # --- Art Processing Pipeline ---
        # 1. Check for existing original art on server/local
        if self.image_server_url or self.download_dir:
            possible_extensions = [original_image_actual_ext] + [ext for ext in ['.jpg', '.png', '.jpeg', '.webp', '.gif'] if ext != original_image_actual_ext]
            for ext_try in possible_extensions:
                base_filename_check = f"{sanitized_card_name}_{set_code_sanitized}_{collector_number_sanitized}{ext_try}"
                potential_url = urljoin(self.image_server_url, os.path.join(self.art_path, "original", base_filename_check)) if self.image_server_url else None
                
                if potential_url and self._check_if_file_exists_on_server(potential_url):
                    print(f"   Found existing original art on server: {potential_url}")
                    hosted_original_art_url = potential_url
                    # We don't fetch bytes here, just confirm existence. Bytes will be fetched if upscaling is needed.
                    break
                elif self.download_dir:
                    local_path_check = Path(self.download_dir) / self.art_path.strip('/') / "original" / base_filename_check
                    if local_path_check.exists():
                        print(f"   Found existing original art locally: {local_path_check}")
                        # Construct a URL that points to the local file, assuming image_server_url is configured
                        if self.image_server_url:
                            hosted_original_art_url = urljoin(self.image_server_url, os.path.join(self.art_path, "original", base_filename_check))
                        else:
                            # If no image_server_url, we can't provide a hosted URL, but we know it exists locally
                            hosted_original_art_url = str(local_path_check) # This will be a local file path, not a URL
                        break
        
        # 2. Fetch original art bytes if not already hosted or if upscaling is enabled
        if not hosted_original_art_url or self.upscale_art:
            original_art_bytes_for_pipeline = self._fetch_image_bytes(art_crop_url, "Scryfall original")
            if original_art_bytes_for_pipeline:
                mime, ext = self._get_image_mime_type_and_extension(original_art_bytes_for_pipeline)
                if ext: original_image_actual_ext = ext
                if mime: original_image_mime_type = mime
                
                # Save/upload original if not already hosted
                if not hosted_original_art_url:
                    filename_to_output = f"{sanitized_card_name}_{set_code_sanitized}_{collector_number_sanitized}{original_image_actual_ext}"
                    self._save_or_upload_image(original_art_bytes_for_pipeline, "original", filename_to_output)
                    if self.image_server_url:
                        hosted_original_art_url = urljoin(self.image_server_url, os.path.join(self.art_path, "original", filename_to_output))
                    elif self.download_dir:
                        hosted_original_art_url = str(Path(self.download_dir) / self.art_path.strip('/') / "original" / filename_to_output)
            else:
                print(f"   Error: Failed to fetch original art from Scryfall for '{card_name}'. Cannot proceed with art preparation.", file=sys.stderr)
                return None

        # 3. Upscale if requested and original bytes are available
        if self.upscale_art and original_art_bytes_for_pipeline and self.ilaria_url:
            upscaled_dir = f"{self._generate_safe_filename(self.upscaler_model)}-{self.upscaler_factor}x"
            upscaled_filename_check = f"{sanitized_card_name}_{set_code_sanitized}_{collector_number_sanitized}.png" # Upscaled output is typically PNG

            # Check if upscaled version already exists
            expected_upscaled_server_url = urljoin(self.image_server_url, os.path.join(self.art_path, upscaled_dir, upscaled_filename_check)) if self.image_server_url else None
            expected_upscaled_local_path = Path(self.download_dir) / self.art_path.strip('/') / upscaled_dir / upscaled_filename_check if self.download_dir else None

            if (expected_upscaled_server_url and self._check_if_file_exists_on_server(expected_upscaled_server_url)) or \
               (expected_upscaled_local_path and expected_upscaled_local_path.exists()):
                print(f"   Found existing upscaled art for '{card_name}'.")
                if self.image_server_url:
                    hosted_upscaled_art_url = expected_upscaled_server_url
                elif self.download_dir:
                    hosted_upscaled_art_url = str(expected_upscaled_local_path)
            else:
                # Determine the path/URL to the original art for the upscaler
                # If we saved locally, the upscaler can read from the local path
                original_art_path_for_upscaler = hosted_original_art_url if self.download_dir else art_crop_url
                
                upscaled_bytes = self._upscale_image_with_ilaria(original_art_path_for_upscaler, f"{sanitized_card_name}_{set_code_sanitized}_{collector_number_sanitized}", original_image_mime_type, self.upscaler_factor)
                if upscaled_bytes:
                    _, upscaled_ext = self._get_image_mime_type_and_extension(upscaled_bytes)
                    upscaled_filename = f"{sanitized_card_name}_{set_code_sanitized}_{collector_number_sanitized}{upscaled_ext or '.png'}"
                    self._save_or_upload_image(upscaled_bytes, upscaled_dir, upscaled_filename)
                    if self.image_server_url:
                        hosted_upscaled_art_url = urljoin(self.image_server_url, os.path.join(self.art_path, upscaled_dir, upscaled_filename))
                    elif self.download_dir:
                        hosted_upscaled_art_url = str(Path(self.download_dir) / self.art_path.strip('/') / upscaled_dir / upscaled_filename)
        
        # 4. Determine the final art source URL to return
        if hosted_upscaled_art_url:
            final_art_source_url = hosted_upscaled_art_url
            print(f"   Using upscaled art: {final_art_source_url}")
        elif hosted_original_art_url:
            final_art_source_url = hosted_original_art_url
            print(f"   Using original hosted art: {final_art_source_url}")
        else:
            final_art_source_url = art_crop_url
            print(f"   Using Scryfall art_crop URL: {final_art_source_url}")

        return final_art_source_url

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

            # --- NEW: PREPARE AND APPLY CUSTOM ART RIGHT AFTER IMPORT ---
            final_art_url = None
            if self.image_server_url or self.download_dir: # Only prepare art if image server or local download is configured
                final_art_url = self._prepare_art_asset(card_name, print_data['set_name'], print_data['collector_number'])
            
            if final_art_url:
                self._apply_custom_art(card_name, print_data['set_name'], print_data['collector_number'], final_art_url)
            else:
                print(f"   No custom art URL available for '{card_name}'. Using default art.")

            # Set a flag to see if we need an extra delay at the end
            mods_applied = False

            self._apply_text_mods(
                "Title", self.title_font_size, self.title_shadow, self.title_kerning, self.title_left)
            
            self._apply_text_mods(
                "Type", self.type_font_size, self.type_shadow, self.type_kerning, self.type_left)

            self._apply_text_mods(
                 "Power/Toughness", self.pt_font_size, self.pt_shadow, self.pt_kerning, bold=self.pt_bold, up=self.pt_up)

            self._apply_text_mods(
                  "Rules Text", down=self.rules_down)

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
                filename = self._generate_final_filename(card_name, print_data['set_name'], print_data['collector_number'])
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

    def _process_all_text_modifications(self):
        """
        Orchestrator for all text modifications to prevent race conditions.
        Returns True if any modification was successfully made.
        """
        # --- UPDATED: Check for new parameters ---
        has_mods_to_apply = any([
            self.title_font_size, self.title_shadow, self.title_kerning, self.title_left,
            self.type_font_size, self.type_shadow, self.type_kerning, self.type_left,
            self.pt_font_size, self.pt_shadow, self.pt_kerning, self.pt_bold, self.pt_up,
            self.flavor_font, self.rules_down
        ])
        if not has_mods_to_apply:
            return False

        self.text_tab.click()
        
        any_text_mod_made = False
        if self._apply_text_mods("Title", self.title_font_size, self.title_shadow, self.title_kerning, self.title_left): any_text_mod_made = True
        if self._apply_text_mods("Type", self.type_font_size, self.type_shadow, self.type_kerning, self.type_left): any_text_mod_made = True
        # --- UPDATED: Pass the 'up' parameter for Power/Toughness ---
        if self._apply_text_mods("Power/Toughness", self.pt_font_size, self.pt_shadow, self.pt_kerning, bold=self.pt_bold, up=self.pt_up): any_text_mod_made = True
        # --- NEW: Add a call for prepending to Rules Text ---
        if self._apply_text_mods("Rules Text", down=self.rules_down): any_text_mod_made = True
        # Flavor font mod is called separately as it has unique logic (inserting, not prepending)
        if self._apply_flavor_font_mod(): any_text_mod_made = True
        
        return any_text_mod_made

    def close(self):
        if self.driver:
            self.driver.quit()
