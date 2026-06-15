import sys
import re
import random
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select, WebDriverWait
from selenium.common.exceptions import TimeoutException, NoSuchElementException

class PrintMixin:
    def _get_and_filter_prints(self, card_name, is_priming=False, is_token=False, set_code=None) -> tuple[list[dict], bool]:
        """
        Gets all prints from the Card Conjurer UI and filters them based on include/exclude sets.
        Returns the list of prints and a boolean indicating if an include-set filter caused a fallback.
        
        Args:
            card_name: Name of the card to search for
            is_priming: If True, bypasses all filtering
            is_token: If True, searches for tokens specifically
            set_code: Optional set code to target a specific printing.
        """
        max_retries = 3
        
        # Construct search query for the UI
        # We use a simple query to increase reliability. Complex syntax can cause timeouts.
        # Set filtering is handled in Python below.
        search_query = card_name
        if is_token:
            search_query = f"{card_name} token"

        for attempt in range(max_retries):
            try:
                # First, interact with the UI to get all available prints for the card name
                import time
                time.sleep(0.5)
                self.import_save_tab.click()
                
                # --- OPTIMIZATION: Check if current results are already what we need ---
                dropdown_locator = (By.ID, 'import-index')
                try:
                    dropdown_element = self.driver.find_element(*dropdown_locator)
                    current_options = Select(dropdown_element).options
                    if current_options and not current_options[0].get_attribute("disabled"):
                        # Check if the first non-disabled option matches our card name
                        if current_options[0].text.lower().startswith(card_name.lower()):
                            # print(f"   Optimization: Results for '{card_name}' already loaded. Skipping search.")
                            # We still need to populate all_exact_matches
                            all_exact_matches = []
                            for option in current_options:
                                option_text = option.text
                                if option_text.lower().startswith(card_name.lower()):
                                    end_of_name_index = len(card_name)
                                    if len(option_text) == end_of_name_index or option_text[end_of_name_index:end_of_name_index+2] == ' (':
                                        match_data = {'index': option.get_attribute('value'), 'text': option_text, 'set_name': None, 'collector_number': None}
                                        set_info = re.search(r'\(([^#]+?)\s*#([^)]+)\)', option_text)
                                        if set_info:
                                            cc_set = set_info.group(1).strip()
                                            if set_code and cc_set.lower() != set_code.lower(): continue
                                            match_data['set_name'] = cc_set
                                            match_data['collector_number'] = set_info.group(2).strip()
                                        elif set_code: continue
                                        all_exact_matches.append(match_data)
                            
                            if all_exact_matches:
                                break # Skip the actual search and go to filtering
                except (NoSuchElementException, Exception):
                    pass # Fall back to normal search if anything fails
                # ----------------------------------------------------------------------

                import_input = self.wait.until(EC.element_to_be_clickable((By.ID, 'import-name')))
                
                # Robust clear and type
                import_input.click()
                import_input.send_keys(Keys.CONTROL + "a")
                import_input.send_keys(Keys.BACKSPACE)
                
                try:
                    first_option = self.driver.find_element(*dropdown_locator).find_element(By.TAG_NAME, 'option')
                except NoSuchElementException:
                    first_option = None
                
                import_input.send_keys(search_query)
                import_input.send_keys(Keys.ENTER)
                print(f"Searching for '{search_query}' (Attempt {attempt+1}/{max_retries})...")
                
                if first_option:
                    # Wait for the dropdown to update/refresh, but with a shorter timeout
                    # because if it doesn't change, we want to proceed to check the content anyway.
                    try:
                        WebDriverWait(self.driver, 5).until(EC.staleness_of(first_option))
                    except TimeoutException:
                        # If it didn't become stale, maybe it didn't need to refresh (same search)
                        pass
                
                # Wait for the dropdown to have options
                self.wait.until(lambda d: len(Select(d.find_element(*dropdown_locator)).options) > 0)

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
                                cc_set = set_info.group(1).strip()
                                # If a specific set was targeted, filter out anything else immediately
                                if set_code and cc_set.lower() != set_code.lower():
                                    continue
                                    
                                match_data['set_name'] = cc_set
                                match_data['collector_number'] = set_info.group(2).strip()
                            elif set_code:
                                # If we are looking for a set but this result has no set info, skip it
                                continue
                                
                            all_exact_matches.append(match_data)
                
                if not all_exact_matches:
                    print(f"   Warning: No exact match found for '{card_name}'{' in ' + set_code if set_code else ''}.", file=sys.stderr)
                    if attempt < max_retries - 1:
                        print("   Retrying...", file=sys.stderr)
                        continue
                    return [], False # No exact matches found after retries.

                # If we got here, we found matches! Break the loop.
                break

            except TimeoutException:
                print(f"   Warning: Timed out searching for '{search_query}' (Attempt {attempt+1}/{max_retries}).", file=sys.stderr)
                if attempt < max_retries - 1:
                    print("   Retrying...", file=sys.stderr)
                else:
                    print(f"Error: Timed out for '{card_name}' after {max_retries} attempts. Card might not exist.", file=sys.stderr)
                    return [], False
        else:
            # Loop finished without break (all retries failed or no matches found)
            return [], False

        try:
            # --- Priming Logic ---
            # If we are only priming, we return all matches immediately without further set filtering.
            if is_priming:
                print("   Bypassing further filters for priming.")
                return all_exact_matches, False
            
            # --- Specific Set Logic ---
            # If a specific set was requested in the deck list, we've already filtered for it.
            if set_code:
                print(f"   Targeted set found: {set_code} ({len(all_exact_matches)} match(es))")
                return all_exact_matches, False
            
            # --- Token Logic ---
            # If searching for tokens, bypass set filtering (tokens have different set codes with 't' prefix)
            if is_token:
                print("   Bypassing set filters for token search (tokens use 't' prefix sets).")
                return all_exact_matches, False

            # --- Filtering Logic ---
            
            # Import Basic Land Names
            from automator_utils import BASIC_LAND_NAMES

            # Determine which filters to use
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

            # 1. Apply the blacklist first. This list is the "true" base for all further operations.
            prints_after_exclude = all_exact_matches
            if current_exclude_sets:
                prints_after_exclude = [p for p in all_exact_matches if not (p['set_name'] and p['set_name'].lower() in current_exclude_sets)]

            # 2. Apply the whitelist to the already-excluded list.
            final_filtered_prints = prints_after_exclude
            if current_include_sets:
                final_filtered_prints = [p for p in prints_after_exclude if p['set_name'] and p['set_name'].lower() in current_include_sets]

            # --- Fallback Logic ---
            # Determine if an include filter was active and resulted in an empty list.
            filter_failed = bool(current_include_sets and not final_filtered_prints)
            if filter_failed:
                print(f"Warning: No prints for '{card_name}' matched the include filter. Falling back to the post-exclusion list.")
                # Return the prints before the include filter was applied, and indicate fallback.
                return prints_after_exclude, True
            
            # If no fallback needed, return the final filtered prints and indicate no fallback.
            return final_filtered_prints, False

        except Exception as e:
            print(f"An unexpected error occurred for '{card_name}': {e}", file=sys.stderr)
            return [], False

    def _select_prints_from_candidate(self, candidate_prints: list[dict], selection_strategy: str) -> list[dict]:
        """
        Applies a selection strategy to a list of candidate prints.
        This method is used for both Card Conjurer mode selections and Scryfall fallbacks.
        It assumes that the input `candidate_prints` list is sorted newest to oldest for CC dropdowns
        and oldest to newest if derived from Scryfall API results.
        """
        if not candidate_prints:
            return []

        if selection_strategy == 'all':
            # Return all prints if the strategy is 'all'.
            return candidate_prints
        
        if selection_strategy == 'latest':
            # For CC dropdown, newest is first. For Scryfall results (oldest to newest), newest is last.
            # We are calling this on a list already sorted based on the primary source.
            return [candidate_prints[0]] 
        elif selection_strategy == 'earliest':
            # For CC dropdown, earliest is last. For Scryfall results (oldest to newest), earliest is first.
            return [candidate_prints[-1]]
        elif selection_strategy == 'random':
            return [random.choice(candidate_prints)]

        return [] # Should not be reached
