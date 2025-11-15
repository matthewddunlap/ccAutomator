import time
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

# --- Configuration ---
CARD_CONJURER_URL = "http://mtgproxy:4242/"
FRAME_TO_SET = "Seventh"
# --- End Configuration ---

def debug_white_border_interaction(url, frame_value):
    """
    A focused script to visually debug the white border click interaction.
    """
    print("Setting up VISIBLE browser for debugging...")
    chrome_options = Options()
    # We explicitly DO NOT run in headless mode for this script.
    # If you are running in a Docker container or environment without a screen,
    # this will fail. It's meant to be run where you can see the browser window.
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--start-maximized") # Start maximized to see everything
    
    driver = webdriver.Chrome(options=chrome_options)
    wait = WebDriverWait(driver, 15)

    try:
        print(f"Navigating to {url}...")
        driver.get(url)
        wait.until(EC.presence_of_element_located((By.ID, 'creator-menu-tabs')))

        # --- Step 1: Set the Main Frame Group ---
        print(f"Navigating to 'Art' tab to set frame to '{frame_value}'...")
        art_tab = wait.until(EC.element_to_be_clickable((By.XPATH, "//h3[text()='Art']")))
        art_tab.click()
        frame_dropdown = Select(driver.find_element(By.ID, 'autoFrame'))
        frame_dropdown.select_by_value(frame_value)
        print(f"Frame group set to '{frame_value}'. Pausing for 3 seconds to ensure all JS updates...")
        time.sleep(3) # A generous pause to let the page state settle completely.

        # --- Step 2: Navigate to the Frame Tab ---
        print("Navigating to 'Frame' tab...")
        frame_tab = wait.until(EC.element_to_be_clickable((By.XPATH, "//h3[text()='Frame']")))
        frame_tab.click()
        time.sleep(1)

        # --- Step 3: Find and Analyze the Target Element ---
        white_border_selector = "//div[@id='frame-picker']//img[contains(@src, '/whiteThumb.png')]"
        print(f"Attempting to locate the white border thumbnail with selector: {white_border_selector}")
        
        try:
            white_border_thumb = wait.until(EC.presence_of_element_located((By.XPATH, white_border_selector)))
            
            # Scroll to the element to make sure it's in view
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", white_border_thumb)
            time.sleep(0.5)

            print("\n--- Element State ---")
            print(f"Is Displayed?  {white_border_thumb.is_displayed()}")
            print(f"Is Enabled?    {white_border_thumb.is_enabled()}")
            print(f"Location (X,Y): {white_border_thumb.location}")
            print(f"Size (W,H):     {white_border_thumb.size}")
            print("---------------------\n")

            # --- Step 4: Take Screenshot and Pause for Inspection ---
            screenshot_before = 'debug_screenshot_BEFORE_click.png'
            driver.save_screenshot(screenshot_before)
            print(f"Saved screenshot to '{screenshot_before}'.")
            
            input("The script is now paused. Please check the visible browser window. \n"
                  "Is the white border thumbnail visible and unobstructed? \n"
                  "Press Enter to attempt the double-click...")

            # --- Step 5: Perform the Click and Get Results ---
            print("Attempting JavaScript double-click...")
            driver.execute_script("arguments[0].click(); arguments[0].click();", white_border_thumb)
            print("Click performed. Pausing for 3 seconds to see the result...")
            time.sleep(3)

            screenshot_after = 'debug_screenshot_AFTER_click.png'
            driver.save_screenshot(screenshot_after)
            print(f"Saved screenshot to '{screenshot_after}'.")
            print("\nDebug script finished. Please compare the two screenshots to see if the border changed.")

        except TimeoutException:
            print("\nCRITICAL ERROR: Could not locate the white border thumbnail.", file=sys.stderr)
            driver.save_screenshot('debug_screenshot_FAILURE.png')
            print("Saved a failure screenshot. The element does not appear to exist on the page.", file=sys.stderr)

    except Exception as e:
        print(f"\nAn unexpected error occurred: {e}", file=sys.stderr)
    finally:
        driver.quit()
        print("Browser closed.")

if __name__ == "__main__":
    debug_white_border_interaction(CARD_CONJURER_URL, FRAME_TO_SET)
