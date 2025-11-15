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

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

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

        except TimeoutException:
            print("Error: Could not find the 'Art' tab or the frame selection dropdown.", file=sys.stderr)
            raise
        except NoSuchElementException:
            print(f"Error: Frame with value '{frame_value}' not found in the dropdown.", file=sys.stderr)
            raise

    def import_and_save_card(self, card_name):
        """
        Imports a card and saves the canvas content directly as a PNG.
        """
        try:
            import_save_tab = self.wait.until(EC.element_to_be_clickable((By.XPATH, '//*[@id="creator-menu-tabs"]/h3[7]')))
            import_save_tab.click()

            import_input = self.wait.until(EC.presence_of_element_located((By.ID, 'import-name')))
            import_input.clear()
            import_input.send_keys(card_name)

            import_button = self.wait.until(EC.element_to_be_clickable((By.ID, 'import-index')))
            import_button.click()
            print(f"Importing card: '{card_name}'...")

            # --- New Canvas Capture Logic ---
            # 1. Explicitly wait for a canvas element to be present.
            self.wait.until(EC.presence_of_element_located((By.TAG_NAME, 'canvas')))

            # 2. Use a more robust script to find the canvas and get its data.
            js_get_canvas_data = """
                const selectors = ['#mainCanvas', '#card-canvas', '#canvas', 'canvas'];
                for (let selector of selectors) {
                    const canvas = document.querySelector(selector);
                    if (canvas) {
                        return canvas.toDataURL('image/png');
                    }
                }
                return null;
            """
            data_url = self.driver.execute_script(js_get_canvas_data)

            if not data_url or not data_url.startswith('data:image/png;base64,'):
                print(f"Error: Could not capture canvas data for '{card_name}'.", file=sys.stderr)
                return

            # 3. Decode the base64 string and save it as a PNG file.
            img_data = base64.b64decode(data_url.split(',', 1)[1])

            safe_filename = re.sub(r'[^a-zA-Z0-9_]', '_', card_name)
            output_path = os.path.join(self.download_dir, f"{safe_filename}.png")

            with open(output_path, 'wb') as f:
                f.write(img_data)
            print(f"Saved canvas to '{output_path}'.")
            # --- End New Logic ---

        except TimeoutException:
            print(f"Error: Timed out while trying to import or save '{card_name}'.", file=sys.stderr)
        except Exception as e:
            print(f"An unexpected error occurred for card '{card_name}': {e}", file=sys.stderr)

    def close(self):
        if self.driver:
            self.driver.quit()
