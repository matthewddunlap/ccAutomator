"""
Utility functions for interacting with the Scryfall API
"""
import logging
import requests
import time
from typing import Dict, Optional, List

logger = logging.getLogger(__name__)

class ScryfallAPIException(Exception):
    def __init__(self, message, details=None):
        super().__init__(message)
        self.details = details
    
    def __str__(self):
        if self.details:
            return f"{super().__str__()} (Details: {self.details})"
        return super().__str__()

class ScryfallAPI:
    def __init__(self):
        self.base_url = "https://api.scryfall.com"
    
    def search_cards(self, query: str, unique="prints", order_by="released", direction="asc") -> List[Dict]:
        """Search for cards using the Scryfall API. Returns a list of all cards matching the query by handling pagination."""
        all_cards = []
        search_url = f"{self.base_url}/cards/search"
        params = {
            "q": query,
            "unique": unique,
            "order": order_by,
            "dir": direction
        }
        
        page_num = 1
        current_search_url = search_url # Use a variable for the current page URL

        while current_search_url:
            try:
                # Only pass params on the first request, subsequent requests use the full next_page URL
                current_params = params if page_num == 1 else None
                # logger.debug(f"Fetching page {page_num} for query '{query}': {current_search_url} with params {current_params}")
                
                response = requests.get(current_search_url, params=current_params, timeout=20)
                response.raise_for_status() 
                
                page_data = response.json()
                data_list = page_data.get('data', [])
                if not data_list and page_num == 1: # No data on first page
                    logger.info(f"No cards found for query: {query}")
                    return []
                
                all_cards.extend(data_list)
                
                current_search_url = page_data.get('next_page') 
                page_num += 1
                if current_search_url:
                    # logger.debug(f"Found next page: {current_search_url}")
                    time.sleep(0.1) # Scryfall API polite delay
                # else:
                    # logger.debug("No more pages found.")

            except requests.exceptions.HTTPError as http_err:
                if http_err.response.status_code == 404:
                    logger.warning(f"No cards found for query: {query}")
                else:
                    raise ScryfallAPIException(f"HTTP error occurred while searching cards (query: '{query}', page: {page_num})", f"{http_err} - {http_err.response.text}")
                break 
            except requests.RequestException as req_err:
                raise ScryfallAPIException(f"Request error occurred while searching cards (query: '{query}', page: {page_num})", str(req_err))
            except Exception as e:
                raise ScryfallAPIException(f"Unexpected error searching cards (query: '{query}', page: {page_num})", str(e))
        
        if page_num > 2 or (page_num == 2 and not current_search_url): # Log only if multiple pages or only one full page
             logger.info(f"Found {len(all_cards)} total cards across {page_num-1} page(s) for query: {query}")
        return all_cards

    def get_token_sets_for_parents(self, parent_set_codes: set) -> set:
        """
        Given a set of parent set codes (e.g., {'blb', 'woe'}), returns a set of corresponding
        token set codes (e.g., {'tblb', 'twoe'}).
        """
        if not parent_set_codes:
            return set()
            
        token_sets = set()
        # Scryfall doesn't have a direct "get token set for parent" endpoint, but we can search for sets.
        # Or simpler: search for *cards* that are tokens and have the parent set code? No, that's circular.
        # Better: Search for sets where set_type:token. But we can't filter sets by parent_set_code in the /sets endpoint easily?
        # Actually, the /sets endpoint returns all sets. We could fetch all sets and filter locally, but that's heavy.
        # Alternatively, we can guess: usually 't' + parent_code. But not always (e.g. 't' + 'dom' -> 'tdom'?).
        # Let's try to be smart. We can query for *any* card in the token sets that links to the parent set?
        # No, that's complicated.
        
        # Let's fetch ALL sets once (it's not that huge, ~500 sets) and cache it? 
        # Or just fetch sets and filter.
        
        # Actually, Scryfall has a /sets endpoint.
        try:
            response = requests.get(f"{self.base_url}/sets", timeout=20)
            response.raise_for_status()
            all_sets = response.json().get('data', [])
            
            for s in all_sets:
                if s.get('set_type') == 'token' and s.get('parent_set_code') in parent_set_codes:
                    token_sets.add(s.get('code'))
                    
            logger.info(f"Mapped parent sets {parent_set_codes} to token sets {token_sets}")
            return token_sets
            
        except Exception as e:
            logger.error(f"Error fetching/mapping token sets: {e}")
            return set()
