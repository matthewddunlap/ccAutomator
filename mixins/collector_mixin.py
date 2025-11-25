import time
import sys
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

class CollectorMixin:
    """
    Mixin for handling interactions with the 'Collector' tab in Card Conjurer.
    """

    def set_collector_info(self, set_code, collector_number):
        """
        Sets the Set Code and Collector Number in the Collector Info tab.
        """
        print(f"   Setting Collector Info: Set='{set_code}', Number='{collector_number}'")
        try:
            # Navigate to Collector tab
            self.collector_tab.click()
            
            # Wait for inputs to be visible
            self.wait.until(EC.visibility_of_element_located((By.ID, 'info-set')))

            # Set Set Code
            if set_code:
                set_input = self.driver.find_element(By.ID, 'info-set')
                self.driver.execute_script("arguments[0].value = arguments[1];", set_input, set_code)
                self.driver.execute_script("arguments[0].dispatchEvent(new Event('input'))", set_input)

            # Set Collector Number
            if collector_number:
                num_input = self.driver.find_element(By.ID, 'info-number')
                self.driver.execute_script("arguments[0].value = arguments[1];", num_input, collector_number)
                self.driver.execute_script("arguments[0].dispatchEvent(new Event('input'))", num_input)
            
            # Short wait for state to settle
            time.sleep(0.5)

        except Exception as e:
            print(f"      Error setting collector info: {e}", file=sys.stderr)

    def get_collector_info(self):
        """
        Reads the Set Code and Collector Number from the Collector Info tab.
        Returns a tuple: (set_code, collector_number)
        """
        try:
            # Navigate to Collector tab
            self.collector_tab.click()
            
            # Wait for inputs to be visible
            self.wait.until(EC.visibility_of_element_located((By.ID, 'info-set')))

            set_input = self.driver.find_element(By.ID, 'info-set')
            num_input = self.driver.find_element(By.ID, 'info-number')

            set_code = set_input.get_attribute('value')
            collector_number = num_input.get_attribute('value')
            
            # print(f"      Read Collector Info: Set='{set_code}', Number='{collector_number}'")
            return set_code, collector_number

        except Exception as e:
            print(f"      Error reading collector info: {e}", file=sys.stderr)
            return None, None
