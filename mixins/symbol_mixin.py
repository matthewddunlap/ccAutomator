import time
import sys
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC

class SymbolMixin:
    """
    Mixin for handling interactions with the 'Set Symbol' tab in Card Conjurer.
    """

    def set_set_symbol(self, set_code):
        """
        Sets the Set Code in the Set Symbol tab and triggers a reload.
        """
        if not set_code:
            return

        print(f"   Setting Set Symbol to: '{set_code}'")
        try:
            # Navigate to Set Symbol tab (usually h3[4])
            self.symbol_tab.click()

            # Wait for input to be visible
            set_input = self.wait.until(EC.visibility_of_element_located((By.ID, 'set-symbol-code')))

            # Set the value using JavaScript to be sure
            self.driver.execute_script("arguments[0].value = arguments[1];", set_input, set_code)
            self.driver.execute_script("arguments[0].dispatchEvent(new Event('input'))", set_input)
            self.driver.execute_script("arguments[0].dispatchEvent(new Event('change'))", set_input)

            # Slight delay after populating to avoid race conditions
            time.sleep(0.5)

            # Simulate Enter key to trigger reload
            set_input.send_keys(Keys.ENTER)
            print(f"      Set symbol code '{set_code}' entered and reloaded.")

            # Wait for rendering/symbol to load
            time.sleep(self.render_delay)

        except Exception as e:
            print(f"      Error setting set symbol: {e}", file=sys.stderr)
