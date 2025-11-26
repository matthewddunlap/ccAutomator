import sys
import re
import random
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select
from selenium.common.exceptions import TimeoutException, NoSuchElementException

class PrintMixin:
    def _get_and_filter_prints(self, card_name, is_priming=False, is_token=False) -> tuple[list[dict], bool]:
        """
        Gets all prints from the Card Conjurer UI and filters them based on include/exclude sets.
        Returns the list of prints and a boolean indicating if an include-set filter caused a fallback.
        
        Args:
            card_name: Name of the card to search for
            is_priming: If True, bypasses all filtering
            is_token: If True, bypasses set filtering (tokens have 't' prefix sets like 'tblc')
        """
        max_retries = 3
        for attempt in range(max_retries):
            try:
                # First, interact with the UI to get all available prints for the card name
                import time
                time.sleep(0.5)
                self.import_save_tab.click()
                import_input = self.wait.until(EC.presence_of_element_located((By.ID, 'import-name')))
                import_input.clear()
                dropdown_locator = (By.ID, 'import-index')
                try:
                    first_option = self.driver.find_element(*dropdown_locator).find_element(By.TAG_NAME, 'option')
                except NoSuchElementException:
                    first_option = None
                
                time.sleep(0.2)
                import_input.send_keys(card_name)
                import_input.send_keys(Keys.RETURN)
                print(f"Searching for '{card_name}' (Attempt {attempt+1}/{max_retries})...")
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
                    print(f"   Warning: No exact match found for '{card_name}'.", file=sys.stderr)
                    if attempt < max_retries - 1:
                        print("   Retrying...", file=sys.stderr)
                        continue
                    return [], False # No exact matches found after retries.

                # If we got here, we found matches! Break the loop.
                break

            except TimeoutException:
                print(f"   Warning: Timed out searching for '{card_name}' (Attempt {attempt+1}/{max_retries}).", file=sys.stderr)
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
            # If we are only priming, we return all matches immediately without any filtering.
            if is_priming:
                print("   Bypassing filters for priming.")
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
