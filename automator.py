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
from datetime import datetime, timedelta, timezone
from pathlib import Path
from gradio_client import Client, file as gradio_file
from PIL import Image
import io
import unicodedata
from typing import Optional, Tuple, List

# Import utilities
from automator_utils import (
    parse_time_string,
    check_server_file_details,
    generate_safe_filename,
    get_image_mime_type_and_extension,
)

# Import Mixins
from mixins import CanvasMixin, TextMixin, ImageMixin, PrintMixin

# Import Scryfall API utilities from the local package
try:
    from scryfall_utils import ScryfallAPI
except ImportError:
    print("FATAL: Could not import ScryfallAPI from local 'scryfall_utils.py'.", file=sys.stderr)
    sys.exit(1)

class CardConjurerAutomator(CanvasMixin, TextMixin, ImageMixin, PrintMixin):
    """
    A class to automate interactions with the Card Conjurer web application.
    """
    def __init__(self, url, download_dir='.', headless=True, include_sets=None,
                 exclude_sets=None, spells_include_sets=None, spells_exclude_sets=None,
                 basic_land_include_sets=None, basic_land_exclude_sets=None,
                 card_selection_strategy='cardconjurer', set_selection_strategy='earliest',
                 no_match_selection='earliest', render_delay=1.5, white_border=False,
                 pt_bold=False, pt_shadow=None, pt_font_size=None, pt_kerning=None, pt_up=None,
                 title_font_size=None, title_shadow=None, title_kerning=None, title_left=None,
                 type_font_size=None, type_shadow=None, type_kerning=None, type_left=None,
                 flavor_font=None, rules_down=None, rules_bounds_y=None, rules_bounds_height=None,
                 hide_reminder_text=False,
                 image_server=None, image_server_path=None, art_path='/art/', autofit_art=False,
                 upscale_art=False, ilaria_url=None, upscaler_model='RealESRGAN_x2plus', upscaler_factor=4,
                 upload_path=None, upload_secret=None, scryfall_filter=None, save_cc_file=False,
                 overwrite=False, overwrite_older_than=None, overwrite_newer_than=None):
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
        
        # Allow insecure downloads and content
        chrome_options.add_argument("--ignore-certificate-errors")
        chrome_options.add_argument("--allow-running-insecure-content")
        chrome_options.add_argument("--disable-web-security")
        
        # Treat the origin as secure to bypass download blocking
        from urllib.parse import urlparse
        parsed_url = urlparse(url)
        origin = f"{parsed_url.scheme}://{parsed_url.netloc}"
        chrome_options.add_argument(f"--unsafely-treat-insecure-origin-as-secure={origin}")
        
        # Configure preferences for automatic downloads
        prefs = {
            "download.default_directory": os.path.abspath(self.download_dir) if self.download_dir else os.getcwd(),
            "download.prompt_for_download": False,
            "download.directory_upgrade": True,
            "safebrowsing.enabled": False,
            "safebrowsing.disable_download_protection": True,
            "profile.default_content_setting_values.automatic_downloads": 1,
        }
        chrome_options.add_experimental_option("prefs", prefs)
        
        self.driver = webdriver.Chrome(options=chrome_options)
        
        # Use CDP to allow downloads in headless mode
        params = {
            'behavior': 'allow',
            'downloadPath': os.path.abspath(self.download_dir) if self.download_dir else os.getcwd()
        }
        self.driver.execute_cdp_cmd('Page.setDownloadBehavior', params)
        
        self.driver.get(url)
        self.wait = WebDriverWait(self.driver, 15)
        self.wait.until(EC.presence_of_element_located((By.ID, 'creator-menu-tabs')))
        
        # Legacy filters
        self.include_sets = {s.strip().lower() for s in include_sets.split(',')} if include_sets else set()
        self.exclude_sets = {s.strip().lower() for s in exclude_sets.split(',')} if exclude_sets else set()

        # Granular filters
        self.spells_include_sets = {s.strip().lower() for s in spells_include_sets.split(',')} if spells_include_sets else set()
        self.spells_exclude_sets = {s.strip().lower() for s in spells_exclude_sets.split(',')} if spells_exclude_sets else set()
        self.basic_land_include_sets = {s.strip().lower() for s in basic_land_include_sets.split(',')} if basic_land_include_sets else set()
        self.basic_land_exclude_sets = {s.strip().lower() for s in basic_land_exclude_sets.split(',')} if basic_land_exclude_sets else set()
        self.card_selection_strategy = card_selection_strategy
        self.set_selection_strategy = set_selection_strategy
        self.no_match_selection = no_match_selection
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
        self.rules_bounds_y = rules_bounds_y
        self.rules_bounds_height = rules_bounds_height
        self.hide_reminder_text = hide_reminder_text

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
        self.overwrite = overwrite
        self.overwrite_older_than_str = overwrite_older_than
        self.overwrite_newer_than_str = overwrite_newer_than

        self.overwrite_older_than_dt: Optional[datetime] = None
        self.overwrite_newer_than_dt: Optional[datetime] = None
        if self.overwrite_older_than_str:
            self.overwrite_older_than_dt = parse_time_string(self.overwrite_older_than_str)
        if self.overwrite_newer_than_str:
            self.overwrite_newer_than_dt = parse_time_string(self.overwrite_newer_than_str)
        self.upload_path = upload_path
        self.upload_secret = upload_secret # This can be None, which is fine
        self.scryfall_filter = scryfall_filter
        self.save_cc_file = save_cc_file

        # Initialize the Scryfall API client
        self.scryfall_api = ScryfallAPI()
        
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

    def _generate_safe_filename(self, value: str):
        return generate_safe_filename(value)

    def _generate_final_filename(self, card_name, set_name, collector_number):
        safe_card = self._generate_safe_filename(card_name)
        safe_set = self._generate_safe_filename(set_name) if set_name else 'unknown-set'
        safe_num = self._generate_safe_filename(collector_number) if collector_number else 'no-num'
        return f"{safe_card}_{safe_set}_{safe_num}.png"

    def _match_scryfall_to_cc_prints(self, scryfall_results, all_cc_prints):
        """
        Matches Scryfall results to Card Conjurer prints, including cross-referencing via illustration_id.
        """
        matched_prints = []
        processed_illustration_ids = set()

        print(f"   Cross-referencing {len(scryfall_results)} Scryfall result(s) with Card Conjurer prints...")

        for sr in scryfall_results:
            # Check for direct match first
            scryfall_set = sr.get('set')
            scryfall_cn = sr.get('collector_number')
            
            direct_match_found = False
            if scryfall_set and scryfall_cn:
                for cc_print in all_cc_prints:
                    if cc_print.get('set_name', '').lower() == scryfall_set.lower() and cc_print.get('collector_number', '').lower() == str(scryfall_cn).lower():
                        matched_prints.append(cc_print)
                        direct_match_found = True
                        break
            
            if direct_match_found:
                continue

            # If no direct match, try cross-referencing via illustration_id
            illustration_id = sr.get('illustration_id')
            if illustration_id and illustration_id not in processed_illustration_ids:
                processed_illustration_ids.add(illustration_id)
                
                # Query for all prints with this illustration_id
                ill_query = f"illustration_id:{illustration_id} unique:prints game:paper"
                # print(f"      Checking for other prints with illustration_id: {illustration_id}")
                ill_results = self.scryfall_api.search_cards(ill_query, unique="prints", order_by="released", direction="asc")
                
                for ir in ill_results:
                    ir_set = ir.get('set')
                    ir_cn = ir.get('collector_number')
                    if ir_set and ir_cn:
                        for cc_print in all_cc_prints:
                            if cc_print.get('set_name', '').lower() == ir_set.lower() and cc_print.get('collector_number', '').lower() == str(ir_cn).lower():
                                # Avoid duplicates if we already matched this print
                                if cc_print not in matched_prints:
                                    matched_prints.append(cc_print)
                                    # print(f"      -> Found cross-reference match: {cc_print['text']}")
        
        return matched_prints

    def _format_mana_cost(self, mana_cost):
        # Convert {2}{R} to {2}{R} (it's usually already correct from Scryfall)
        # But we might need to handle specific symbols if CC differs.
        return mana_cost

    def _generate_text_with_tags(self, text, font_size=None, shadow=None, kerning=None, left=None, bold=False, up=None):
        if not text: return ""
        tags = []
        if font_size is not None: tags.append(f"{{fontsize{font_size}}}")
        if shadow is not None: tags.append(f"{{shadow{shadow}}}")
        if kerning is not None: tags.append(f"{{kerning{kerning}}}")
        if left is not None: tags.append(f"{{left{left}}}")
        if up is not None: tags.append(f"{{up{up}}}")
        if bold: tags.append("{bold}")
        
        prefix = "".join(tags)
        suffix = "{/bold}" if bold else ""
        return f"{prefix}{text}{suffix}"

    def process_and_capture_card(self, card_name, is_priming=False):
        # Step 1: Get all possible prints from the UI, bypassing filters if priming.
        all_cc_prints, include_filter_failed_cc = self._get_and_filter_prints(card_name, is_priming=is_priming)

        # --- Priming ---
        # If priming, just select the first available print and return.
        if is_priming:
            if all_cc_prints:
                dropdown = Select(self.driver.find_element(By.ID, 'import-index'))
                dropdown.select_by_value(all_cc_prints[0]['index'])
                time.sleep(self.render_delay)
            else:
                print(f"   Error: No prints found for priming card '{card_name}'.", file=sys.stderr)
            return

        prints_to_capture = []
        
        # --- Card Conjurer Mode ---
        if self.card_selection_strategy == 'cardconjurer':
            print(f"--- Card Conjurer Mode for '{card_name}' ---")
            strategy_to_use = self.set_selection_strategy
            
            # If the include filter failed in _get_and_filter_prints, we use the no_match_selection strategy.
            if include_filter_failed_cc:
                if self.no_match_selection == 'skip':
                    print(f"   Skipping card because no prints matched the include filter and --no-match-selection is 'skip'.", file=sys.stderr)
                    return
                strategy_to_use = self.no_match_selection
            
            prints_to_capture = self._select_prints_from_candidate(all_cc_prints, strategy_to_use)

        # --- Scryfall Mode ---
        elif self.card_selection_strategy == 'scryfall':
            print(f"--- Scryfall Mode for '{card_name}' ---")
            
            # 1. Initial Scryfall Query (with set filters)
            base_query_parts = [f'!\"{card_name}\"', 'unique:art', 'game:paper', 'not:covered']
            if self.scryfall_filter:
                base_query_parts.append(self.scryfall_filter)
            query_parts = list(base_query_parts) # Make a copy

            # Determine which filters to use (Granular vs Legacy)
            from automator_utils import BASIC_LAND_NAMES
            current_include_sets = set()
            current_exclude_sets = set()

            if self.include_sets or self.exclude_sets:
                # Legacy mode
                current_include_sets = self.include_sets
                current_exclude_sets = self.exclude_sets
            else:
                # Granular mode
                if card_name in BASIC_LAND_NAMES:
                    current_include_sets = self.basic_land_include_sets
                    current_exclude_sets = self.basic_land_exclude_sets
                else:
                    current_include_sets = self.spells_include_sets
                    current_exclude_sets = self.spells_exclude_sets

            # Add include/exclude set filters for the initial query
            if current_include_sets:
                include_query = " OR ".join([f"set:{s}" for s in current_include_sets])
                query_parts.append(f"({include_query})")
            if current_exclude_sets:
                exclude_query = " ".join([f"-set:{s}" for s in current_exclude_sets])
                query_parts.append(f" {exclude_query}")

            full_query = " ".join(query_parts)
            print(f"   Scryfall query (with filters): {full_query}")
            scryfall_results = self.scryfall_api.search_cards(full_query, unique="art", order_by="released", direction="asc")

            selection_strategy = self.set_selection_strategy # Default to set_selection_strategy

            # 2. Fallback Scryfall Query if initial one yields no results
            if not scryfall_results:
                if self.no_match_selection == 'skip':
                    print(f"   Warning: Initial Scryfall query found no matches. Skipping card as per --no-match-selection.", file=sys.stderr)
                    return

                print(f"   Warning: Initial query found no matches. Stripping set filters and retrying a broader Scryfall search.", file=sys.stderr)
                
                # Construct fallback query without set filters, applying prefer:newest/oldest if specified
                fallback_query_parts = list(base_query_parts)
                if self.no_match_selection == 'latest':
                    fallback_query_parts.append('prefer:newest')
                elif self.no_match_selection == 'earliest':
                    fallback_query_parts.append('prefer:oldest')
                
                fallback_query = " ".join(fallback_query_parts)
                print(f"   Scryfall fallback query: {fallback_query}")
                scryfall_results = self.scryfall_api.search_cards(fallback_query, unique="art", order_by="released", direction="asc")

                if not scryfall_results:
                    print(f"   Error: Fallback Scryfall query also found no results for '{card_name}'. Skipping card.", file=sys.stderr)
                    return

                # If fallback query was used, the selection strategy shifts to no_match_selection
                selection_strategy = self.no_match_selection

            # 3. Match Scryfall results against Card Conjurer UI prints
            matched_prints = self._match_scryfall_to_cc_prints(scryfall_results, all_cc_prints)
            
            # 4. Apply Final Selection from matched prints or fallback to all CC prints
            if not matched_prints:
                if self.no_match_selection == 'skip':
                    print(f"   Warning: Found {len(scryfall_results)} print(s) on Scryfall (and checked cross-references), but none were available in the UI. Skipping card as per --no-match-selection.", file=sys.stderr)
                    return
                
                print(f"   Warning: Found {len(scryfall_results)} print(s) on Scryfall, but none matched in the Card Conjurer UI (even after cross-referencing).", file=sys.stderr)
                print(f"   Applying fallback selection '{self.no_match_selection}' to all available Card Conjurer prints.", file=sys.stderr)
                prints_to_capture = self._select_prints_from_candidate(all_cc_prints, self.no_match_selection)
            else:
                print(f"   Found {len(matched_prints)} matching prints in UI from {len(scryfall_results)} Scryfall results (including cross-references).")
                
                if selection_strategy == 'latest':
                    prints_to_capture = [matched_prints[-1]] # Last item from sorted list is newest (Scryfall results are oldest-to-newest)
                elif selection_strategy == 'earliest':
                    prints_to_capture = [matched_prints[0]] # First item is oldest (Scryfall results are oldest-to-newest)
                elif selection_strategy == 'random':
                    prints_to_capture = [random.choice(matched_prints)]
                else: # 'all'
                    prints_to_capture = matched_prints
        
        # --- Final Check ---
        if not prints_to_capture:
            print(f"Error: No prints selected for '{card_name}' after applying all filters and strategies.", file=sys.stderr)
            return

        # --- Main Capture Loop ---
        print(f"Preparing to capture {len(prints_to_capture)} print(s) for '{card_name}'.")
        dropdown = Select(self.driver.find_element(By.ID, 'import-index'))
        for i, print_data in enumerate(prints_to_capture, 1):
            print(f"-> Capturing {i}/{len(prints_to_capture)}: '{print_data['text']}'")

            # --- OVERWRITE PRE-CHECK ---
            should_skip = False
            if self.upload_path: # Only check for overwrites if we are in an upload mode
                output_filename = self._generate_final_filename(card_name, print_data['set_name'], print_data['collector_number'])
                check_url = urljoin(self.image_server_url, os.path.join(self.upload_path, output_filename))
                
                exists, last_modified = check_server_file_details(check_url)
                
                if exists:
                    if self.overwrite:
                        should_skip = False # Unconditional overwrite
                    elif self.overwrite_older_than_dt:
                        if last_modified and last_modified < self.overwrite_older_than_dt:
                            print(f"   Overwriting '{output_filename}' as server file is older than {self.overwrite_older_than_str}.")
                            should_skip = False
                        else:
                            print(f"   Skipping '{output_filename}', server file is not older than {self.overwrite_older_than_str} (or has no timestamp).")
                            should_skip = True
                    elif self.overwrite_newer_than_dt:
                        if last_modified and last_modified > self.overwrite_newer_than_dt:
                            print(f"   Overwriting '{output_filename}' as server file is newer than {self.overwrite_newer_than_str}.")
                            should_skip = False
                        else:
                            print(f"   Skipping '{output_filename}', server file is not newer than {self.overwrite_newer_than_str} (or has no timestamp).")
                            should_skip = True
                    else: # Default behavior: skip if exists and no overwrite flag
                        print(f"   Skipping '{output_filename}', file exists on server.")
                        should_skip = True
            
            if should_skip:
                continue # Skip to the next print

            self.import_save_tab.click()
            dropdown.select_by_value(print_data['index'])

            # --- NEW: PREPARE AND APPLY CUSTOM ART RIGHT AFTER IMPORT ---
            final_art_url, type_line = None, None
            if self.image_server_url or self.download_dir: # Only prepare art if image server or local download is configured
                final_art_url, type_line = self._prepare_art_asset(card_name, print_data['set_name'], print_data['collector_number'])
            
            if final_art_url:
                self._apply_custom_art(card_name, print_data['set_name'], print_data['collector_number'], final_art_url)
            else:
                print(f"   No custom art URL available for '{card_name}'. Using default art.")

            # Set a flag to see if we need a final delay at the end
            mods_applied = False

            self._apply_text_mods(
                "Title", self.title_font_size, self.title_shadow, self.title_kerning, self.title_left)
            
            self._apply_text_mods(
                "Type", self.type_font_size, self.type_shadow, self.type_kerning, self.type_left)

            self._apply_text_mods(
                 "Power/Toughness", self.pt_font_size, self.pt_shadow, self.pt_kerning, bold=self.pt_bold, up=self.pt_up)

            # --- NEW: Basic Land Rules Text Handling ---
            is_basic_land = False
            if type_line and 'Basic' in type_line and 'Land' in type_line:
                is_basic_land = True

            if is_basic_land:
                mana_symbol = ''
                if 'Plains' in card_name: mana_symbol = '{w}'
                elif 'Island' in card_name: mana_symbol = '{u}'
                elif 'Swamp' in card_name: mana_symbol = '{b}'
                elif 'Mountain' in card_name: mana_symbol = '{r}'
                elif 'Forest' in card_name: mana_symbol = '{g}'
                
                if mana_symbol:
                    rules_text = f"{{down80}}{{fontsize64pt}}{{center}}{mana_symbol}"
                    self._set_rules_text(rules_text)
                else:
                    # Fallback for other basic lands if any
                    self._apply_text_mods("Rules Text", down=self.rules_down)
                    self._apply_flavor_font_mod()
            else:
                self._apply_text_mods("Rules Text", down=self.rules_down)
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

        # --- Save Card to Browser Storage (if enabled) ---
        if self.save_cc_file:
            self._save_card_to_browser_storage()

    def _save_card_to_browser_storage(self):
        """
        Navigates to the Import/Save tab, clicks 'Save Card', and handles the alert.
        """
        try:
            # Navigate to Import/Save tab
            self.import_save_tab.click()
            
            # Find and click the "Save Card" button
            # <button class="input margin-bottom" onclick="saveCard();">Save Card</button>
            save_btn = self.wait.until(EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), 'Save Card')]")))
            save_btn.click()
            
            # Handle the alert/popup
            try:
                # Wait for alert to be present
                WebDriverWait(self.driver, 3).until(EC.alert_is_present())
                alert = self.driver.switch_to.alert
                # print(f"   Alert text: {alert.text}")
                alert.accept()
                print("   Saved card to browser storage.")
            except TimeoutException:
                print("   Warning: No alert appeared after clicking 'Save Card'. It might have saved silently or failed.", file=sys.stderr)
                
        except Exception as e:
            print(f"   Error saving card to browser storage: {e}", file=sys.stderr)

    def download_saved_cards(self, output_filename):
        """
        Downloads all saved cards as a .cardconjurer file and renames it.
        """
        try:
            # Navigate to Import/Save tab
            self.import_save_tab.click()
            
            # Find and click the "Download All" button
            # <button class="input margin-bottom" onclick="downloadSavedCards();">Download All</button>
            download_btn = self.wait.until(EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), 'Download All')]")))
            download_btn.click()
            
            print(f"   Initiated download for '{output_filename}'...")
            
            # Wait for the file to appear in the download directory
            # The default name is typically 'cards.cardconjurer' or similar
            # We'll look for the most recently created .cardconjurer file
            target_dir = self.download_dir if self.download_dir else os.getcwd()
            
            downloaded_file = None
            timeout = 10
            start_time = time.time()
            
            while time.time() - start_time < timeout:
                # List all .cardconjurer files in the directory
                files = [f for f in os.listdir(target_dir) if f.endswith('.cardconjurer')]
                if not files:
                    time.sleep(0.5)
                    continue
                
                # Sort by modification time (newest first)
                files.sort(key=lambda x: os.path.getmtime(os.path.join(target_dir, x)), reverse=True)
                candidate = files[0]
                
                # Check if it's a new file (created within the last few seconds)
                if os.path.getmtime(os.path.join(target_dir, candidate)) > start_time - 5:
                    downloaded_file = os.path.join(target_dir, candidate)
                    break
                
                time.sleep(0.5)
            
            if downloaded_file:
                # Rename the file
                final_path = os.path.join(target_dir, output_filename)
                
                # If destination exists, remove it first
                if os.path.exists(final_path):
                    os.remove(final_path)
                    
                os.rename(downloaded_file, final_path)
                print(f"   Successfully downloaded and saved project file to: {final_path}")
                
                # If upload path is set, we might want to upload this too?
                # The user said "store alongside whatever the output of card images is"
                if self.upload_path:
                    with open(final_path, 'rb') as f:
                        file_data = f.read()
                    self._upload_image(file_data, output_filename) # Reusing _upload_image for convenience
                    print(f"   Uploaded project file to server: {output_filename}")
                    
            else:
                print("   Error: Download timed out. No .cardconjurer file found.", file=sys.stderr)
                
        except Exception as e:
            print(f"   Error downloading saved cards: {e}", file=sys.stderr)



    def render_project_file(self, project_file_path, frame_name):
        """
        Uploads a .cardconjurer project file and iterates through the saved cards to capture them.
        """
        print(f"--- Rendering Project File: {project_file_path} ---")
        try:
            # 1. Upload the project file
            self.import_save_tab.click()
            
            # Find the file input for uploading saved cards
            # <input type="file" accept=".cardconjurer,.txt" class="input margin-bottom" oninput="uploadSavedCards(event);" autocomplete="off">
            # We target it by the oninput attribute to be precise
            file_input = self.driver.find_element(By.XPATH, "//input[@oninput='uploadSavedCards(event);']")
            
            abs_path = os.path.abspath(project_file_path)
            file_input.send_keys(abs_path)
            
            print("   Uploaded project file.")
            time.sleep(2) # Wait for processing
            
            # Enable Autofit globally before processing cards
            # Enable Autofit globally before processing cards
            self.enable_autofit()
            
            # Switch back to Import/Save tab to load cards
            self.import_save_tab.click()
            
            # 2. Iterate through saved cards using the dropdown
            # <select id="load-card-options" ...>
            dropdown_element = self.driver.find_element(By.ID, 'load-card-options')
            select = Select(dropdown_element)
            
            # Get all options except the first one (which is "None selected" or similar)
            options = select.options
            
            # Filter out disabled options or the placeholder
            valid_options = [opt for opt in options if not opt.get_attribute("disabled")]
            
            print(f"   Found {len(valid_options)} cards in project.")
            
            for i in range(len(valid_options)):
                # Re-locate dropdown and options to avoid StaleElementReferenceException
                # and ensure we get the correct text if it was hidden before
                self.import_save_tab.click()
                dropdown_element = self.driver.find_element(By.ID, 'load-card-options')
                select = Select(dropdown_element)
                options = select.options
                valid_options_fresh = [opt for opt in options if not opt.get_attribute("disabled")]
                
                if i >= len(valid_options_fresh):
                    break
                    
                option = valid_options_fresh[i]
                card_name = option.text
                print(f"   Rendering card {i+1}/{len(valid_options)}: '{card_name}'...")
                
                # Select the option to load the card
                select.select_by_visible_text(card_name)
                time.sleep(1.5) # Wait for load
                
                # 3. Apply Frame
                if frame_name:
                    self.set_frame(frame_name)
                    
                # 4. Apply Global Mods (Rules Bounds, Reminder Text)
                # Since loading a card might reset these, we should re-apply them.
                self.apply_rules_text_bounds_mods()
                self.apply_hide_reminder_text()
                
                # 5. Apply White Border (if enabled)
                if self.apply_white_border_on_capture:
                    self.apply_white_border()
                    
                # 6. Capture
                # Capture canvas
                canvas_hash = self._wait_for_canvas_stabilization(self.current_canvas_hash)
                self.current_canvas_hash = canvas_hash
                
                # Get image data
                img_data_b64 = self._get_canvas_data_url()
                if img_data_b64:
                     # Parse base64
                    header, encoded = img_data_b64.split(",", 1)
                    image_data = base64.b64decode(encoded)
                    
                    filename = f"{self._generate_safe_filename(card_name)}.png"
                    
                    # Upload/Save
                    if self.upload_path:
                        self._upload_image(image_data, filename)
                    else:
                        # Save locally
                        save_path = os.path.join(self.download_dir, filename)
                        with open(save_path, "wb") as f:
                            f.write(image_data)
                        print(f"      Saved to {save_path}")

        except Exception as e:
            print(f"   Error rendering project file: {e}", file=sys.stderr)

    def close(self):
        if self.driver:
            try:
                self.driver.quit()
            except:
                pass
