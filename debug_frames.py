import argparse
import sys
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException

def main():
    """
    Connects to Card Conjurer, navigates to the frame selection dropdown,
    and prints all available options to identify the correct name.
    """
    parser = argparse.ArgumentParser(
        description="Debug script to list available frames in Card Conjurer."
    )
    parser.add_argument(
        '--url',
        required=True,
        help="The URL for the Card Conjurer web app."
    )
    args = parser.parse_args()

    print("Setting up browser...")
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--window-size=1200,900")

    driver = None
    try:
        driver = webdriver.Chrome(options=chrome_options)
        wait = WebDriverWait(driver, 15)

        print(f"Navigating to {args.url}...")
        driver.get(args.url)
        wait.until(EC.presence_of_element_located((By.ID, 'creator-menu-tabs')))

        print("Clicking 'Art' tab...")
        art_tab = wait.until(EC.element_to_be_clickable((By.XPATH, '//*[@id="creator-menu-tabs"]/h3[3]')))
        art_tab.click()

        print("Finding frame dropdown and listing options...")
        frame_dropdown = wait.until(EC.presence_of_element_located((By.ID, 'autoFrame')))
        options = frame_dropdown.find_elements(By.TAG_NAME, 'option')

        print("\n--- Available Frames ---")
        for option in options:
            text = option.text
            value = option.get_attribute('value')
            print(f"Text: \"{text}\", Value: \"{value}\"")
        print("------------------------\n")

    except TimeoutException as e:
        print(f"\nAn error occurred: Timed out waiting for an element.", file=sys.stderr)
        print(f"Details: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"\nAn unexpected error occurred: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        if driver:
            driver.quit()
        print("Browser closed.")

if __name__ == "__main__":
    main()
