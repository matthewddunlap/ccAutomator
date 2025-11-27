
from mixins.image_mixin import ImageMixin
import sys

class MockAutomator(ImageMixin):
    def __init__(self, image_server_url, download_dir):
        self.image_server_url = image_server_url
        self.download_dir = download_dir
        self.art_path = "art"
    
    def _upload_art_asset(self, image_data, sub_dir, filename):
        print(f"MOCK: Uploading {filename} to {self.image_server_url}")

print("--- Test 1: Image Server Set ---")
automator = MockAutomator(image_server_url="http://example.com", download_dir=".")
automator._save_or_upload_image(b"fake_bytes", "original", "test.png")

print("\n--- Test 2: Image Server None ---")
automator2 = MockAutomator(image_server_url=None, download_dir=".")
automator2._save_or_upload_image(b"fake_bytes", "original", "test.png")
